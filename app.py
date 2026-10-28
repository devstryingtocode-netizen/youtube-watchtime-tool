import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import date
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from youtube_tool.calculations import estimate_finish_date
from youtube_tool.config import (
    ConfigurationError,
    configured_api_keys,
    select_api_key,
)
from youtube_tool.inputs import parse_youtube_input
from youtube_tool.service import analyze_inputs
from youtube_tool.thumbnails import thumbnail_variants
from youtube_tool.timestamp import timestamp_link
from youtube_tool.youtube_api import YouTubeApiError

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        if not configured_api_keys():
            raise ConfigurationError("No YouTube API key is configured.")
    except ConfigurationError:
        logging.getLogger(__name__).warning(
            "YouTube API key is not configured. The UI will load, but analysis "
            "requires YOUTUBE_API_KEY or a user-supplied key."
        )
    yield


app = FastAPI(title="YouTube Playlist Length", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


class AnalysisRequest(BaseModel):
    input_text: str = Field(min_length=1, max_length=2000)
    range_start: int | None = Field(default=None, ge=1, le=500)
    range_end: int | None = Field(default=None, ge=1, le=500)
    custom_speed: float | None = Field(default=None, ge=0.1, le=10)
    watched_count: int = Field(default=0, ge=0, le=500)
    api_key: str | None = Field(default=None, max_length=200)


class ScheduleRequest(BaseModel):
    remaining_seconds: int = Field(ge=0)
    daily_seconds: int = Field(ge=0, le=90000)
    watching_weekdays: list[int] = Field(max_length=7)
    speed: float = Field(gt=0.0, le=10)
    include_today: bool = True
    start_date: date | None = None


class ThumbnailRequest(BaseModel):
    video_input: str = Field(min_length=1, max_length=500)


class TimestampRequest(BaseModel):
    video_input: str = Field(min_length=1, max_length=500)
    timestamp: str = Field(min_length=1, max_length=20)


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "page": "home",
            "title": "Find the length of any YouTube playlist",
            "description": "Find YouTube playlist and video lengths, compare playback speeds, and plan a watch schedule.",
            "canonical_url": f"{BASE_URL}/",
        },
    )


@app.post("/api/analyze")
async def analyze(request_data: AnalysisRequest):
    try:
        input_lines = [
            line.strip() for line in request_data.input_text.splitlines() if line.strip()
        ]
        if not input_lines:
            raise ValueError("Enter at least one YouTube video or playlist link.")
        if len(input_lines) > 5:
            raise ValueError("Analyze up to 5 links at a time.")
        has_supported_input = False
        for line in input_lines:
            try:
                parse_youtube_input(line)
                has_supported_input = True
                break
            except ValueError:
                continue
        if not has_supported_input:
            return {
                "results": await analyze_inputs(
                    request_data.input_text,
                    api_key="",
                    range_start=request_data.range_start,
                    range_end=request_data.range_end,
                    custom_speed=request_data.custom_speed,
                    watched_count=request_data.watched_count,
                )
            }
        api_key = select_api_key(request_data.api_key)
        results = await analyze_inputs(
            request_data.input_text,
            api_key=api_key,
            range_start=request_data.range_start,
            range_end=request_data.range_end,
            custom_speed=request_data.custom_speed,
            watched_count=request_data.watched_count,
        )
        return {"results": results}
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except YouTubeApiError as exc:
        status_code = 503 if exc.status_code == 429 else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/schedule")
def schedule(request_data: ScheduleRequest):
    weekdays = set(request_data.watching_weekdays)
    if len(weekdays) != len(request_data.watching_weekdays):
        raise HTTPException(status_code=422, detail="Watching days must not contain duplicates.")
    if any(day < 0 or day > 6 for day in weekdays):
        raise HTTPException(status_code=422, detail="Watching days must be between 0 and 6.")
    remaining_at_speed = math.ceil(request_data.remaining_seconds / request_data.speed)
    finish = estimate_finish_date(
        remaining_at_speed,
        request_data.daily_seconds,
        weekdays,
        request_data.start_date or date.today(),
        request_data.include_today,
    )
    return {"finish_date": finish.isoformat() if finish else None}


@app.post("/api/thumbnail-variants")
def get_thumbnail_variants(request_data: ThumbnailRequest):
    try:
        return thumbnail_variants(request_data.video_input)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/timestamp")
def make_timestamp_link(request_data: TimestampRequest):
    try:
        return timestamp_link(request_data.video_input, request_data.timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/thumbnails")
def thumbnails(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="thumbnails.html",
        context={
            "page": "thumbnails",
            "title": "YouTube Thumbnail Downloader",
            "description": "Preview and download available thumbnail images for YouTube videos.",
            "canonical_url": f"{BASE_URL}/thumbnails",
        },
    )


@app.get("/timestamp")
def timestamp(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="timestamp.html",
        context={
            "page": "timestamp",
            "title": "YouTube Timestamp Link Generator",
            "description": "Create a shareable YouTube link that starts at a chosen timestamp.",
            "canonical_url": f"{BASE_URL}/timestamp",
        },
    )


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return Response(
        f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {BASE_URL}/sitemap.xml\n",
        media_type="text/plain",
    )


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    paths = ("/", "/thumbnails", "/timestamp")
    urls = "".join(
        f"<url><loc>{escape(BASE_URL + path)}</loc></url>"
        for path in paths
    )
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>",
        media_type="application/xml",
    )


@app.get("/healthz", include_in_schema=False)
def healthcheck():
    return {"status": "ok"}
