import httpx

from youtube_tool.calculations import (
    format_duration,
    playback_times,
    progress_for_videos,
)
from youtube_tool.inputs import parse_youtube_input
from youtube_tool.youtube_api import YouTubeApi, YouTubeApiError, gather_playlist_items


MAX_INPUTS = 5


def _unavailable(video_id: str | None, title: str | None = None) -> dict:
    return {
        "video_id": video_id,
        "title": title or "Unavailable video",
        "duration_seconds": None,
        "thumbnail_url": None,
        "accessible": False,
    }


def _range_bounds(
    item_count: int,
    range_start: int | None,
    range_end: int | None,
) -> tuple[int, int]:
    start = 1 if range_start is None else range_start
    end = min(item_count if range_end is None else range_end, item_count)
    if start < 1 or end < 1 or start > item_count:
        raise ValueError(f"Range start must be between 1 and {item_count}.")
    if start > end:
        raise ValueError("Range start cannot be greater than range end.")
    return start, end


async def analyze_inputs(
    input_text: str,
    *,
    api_key: str,
    range_start: int | None = None,
    range_end: int | None = None,
    custom_speed: float | None = None,
    watched_count: int = 0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict]:
    raw_inputs = [line.strip() for line in input_text.splitlines() if line.strip()]
    if not raw_inputs:
        raise ValueError("Enter at least one YouTube video or playlist link.")
    if len(raw_inputs) > MAX_INPUTS:
        raise ValueError(f"Analyze up to {MAX_INPUTS} links at a time.")
    if range_start is not None and not 1 <= range_start <= 500:
        raise ValueError("Range start must be between 1 and 500.")
    if range_end is not None and not 1 <= range_end <= 500:
        raise ValueError("Range end must be between 1 and 500.")
    if range_start is not None and range_end is not None and range_start > range_end:
        raise ValueError("Range start cannot be greater than range end.")
    if not 0 <= watched_count <= 500:
        raise ValueError("Videos watched must be between 0 and 500.")
    if custom_speed is not None and not 0.1 <= custom_speed <= 10:
        raise ValueError("Custom speed must be between 0.1x and 10x.")

    parsed = []
    for raw in raw_inputs:
        try:
            parsed.append({"raw": raw, **parse_youtube_input(raw)})
        except ValueError as exc:
            parsed.append({"raw": raw, "error": str(exc)})

    playlist_ids = list(dict.fromkeys(
        item["id"] for item in parsed
        if item.get("kind") == "playlist"
    ))
    video_ids = list(dict.fromkeys(
        item["id"] for item in parsed
        if item.get("kind") == "video"
    ))

    async with YouTubeApi(api_key, transport=transport) as youtube:
        playlist_metadata = await youtube.get_playlist_metadata(playlist_ids)
        playlist_requests = [
            playlist_id for playlist_id in playlist_ids if playlist_id in playlist_metadata
        ]
        playlist_items = await gather_playlist_items(
            playlist_requests,
            youtube.get_playlist_items,
        )

        all_video_ids = list(video_ids)
        for items, _limited, error in playlist_items.values():
            if items is not None and error is None:
                all_video_ids.extend(
                    item["video_id"] for item in items if item["video_id"]
                )
        all_video_ids = list(dict.fromkeys(all_video_ids))

        video_metadata: dict[str, dict] = {}
        for index in range(0, len(all_video_ids), 50):
            video_metadata.update(
                await youtube.get_video_metadata(all_video_ids[index : index + 50])
            )

    results = []
    for item in parsed:
        if item.get("error"):
            results.append({
                "input": item["raw"],
                "error": item["error"],
            })
            continue

        if item["kind"] == "playlist":
            playlist_id = item["id"]
            metadata = playlist_metadata.get(playlist_id)
            if metadata is None:
                results.append({
                    "input": item["raw"],
                    "error": "Playlist not found or unavailable. Check that the playlist is public or unlisted and the ID is correct.",
                })
                continue
            playlist_snippet = metadata.get("snippet")
            if not isinstance(playlist_snippet, dict):
                results.append({"input": item["raw"], "error": "YouTube returned incomplete playlist metadata."})
                continue
            playlist_name = playlist_snippet.get("title")
            channel_title = playlist_snippet.get("channelTitle")
            items, limited, fetch_error = playlist_items.get(playlist_id, (None, False, None))
            if fetch_error:
                results.append({"input": item["raw"], "error": fetch_error})
                continue
            if items is None:
                results.append({"input": item["raw"], "error": "Playlist items could not be retrieved."})
                continue
            if not items:
                if range_start is not None or range_end is not None:
                    results.append({
                        "input": item["raw"],
                        "error": "This playlist is empty, so the requested range has no items.",
                    })
                    continue
                results.append(_build_result(
                    item,
                    [],
                    custom_speed,
                    watched_count,
                    name=playlist_name or "Untitled playlist",
                    creator=channel_title,
                    playlist_id=playlist_id,
                    limited=limited,
                ))
                continue
            try:
                start, end = _range_bounds(len(items), range_start, range_end)
            except ValueError as exc:
                results.append({"input": item["raw"], "error": str(exc)})
                continue
            selected = items[start - 1 : end]
            videos = [
                video_metadata.get(entry["video_id"], _unavailable(entry["video_id"], entry["title"]))
                if entry["video_id"]
                else _unavailable(None, entry["title"])
                for entry in selected
            ]
            result = _build_result(
                item,
                videos,
                custom_speed,
                watched_count,
                name=playlist_name or "Untitled playlist",
                creator=channel_title,
                playlist_id=playlist_id,
                range_start=start,
                range_end=end,
                limited=limited,
            )
            results.append(result)
            continue

        video = video_metadata.get(item["id"])
        if video is None:
            results.append({
                "input": item["raw"],
                "error": "Video not found or unavailable. It may be private, deleted, or inaccessible.",
            })
            continue
        result = _build_result(
            item,
            [video],
            custom_speed,
            watched_count,
            name=video["title"],
            creator=video.get("creator"),
        )
        results.append(result)
    return results


def _build_result(
    item: dict,
    videos: list[dict],
    custom_speed: float | None,
    watched_count: int,
    *,
    name: str,
    creator: str | None = None,
    playlist_id: str | None = None,
    range_start: int | None = None,
    range_end: int | None = None,
    limited: bool = False,
) -> dict:
    try:
        progress = progress_for_videos(videos, watched_count)
    except ValueError as exc:
        return {"input": item["raw"], "error": str(exc)}
    total_seconds = progress["total_seconds"]
    accessible_count = sum(1 for video in videos if video["accessible"])
    result = {
        "input": item["raw"],
        "kind": item["kind"],
        "title": name,
        "creator": creator,
        "playlist_id": playlist_id,
        "video_id": item["id"] if item["kind"] == "video" else None,
        "video_count": len(videos),
        "accessible_video_count": accessible_count,
        "unavailable_video_count": len(videos) - accessible_count,
        "videos": videos,
        "total_seconds": total_seconds,
        "total_duration": format_duration(total_seconds),
        "playback_times": playback_times(total_seconds, custom_speed),
        "progress": progress,
        "range": (
            {"start": range_start, "end": range_end}
            if item["kind"] == "playlist"
            else None
        ),
        "limited_to_500_items": limited,
        "warning": (
            "Unavailable playlist items are included in the item range but excluded from duration totals."
            if len(videos) != accessible_count
            else None
        ),
    }
    return result
