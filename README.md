# YouTube Playlist Length Calculator

A simple tool for checking the total duration of a YouTube playlist and figuring out how long it would take to watch at different playback speeds.

## Features

- Calculate the total duration of a YouTube playlist
- View playlist video information
- Calculate watch time at different playback speeds
- Track viewing progress and estimate remaining time
- Plan viewing sessions
- Download available video thumbnails
- Generate YouTube links with timestamps
- Responsive dark-themed interface

## Tech Stack

- Python
- FastAPI
- HTML, CSS, and JavaScript
- YouTube Data API v3

## Running Locally

**1. Clone the repository**

```bash
git clone YOUR_REPOSITORY_URL
cd YOUR_PROJECT_FOLDER
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Set up your API key**

Create a `.env` file in the project root:

```env
YOUTUBE_API_KEY=your_api_key_here
```

You need a YouTube Data API v3 key from the Google Cloud Console.

Keep your actual API key private. Do not commit your `.env` file to GitHub.

**4. Start the server**

```bash
uvicorn app:app --reload
```

Open the local URL shown in your terminal, usually `http://127.0.0.1:8000`.

The command assumes your FastAPI application is defined as `app` in `app.py`. Adjust it if your project uses a different entry point.

## Deployment

The application is deployed here:

**Live demo:** YOUR_DEPLOYED_WEBSITE_URL

## Notes

Playlist analysis depends on the YouTube Data API and its quota limits. Some videos or playlist details may be unavailable depending on their privacy settings and API access.

## License

Add a license if you intend to allow others to reuse or modify this project.
