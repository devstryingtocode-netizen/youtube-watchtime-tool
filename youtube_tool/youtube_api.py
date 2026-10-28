import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from youtube_tool.calculations import parse_iso_duration


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_PLAYLIST_ITEMS = 500
PAGE_SIZE = 50


class YouTubeApiError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _api_error_message(payload: Any, status_code: int) -> str:
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    errors = error.get("errors", []) if isinstance(error, dict) else []
    reason = errors[0].get("reason") if errors and isinstance(errors[0], dict) else ""
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    lowered = f"{reason} {message}".lower()
    if "quota" in lowered or "dailylimitexceeded" in lowered:
        return "YouTube API quota has been exceeded. Try again later or use your own API key."
    if (
        "keyinvalid" in lowered
        or "keyexpired" in lowered
        or "api key not valid" in lowered
        or "invalid api key" in lowered
    ):
        return "The YouTube API key is invalid. Check the key and its API restrictions."
    if "iprefererblocked" in lowered or "accessnotconfigured" in lowered:
        return "The API key cannot access YouTube Data API v3. Check its API and application restrictions."
    if status_code == 429:
        return "YouTube is temporarily rate-limiting requests. Try again shortly."
    return "YouTube could not complete the request. Check the video or playlist and try again."


class YouTubeApi:
    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=self.transport,
        )
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, resource: str, **params) -> dict:
        if self._client is None:
            raise RuntimeError("YouTubeApi must be used inside an async context.")
        try:
            response = await self._client.get(
                f"{YOUTUBE_API_BASE}/{resource}",
                params={**params, "key": self.api_key},
            )
        except httpx.TimeoutException as exc:
            raise YouTubeApiError("YouTube did not respond in time. Try again.") from exc
        except httpx.RequestError as exc:
            raise YouTubeApiError("Could not connect to YouTube. Check your connection.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeApiError("YouTube returned an unreadable response.") from exc
        if response.is_error:
            raise YouTubeApiError(
                _api_error_message(payload, response.status_code),
                response.status_code,
            )
        if not isinstance(payload, dict):
            raise YouTubeApiError("YouTube returned an unexpected response.")
        return payload

    async def get_playlist_metadata(self, playlist_ids: list[str]) -> dict[str, dict]:
        if not playlist_ids:
            return {}
        payload = await self._get(
            "playlists",
            part="snippet",
            id=",".join(playlist_ids),
            maxResults=min(len(playlist_ids), 50),
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise YouTubeApiError("YouTube returned malformed playlist metadata.")
        results = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise YouTubeApiError("YouTube returned malformed playlist metadata.")
            if not isinstance(item.get("snippet"), dict):
                raise YouTubeApiError("YouTube returned incomplete playlist metadata.")
            results[item["id"]] = item
        return results

    async def get_playlist_items(self, playlist_id: str) -> tuple[list[dict], bool]:
        items: list[dict] = []
        seen_item_ids: set[str] = set()
        page_token = None
        seen_tokens: set[str] = set()
        while len(items) < MAX_PLAYLIST_ITEMS:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": min(PAGE_SIZE, MAX_PLAYLIST_ITEMS - len(items)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get("playlistItems", **params)
            page_items = payload.get("items")
            if not isinstance(page_items, list):
                raise YouTubeApiError("YouTube returned malformed playlist items.")
            for item in page_items:
                if not isinstance(item, dict):
                    raise YouTubeApiError("YouTube returned malformed playlist items.")
                playlist_item_id = item.get("id")
                if not isinstance(playlist_item_id, str):
                    raise YouTubeApiError("YouTube returned a playlist item without an ID.")
                if playlist_item_id in seen_item_ids:
                    continue
                seen_item_ids.add(playlist_item_id)
                content = item.get("contentDetails")
                snippet = item.get("snippet")
                video_id = content.get("videoId") if isinstance(content, dict) else None
                title = snippet.get("title") if isinstance(snippet, dict) else None
                items.append({
                    "video_id": video_id if isinstance(video_id, str) else None,
                    "title": title if isinstance(title, str) and title else None,
                })
                if len(items) == MAX_PLAYLIST_ITEMS:
                    break

            next_token = payload.get("nextPageToken")
            if next_token is None:
                return items, False
            if not isinstance(next_token, str) or not next_token:
                raise YouTubeApiError("YouTube returned an invalid playlist page token.")
            if next_token in seen_tokens:
                raise YouTubeApiError("YouTube returned a repeated playlist page.")
            seen_tokens.add(next_token)
            page_token = next_token
        return items, bool(page_token)

    async def get_video_metadata(self, video_ids: list[str]) -> dict[str, dict]:
        if not video_ids:
            return {}
        payload = await self._get(
            "videos",
            part="snippet,contentDetails",
            id=",".join(video_ids),
            maxResults=min(len(video_ids), 50),
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise YouTubeApiError("YouTube returned malformed video metadata.")
        results = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise YouTubeApiError("YouTube returned malformed video metadata.")
            snippet = item.get("snippet")
            content = item.get("contentDetails")
            if not isinstance(snippet, dict) or not isinstance(content, dict):
                raise YouTubeApiError("YouTube returned incomplete video metadata.")
            duration = content.get("duration")
            title = snippet.get("title")
            creator = snippet.get("channelTitle")
            if not isinstance(duration, str) or not isinstance(title, str):
                raise YouTubeApiError("YouTube returned incomplete video metadata.")
            try:
                duration_seconds = parse_iso_duration(duration)
            except ValueError as exc:
                raise YouTubeApiError("YouTube returned an invalid video duration.") from exc
            thumbnails = snippet.get("thumbnails")
            thumbnail_url = None
            if isinstance(thumbnails, dict):
                for size in ("high", "medium", "default"):
                    image = thumbnails.get(size)
                    if isinstance(image, dict) and isinstance(image.get("url"), str):
                        thumbnail_url = image["url"]
                        break
            results[item["id"]] = {
                "video_id": item["id"],
                "title": title,
                "creator": creator if isinstance(creator, str) else None,
                "duration_seconds": duration_seconds,
                "thumbnail_url": thumbnail_url,
                "accessible": True,
            }
        return results


async def gather_playlist_items(
    playlist_ids: list[str],
    fetch_items: Callable[[str], Awaitable[tuple[list[dict], bool]]],
) -> dict[str, tuple[list[dict] | None, bool, str | None]]:
    semaphore = asyncio.Semaphore(3)

    async def fetch_one(playlist_id: str):
        async with semaphore:
            try:
                items, limited = await fetch_items(playlist_id)
                return playlist_id, (items, limited, None)
            except YouTubeApiError as exc:
                return playlist_id, (None, False, str(exc))

    results = await asyncio.gather(*(fetch_one(playlist_id) for playlist_id in playlist_ids))
    return dict(results)
