import os
import re
import time
import uuid
import json
import shutil
import threading
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_file, session
from werkzeug.utils import secure_filename
import yt_dlp

# Detect environment
IS_VERCEL = os.environ.get('VERCEL', False)

# Initialize Flask without socketio for Vercel
app = Flask(__name__)
app.secret_key = "yanktube_secret_key"

# Remove the SERVER_NAME configuration

# Set temporary folder
DOWNLOAD_FOLDER = '/tmp/downloads' if IS_VERCEL else 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Only set up socketio if not on Vercel
if not IS_VERCEL:
    from flask_socketio import SocketIO, emit, join_room
    socketio = SocketIO(app, cors_allowed_origins="*")

# Create download folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERMANENT_FOLDER = os.path.join(BASE_DIR, 'downloads')

# Create folders if they don't exist
os.makedirs(PERMANENT_FOLDER, exist_ok=True)

# Dictionary to track active downloads
active_downloads = {}

@app.route('/')
def index():
    # Get theme from session if available
    theme = session.get('theme', 'light')
    return render_template('index.html', theme=theme, is_vercel=IS_VERCEL)

@app.route('/set_theme', methods=['POST'])
def set_theme():
    """Set the theme preference in session"""
    theme = request.form.get('theme', 'light')
    session['theme'] = theme
    return jsonify({'success': True})

