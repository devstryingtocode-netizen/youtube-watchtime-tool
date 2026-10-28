# YouTube Playlist Length

A responsive playlist analyzer inspired by [YouTube Playlist Length](https://ytplaylist-len.sharats.dev/). The app uses FastAPI, Jinja2, hand-authored responsive CSS, and vanilla JavaScript.

## Requirements

- Python 3.10+
- A YouTube Data API v3 key to analyze real playlists and videos

## Install and configure

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
```

Create an API key in the [Google Cloud Console](https://console.cloud.google.com/), enable **YouTube Data API v3** for the project, and replace `your_api_key_here` with your key in `.env`. Restrict the key to the YouTube Data API v3 and to the appropriate server application where possible. `.env` is ignored by Git; do not commit it.

Multiple server keys can optionally be configured with a semicolon-delimited `YOUTUBE_API_KEYS` value. The app selects a configured key per analysis request. If no server key is configured, a user can enter a key in the optional form field; it is sent to the server only for that request and is not logged or persisted. Configured server keys take precedence over a submitted key.

The web pages still start without a configured key, but analysis requests receive a clear configuration error. On startup the app logs a warning if no server key is configured.

## Run

```bash
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Tests

Run the offline test suite (external YouTube API responses are mocked):

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Features

- `POST /api/analyze` parses up to five YouTube links or IDs, loads playlist metadata and up to 500 ordered playlist items, retrieves video durations in batches, and returns per-input results.
- Supports watch, playlist, `youtu.be`, Shorts, embed and live URLs; playlist item ranges are one-based and inclusive.
- Shows actual total duration, standard and custom-speed estimates, unavailable item counts, and watched/remaining progress.
- `POST /api/schedule` estimates the finish date from remaining watch time, speed, daily limit, selected weekdays, and the include-today setting. Schedule input changes recalculate the estimate.
- `/thumbnails` checks YouTube's public thumbnail variants in the browser, previews those that exist, and offers open/download actions.
- `/timestamp` validates a video and timestamp (seconds, `MM:SS`, or `HH:MM:SS`), generates a share link, and supports copy/open actions.
- `/robots.txt`, `/sitemap.xml`, and `/healthz` provide basic crawl and deployment endpoints. Page titles, descriptions, canonical URLs, and Open Graph metadata are set per route.
- Theme preference is saved in browser local storage.
- No Tailwind CDN, Redis, or response cache is used.

Routes:

- `/` — playlist length and watch schedule
- `/thumbnails` — thumbnail downloader
- `/timestamp` — timestamp link generator

The YouTube API key is sent in the API request query as required by Google's API. This app does not cache API responses or store user-provided keys. The UI does not display stack traces or the API key. Real API tests require a valid configured key and consume quota; the included tests use mocked responses and do not require credentials.

### Configure and restart in VS Code

Open the project folder in VS Code, then open **Terminal → New Terminal** and run:

```bash
cp .env.example .env
```

Open `.env`, replace `your_api_key_here` with your Google Cloud API key, and save it. In the terminal, start or restart the app:

```bash
uvicorn app:app --reload
```

If the server is already running without `--reload`, stop it with `Ctrl+C` and run the command again so the process loads `.env`. `cp -n` leaves an existing `.env` intact; edit that file directly when rotating keys. Then visit `http://127.0.0.1:8000`, paste a public or unlisted playlist URL, and click **Analyze Playlist**. For production, set `YOUTUBE_API_KEY` and `BASE_URL` in the hosting provider's environment settings. The `.env` file is only for local development.

## Deploy to Render

The included `render.yaml` defines a Render web service, production Uvicorn command, health check, public base URL and a secret `YOUTUBE_API_KEY` setting.

1. Push the repository to your GitHub account (instructions below).
2. In Render, choose **New → Blueprint**, connect the GitHub repository, and approve the `youtube-watchtime-tool` service from `render.yaml`.
3. Enter `YOUTUBE_API_KEY` in Render's environment prompt. Do not put the value in `render.yaml` or GitHub.
4. Deploy and wait for the `/healthz` check to pass. Open the Render service URL and test with a public playlist.
5. If you use a custom domain, update `BASE_URL` in Render to that HTTPS origin and redeploy.

The repository includes a GitHub Actions workflow that runs the mocked test suite on pushes and pull requests. No deployment has been performed from this workspace.

## Push to GitHub

From the project terminal, review the changes and ensure `.env` is not staged:

```bash
git status --short
git check-ignore -v .env
git add README.md .env.example .gitignore requirements.txt requirements-dev.txt render.yaml .github app.py static templates tests youtube_tool
git status --short
git commit -m "Complete playlist tools and deployment setup" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

Never use `git add .` for this project while `.env` is present. If your working branch is not `main`, push that branch name instead.

## Limitations

Only English is implemented; the upstream site's 27-language routing is not replicated. Thumbnail variants are checked by image loading in the browser; direct download can fall back to opening the image if the browser blocks cross-origin fetches. Browser locale is used for dates and formatting. Live YouTube API calls depend on the configured key and quota.
