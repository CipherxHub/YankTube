# YankTube - YouTube Video Downloader

A modern web application for downloading YouTube videos with a clean, responsive interface.

## Features

- Download YouTube videos in various formats
- Real-time download progress tracking
- Dark/Light theme support
- Responsive design
- Socket.IO for real-time updates

## Deployment on Vercel

1. Fork this repository to your GitHub account
2. Create a new project on [Vercel](https://vercel.com)
3. Connect your GitHub repository to Vercel
4. Deploy with the following settings:
   - Framework Preset: Other
   - Build Command: None
   - Output Directory: None
   - Install Command: `pip install -r requirements.txt`

## Environment Variables

Add the following environment variables in your Vercel project settings:

- `FLASK_APP`: app.py
- `FLASK_ENV`: production

## Development

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run the development server: `python app.py`

## License

MIT

## Author

CipherxHub