@app.route('/fetch_info', methods=['POST'])
def fetch_info():
    """Fetch video information from YouTube"""
    url = request.form.get('url')
    
    if not url:
        flash('Please enter a valid YouTube URL', 'error')
        return redirect(url_for('index'))
    
    try:
        # Configure yt-dlp options
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'format': 'best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Check if it's a playlist and get the first video
            if 'entries' in info:
                info = info['entries'][0]
            
            # Create a simplified video info object
            video_info = {
                'id': info.get('id'),
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'duration_string': None,  # Will be set below
                'uploader': info.get('uploader'),
                'channel_url': info.get('uploader_url'),
                'view_count': info.get('view_count'),
                'view_count_formatted': None,  # Will be set below
                'like_count': info.get('like_count'),
                'like_count_formatted': None,  # Will be set below
                'upload_date': info.get('upload_date'),
                'upload_date_formatted': None,  # Will be set below
                'description': info.get('description'),
                'webpage_url': url
            }
            
            # Format duration
            if video_info['duration']:
                minutes, seconds = divmod(video_info['duration'], 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    video_info['duration_string'] = f"{hours}h {minutes}m {seconds}s"
                else:
                    video_info['duration_string'] = f"{minutes}m {seconds}s"
            else:
                video_info['duration_string'] = "Unknown"
                
            # Format view count
            if video_info['view_count']:
                video_info['view_count_formatted'] = f"{video_info['view_count']:,}"
            else:
                video_info['view_count_formatted'] = "Unknown"
                
            # Format like count
            if video_info['like_count']:
                video_info['like_count_formatted'] = f"{video_info['like_count']:,}"
            else:
                video_info['like_count_formatted'] = "Not available"
                
            # Format upload date
            if video_info['upload_date'] and len(video_info['upload_date']) == 8:
                year = video_info['upload_date'][:4]
                month = video_info['upload_date'][4:6]
                day = video_info['upload_date'][6:8]
                video_info['upload_date_formatted'] = f"{year}-{month}-{day}"
            else:
                video_info['upload_date_formatted'] = "Unknown"
            
            # Process available formats
            formats = []
            
            # Add "Best Audio" option first
            formats.append({
                'format_id': 'bestaudio',
                'format_note': 'Best Audio',
                'resolution': 'Audio Only',
                'ext': 'mp3',
                'filesize': info.get('filesize', 0),
                'vcodec': 'none',
                'acodec': 'best',
                'size_str': 'Variable',
                'filesize_approx': 10000000,  # Approximate 10MB for sorting
                'audio_only': True
            })
            
            # Add "Best Audio + Video" option next
            formats.append({
                'format_id': 'bestvideo+bestaudio',
                'format_note': 'Best Quality',
                'resolution': 'Best',
                'ext': 'mp4',
                'filesize': info.get('filesize', 0),
                'vcodec': 'best',
                'acodec': 'best',
                'size_str': 'Variable',
                'filesize_approx': 50000000,  # Approximate 50MB for sorting
                'audio_only': False
            })
            
            # Add "4K" option if available - FIX THE ERROR HERE
            has_4k = False
            for fmt in info.get('formats', []):
                height = fmt.get('height')
                if height is not None and height >= 2160:
                    has_4k = True
                    break
                    
            if has_4k:
                formats.append({
                    'format_id': 'bestvideo[height>=2160]+bestaudio/best[height>=2160]',
                    'format_note': '4K Ultra HD',
                    'resolution': '3840x2160',
                    'ext': 'mp4',
                    'filesize': 0,
                    'vcodec': 'best',
                    'acodec': 'best',
                    'size_str': 'Large',
                    'filesize_approx': 100000000,  # Approximate 100MB for sorting
                    'audio_only': False
                })
            
            # Add "1080p" option
            formats.append({
                'format_id': 'bestvideo[height<=1080][height>=720]+bestaudio/best[height<=1080][height>=720]',
                'format_note': '1080p HD',
                'resolution': '1920x1080',
                'ext': 'mp4',
                'filesize': 0,
                'vcodec': 'best',
                'acodec': 'best',
                'size_str': 'Medium',
                'filesize_approx': 30000000,  # Approximate 30MB for sorting
                'audio_only': False
            })
            
            # Add "720p" option
            formats.append({
                'format_id': 'bestvideo[height<=720][height>=480]+bestaudio/best[height<=720][height>=480]',
                'format_note': '720p HD',
                'resolution': '1280x720',
                'ext': 'mp4',
                'filesize': 0,
                'vcodec': 'best',
                'acodec': 'best',
                'size_str': 'Small',
                'filesize_approx': 20000000,  # Approximate 20MB for sorting
                'audio_only': False
            })
            
            # Add "480p" option
            formats.append({
                'format_id': 'bestvideo[height<=480][height>=360]+bestaudio/best[height<=480][height>=360]',
                'format_note': '480p',
                'resolution': '854x480',
                'ext': 'mp4',
                'filesize': 0,
                'vcodec': 'best',
                'acodec': 'best',
                'size_str': 'Very Small',
                'filesize_approx': 15000000,  # Approximate 15MB for sorting
                'audio_only': False
            })
            
            # Add "360p" option for low bandwidth
            formats.append({
                'format_id': 'bestvideo[height<=360][height>=240]+bestaudio/best[height<=360][height>=240]',
                'format_note': '360p',
                'resolution': '640x360',
                'ext': 'mp4',
                'filesize': 0,
                'vcodec': 'best',
                'acodec': 'best',
                'size_str': 'Minimal',
                'filesize_approx': 10000000,  # Approximate 10MB for sorting
                'audio_only': False
            })
            
            # Process all other formats
            for fmt in info.get('formats', []):
                # Skip formats without video (except audio-only above)
                vcodec = fmt.get('vcodec', '')
                if vcodec == 'none' or 'audio only' in fmt.get('format', '').lower():
                    continue
                
                # Get resolution
                width = fmt.get('width', 0)
                height = fmt.get('height', 0)
                
                if width and height:
                    resolution = f"{width}x{height}"
                else:
                    resolution = fmt.get('format_note', 'Unknown')
                
                # Get filesize
                filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                
                if filesize:
                    if filesize >= 1073741824:  # 1 GB
                        size_str = f"{filesize / 1073741824:.1f} GB"
                    elif filesize >= 1048576:  # 1 MB
                        size_str = f"{filesize / 1048576:.1f} MB"
                    else:
                        size_str = f"{filesize / 1024:.1f} KB"
                else:
                    size_str = "Unknown"
                    filesize = width * height * 500  # Approximate size based on resolution
                
                format_id = fmt.get('format_id', '')
                ext = fmt.get('ext', 'mp4')
                
                # Create format object with all needed info
                format_obj = {
                    'format_id': format_id,
                    'format_note': fmt.get('format_note', ''),
                    'resolution': resolution,
                    'ext': ext,
                    'filesize': filesize,
                    'vcodec': fmt.get('vcodec', ''),
                    'acodec': fmt.get('acodec', ''),
                    'size_str': size_str,
                    'filesize_approx': filesize,
                    'audio_only': False
                }
                
                formats.append(format_obj)
            
            # Sort formats by filesize (largest to smallest), keeping the best options at top
            special_formats = formats[:7]  # Keep our special options at the top (including the new 360p option)
            regular_formats = formats[7:]  # Skip the special options
            regular_formats.sort(key=lambda x: x.get('filesize_approx', 0), reverse=True)
            formats = special_formats + regular_formats  # Combine special options with sorted formats
            
            # Pass theme to template
            theme = session.get('theme', 'light')
            return render_template('video_info.html', video=video_info, formats=formats, url=url, theme=theme, is_vercel=IS_VERCEL)
    
    except Exception as e:
        print(f"Error in fetch_info: {str(e)}")
        flash(f'Failed to fetch video information: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/start_download', methods=['POST'])
def start_download():
    """Start downloading the video"""
    url = request.form.get('url')
    format_id = request.form.get('format')
    audio_only = 'audio_only' in request.form
    
    if not url or not format_id:
        flash('Invalid request. Please try again.', 'error')
        return redirect(url_for('index'))
    
    # Generate a unique ID for this download
    download_id = str(uuid.uuid4())
    
    # Initialize in active downloads with proper structure
    active_downloads[download_id] = {
        'status': 'initializing',
        'filename': None
    }
    
    # Start the download process in a background thread
    download_thread = threading.Thread(
        target=download_video, 
        args=(url, format_id, audio_only, download_id)
    )
    download_thread.daemon = True
    download_thread.start()
    
    # Pass theme to template
    theme = session.get('theme', 'light')
    return render_template('download_status.html', download_id=download_id, theme=theme, is_vercel=IS_VERCEL)

def download_video(url, format_id, audio_only, download_id):
    """Download the video or audio and emit progress events"""
    temp_dir = None
    try:
        # Update the active_downloads with initial status
        active_downloads[download_id] = {
            'status': 'downloading',
            'filename': None
        }
        
        # Create a unique temp directory for this download
        temp_dir = os.path.join(DOWNLOAD_FOLDER, f"temp_{download_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Generate unique filename with timestamp
        timestamp = int(time.time())
        
        # Configure yt-dlp options
        # If format_id is 'bestaudio' or audio_only checkbox is checked, download audio only
        if format_id == 'bestaudio' or (audio_only and 'bestvideo' not in format_id):
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, f'%(title)s_{timestamp}.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'progress_hooks': [lambda d: progress_hook(d, download_id)]
            }
        else:
            # Fix for video quality
            if format_id == 'bestvideo+bestaudio':
                format_spec = 'bestvideo+bestaudio/best'
            else:
                format_spec = f"{format_id}+bestaudio/best"
            
            ydl_opts = {
                'format': format_spec,
                'outtmpl': os.path.join(temp_dir, f'%(title)s_{timestamp}.%(ext)s'),
                'merge_output_format': 'mp4',  # Merge into MP4 when possible
                'quiet': True,
                'progress_hooks': [lambda d: progress_hook(d, download_id)]
            }
        
        # Check if download has been cancelled
        if download_id not in active_downloads:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return
            
        # Download the video/audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Check if download has been cancelled after download
        if download_id not in active_downloads:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return
            
        # Get the filename of the downloaded file
        files = os.listdir(temp_dir)
        if not files:
            raise Exception("Download failed - no file was created")
            
        # Move file to the main download folder with a secure filename
        downloaded_file = os.path.join(temp_dir, files[0])
        
        # Extract original filename without timestamp or path
        original_name = os.path.basename(downloaded_file)
        
        # Ensure YankTube appears only once in the filename
        if original_name.startswith('YankTube_'):
            # If it already has YankTube prefix, keep it as is
            secure_name = secure_filename(original_name)
        else:
            # Add YankTube prefix
            new_filename = f"YankTube_{original_name}"
            secure_name = secure_filename(new_filename)
        
        # Move to final location
        dest_path = os.path.join(DOWNLOAD_FOLDER, secure_name)
        
        # If file already exists, add timestamp to make it unique
        if os.path.exists(dest_path):
            name, ext = os.path.splitext(secure_name)
            secure_name = f"{name}_{timestamp}{ext}"
            dest_path = os.path.join(DOWNLOAD_FOLDER, secure_name)
        
        # Copy the file to the destination
        shutil.copy2(downloaded_file, dest_path)
        
        # Get file size and type for client info
        file_size = os.path.getsize(dest_path)
        file_type = 'audio/mp3' if audio_only else 'video/mp4'
        
        # Store download info in active_downloads
        active_downloads[download_id] = {
            'status': 'complete',
            'filename': secure_name,
            'path': dest_path,
            'original_name': original_name
        }
        
        # Generate URL for the file (either with app context or manually)
        try:
            with app.app_context():
                download_url = url_for('download_file', filename=secure_name, _external=True)
        except Exception as e:
            print(f"Error generating URL: {e}")
            # Fallback to manual URL construction if url_for fails
            download_url = f"/download/{secure_name}"
            
        # Get file info for the client
        file_info = {
            'name': os.path.basename(downloaded_file),
            'size': file_size,
            'type': file_type,
            'download_url': download_url
        }
        
        # Emit completion event with download URL
        if not IS_VERCEL:
            socketio.emit('complete', {
                'download_url': download_url,
                'file_info': file_info
            }, room=download_id)
    
    except Exception as e:
        print(f"Error in download_video: {str(e)}")
        if download_id in active_downloads:
            active_downloads[download_id] = {
                'status': 'error',
                'error': str(e)
            }
            if not IS_VERCEL:
                socketio.emit('error', {'error': str(e)}, room=download_id)
        
        # Clean up temp directory in case of error
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

def progress_hook(d, download_id):
    """Progress hook for yt-dlp to track download progress"""
    if d['status'] == 'downloading':
        try:
            # Calculate percent
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded_bytes = d.get('downloaded_bytes', 0)
            
            if total_bytes > 0:
                percent = (downloaded_bytes / total_bytes) * 100
            else:
                percent = 0
                
            # Emit progress event
            if not IS_VERCEL:
                socketio.emit('progress', {
                    'percent': percent,
                    'downloaded_bytes': downloaded_bytes,
                    'total_bytes': total_bytes,
                    'speed': d.get('speed', 0),
                    'eta': d.get('eta', 0)
                }, room=download_id)
            else:
                progress_info = {
                    "status": "downloading",
                    "progress": percent,
                    "downloaded": downloaded_bytes,
                    "total": total_bytes,
                    "speed": d.get('speed', 0),
                    "eta": d.get('eta', 0)
                }
                # Write to file for API polling
                with open(os.path.join(DOWNLOAD_FOLDER, f"{download_id}_progress.json"), 'w') as f:
                    json.dump(progress_info, f)
        except Exception as e:
            print(f"Error in progress_hook: {str(e)}")
    elif d['status'] == 'finished':
        # Notify that download is complete, now processing
        if not IS_VERCEL:
            socketio.emit('processing', {
                'message': 'Download complete, now processing file...'
            }, room=download_id)
        else:
            progress_info = {"status": "finished", "filename": d.get('filename')}
            with open(os.path.join(DOWNLOAD_FOLDER, f"{download_id}_progress.json"), 'w') as f:
                json.dump(progress_info, f)

@app.route('/download/<path:filename>')
def download_file(filename):
    """Serve the file to the browser as an attachment for download"""
    try:
        print(f"Download request for filename: {filename}")
        
        # Try different potential paths for the file
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"ERROR: File not found at path: {file_path}")
            print(f"Files in download folder: {os.listdir(DOWNLOAD_FOLDER)}")
            
            # Try to find a file with similar name
            for file in os.listdir(DOWNLOAD_FOLDER):
                if filename in file:
                    file_path = os.path.join(DOWNLOAD_FOLDER, file)
                    print(f"Found similar file: {file_path}")
                    break
            
            # If still not found, return error
            if not os.path.exists(file_path):
                flash('File not found. Please try downloading again.', 'error')
                return redirect(url_for('index'))
        
        print(f"File found! Size: {os.path.getsize(file_path)} bytes")
        
        # Determine content type
        import mimetypes
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            # Default to binary stream if type cannot be determined
            content_type = 'application/octet-stream'
        
        print(f"Using content type: {content_type}")
        
        # Clean up the filename for display
        display_filename = os.path.basename(file_path)
        
        # Create direct file response with correct headers
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=display_filename,
            mimetype=content_type
        )
        
        # Add additional headers to ensure browser shows save dialog
        response.headers["Content-Disposition"] = f'attachment; filename="{display_filename}"'
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        return response
        
    except Exception as e:
        print(f"Error in download_file: {str(e)}")
        flash(f'Error downloading file: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/save_file/<download_id>', methods=['POST'])
def save_file(download_id):
    """Save the downloaded file to a permanent location"""
    try:
        location = request.form.get('location', PERMANENT_FOLDER)
        
        # Make sure the download exists and is complete
        if download_id not in active_downloads:
            return jsonify({'success': False, 'error': 'Download not found'})
        
        download_info = active_downloads[download_id]
        if not isinstance(download_info, dict) or download_info.get('status') != 'complete':
            return jsonify({'success': False, 'error': 'Download not complete'})
        
        # Get source file path
        filename = download_info.get('filename')
        if not filename:
            return jsonify({'success': False, 'error': 'Filename not found'})
        
        source_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if not os.path.exists(source_path):
            return jsonify({'success': False, 'error': 'Source file not found'})
        
        # Create destination path
        dest_path = os.path.join(location, filename)
        
        # Make sure the destination directory exists
        os.makedirs(location, exist_ok=True)
        
        # Copy the file (don't move, as user might want to download again)
        shutil.copy2(source_path, dest_path)
        
        return jsonify({
            'success': True, 
            'location': dest_path,
            'filename': filename
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/cancel_download/<download_id>', methods=['POST'])
def cancel_download(download_id):
    """Cancel an active download"""
    try:
        print(f"Cancellation request received for: {download_id}")
        
        if download_id in active_downloads:
            # Get the file info if available
            download_info = active_downloads[download_id]
            
            # Clean up temp directory
            temp_dir = os.path.join(DOWNLOAD_FOLDER, f"temp_{download_id}")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                print(f"Removed temp directory: {temp_dir}")
            
            # If the download was completed, check for the file
            if isinstance(download_info, dict) and download_info.get('status') == 'complete':
                filename = download_info.get('filename')
                if filename:
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Removed downloaded file: {file_path}")
            
            # Remove from active downloads
            del active_downloads[download_id]
            print(f"Removed from active downloads")
            
            # Notify client that download was cancelled
            if not IS_VERCEL:
                socketio.emit('cancelled', {}, room=download_id)
            
            return jsonify({'success': True})
        else:
            print(f"Download ID not found in active_downloads")
            return jsonify({'success': False, 'error': 'Download not found'})
            
    except Exception as e:
        print(f"Exception in cancel_download: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_status/<download_id>')
def check_status(download_id):
    """Check the status of a download"""
    try:
        if download_id in active_downloads:
            download_info = active_downloads[download_id]
            
            if isinstance(download_info, dict):
                status = download_info.get('status')
                
                if status == 'complete':
                    filename = download_info.get('filename')
                    if filename:
                        try:
                            with app.app_context():
                                download_url = url_for('download_file', filename=filename, _external=True)
                        except Exception:
                            download_url = f"/download/{filename}"
                            
                        # Get file info
                        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                        
                        # Determine file type
                        import mimetypes
                        file_type, _ = mimetypes.guess_type(file_path)
                        if not file_type:
                            file_type = 'application/octet-stream'
                            
                        file_info = {
                            'name': filename,
                            'size': file_size,
                            'type': file_type
                        }
                        
                        return jsonify({
                            'status': 'complete',
                            'download_url': download_url,
                            'file_info': file_info
                        })
                elif status == 'error':
                    return jsonify({
                        'status': 'error',
                        'error': download_info.get('error', 'An unknown error occurred')
                    })
                else:
                    return jsonify({'status': status})
            else:
                return jsonify({'status': 'unknown'})
        else:
            return jsonify({'status': 'not_found'})
    except Exception as e:
        print(f"Error checking status: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)})

@app.route('/check_download_status/<download_id>')
def check_download_status(download_id):
    """API to check current download status"""
    try:
        print(f"Checking status for download ID: {download_id}")
        
        # Check if download ID exists in our tracking dictionary
        if download_id in active_downloads:
            download_info = active_downloads[download_id]
            print(f"Found download in active_downloads: {download_info}")
            
            # Handle dictionary format
            if isinstance(download_info, dict):
                status = download_info.get('status', 'unknown')
                
                if status == 'complete' and 'filename' in download_info:
                    # Get download URL
                    try:
                        download_url = url_for('download_file', filename=download_info['filename'], _external=True)
                    except Exception:
                        download_url = f"/download/{download_info['filename']}"
                        
                    return jsonify({
                        'status': 'complete',
                        'download_url': download_url,
                        'filename': download_info['filename']
                    })
                elif status == 'error':
                    return jsonify({
                        'status': 'error',
                        'message': download_info.get('error', 'Unknown error')
                    })
                else:
                    return jsonify({'status': status})
            
            # Handle string format (old format - might be a filename)
            elif download_info:
                # Assume it's a filename
                try:
                    download_url = url_for('download_file', filename=download_info, _external=True)
                except Exception:
                    download_url = f"/download/{download_info}"
                    
                return jsonify({
                    'status': 'complete',
                    'download_url': download_url,
                    'filename': download_info
                })
            else:
                return jsonify({'status': 'downloading'})
        
        # If not in active downloads, check if there's a matching file
        print(f"Download ID not in active_downloads, checking for files")
        for filename in os.listdir(DOWNLOAD_FOLDER):
            if download_id in filename:
                print(f"Found matching file: {filename}")
                try:
                    download_url = url_for('download_file', filename=filename, _external=True)
                except Exception:
                    download_url = f"/download/{filename}"
                    
                return jsonify({
                    'status': 'complete',
                    'download_url': download_url,
                    'filename': filename
                })
        
        print(f"No status found for download ID: {download_id}")
        return jsonify({'status': 'unknown'})
        
    except Exception as e:
        print(f"Error in check_download_status: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/cleanup_temp_files/<download_id>', methods=['POST'])
def cleanup_temp_files(download_id):
    """Clean up temporary files when user navigates away"""
    try:
        print(f"Cleaning up temp files for download ID: {download_id}")
        
        # Check if there are temp directories to clean
        temp_dir = os.path.join(DOWNLOAD_FOLDER, f"temp_{download_id}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"Removed temp directory: {temp_dir}")
        
        # Remove completed download files if they haven't been saved
        if download_id in active_downloads:
            download_info = active_downloads[download_id]
            
            # If it was a completed download, remove the file
            if isinstance(download_info, dict) and download_info.get('status') == 'complete':
                filename = download_info.get('filename')
                if filename:
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Removed downloaded file: {file_path}")
            
            # Remove from active downloads
            del active_downloads[download_id]
            print(f"Removed download from tracking")
        
        return jsonify({'success': True, 'message': 'Cleanup completed'})
        
    except Exception as e:
        print(f"Error in cleanup_temp_files: {e}")
        return jsonify({'success': False, 'error': str(e)})

# For Vercel: Create API endpoint instead of using Socket.IO
@app.route('/api/fetch_video_info', methods=['POST'])
def api_fetch_video_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"error": "Please provide a valid YouTube URL"}), 400
    
    try:
        # Configure yt-dlp options
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'format': 'best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Check if it's a playlist and get the first video
            if 'entries' in info:
                info = info['entries'][0]
            
            # Create a simplified video info object
            video_info = {
                'id': info.get('id'),
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'view_count': info.get('view_count'),
                'formats': info.get('formats', [])
            }
            
            return jsonify({"info": video_info})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download_progress/<download_id>', methods=['GET'])
def api_download_progress(download_id):
    # Create simplified polling endpoint
    # Check progress file in /tmp
    progress_file = os.path.join(DOWNLOAD_FOLDER, f"{download_id}_progress.json")
    if os.path.exists(progress_file):
        with open(progress_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({"status": "waiting", "progress": 0})

# Add these endpoints for Vercel environment
@app.route('/api/check_download_status/<download_id>')
def api_check_download_status(download_id):
    """API to check current download status when SocketIO isn't available"""
    try:
        # Check if download ID exists in our tracking dictionary
        if download_id in active_downloads:
            download_info = active_downloads[download_id]
            return jsonify(download_info)
        
        # If not in active downloads, check if there's a matching file
        for filename in os.listdir(DOWNLOAD_FOLDER):
            if download_id in filename:
                file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                if os.path.exists(file_path):
                    return jsonify({
                        'status': 'complete',
                        'filename': filename,
                        'filepath': file_path
                    })
        
        return jsonify({'status': 'unknown'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# Only run socketio if not on Vercel
if __name__ == '__main__' and not IS_VERCEL:
    socketio.run(app, debug=True)
