import re
from urllib.parse import parse_qs, urlsplit


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def parse_youtube_input(value: str) -> dict:
    item = value.strip()
    if not item:
        raise ValueError("Enter a YouTube video or playlist link.")

    if VIDEO_ID_PATTERN.fullmatch(item):
        return {"kind": "video", "id": item}
    if PLAYLIST_ID_PATTERN.fullmatch(item):
        return {"kind": "playlist", "id": item}

    candidate = item if "://" in item else f"https://{item}"
    try:
        parsed = urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Enter a valid YouTube URL or ID.") from exc

    is_youtube_host = host == "youtube.com" or host.endswith(".youtube.com")
    is_short_host = host == "youtu.be" or host.endswith(".youtu.be")
    if not (is_youtube_host or is_short_host):
        raise ValueError("Only YouTube video and playlist links are supported.")

    query = parse_qs(parsed.query)
    playlist_id = query.get("list", [None])[0]
    if playlist_id is not None:
        if not PLAYLIST_ID_PATTERN.fullmatch(playlist_id):
            raise ValueError("The playlist ID in this URL is invalid.")
        return {"kind": "playlist", "id": playlist_id}

    video_id = None
    if is_short_host:
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) == 1:
            video_id = path_parts[0]
    elif parsed.path.rstrip("/") == "/watch":
        video_id = query.get("v", [None])[0]
    else:
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) == 2 and path_parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = path_parts[1]

    if video_id and VIDEO_ID_PATTERN.fullmatch(video_id):
        return {"kind": "video", "id": video_id}
    if parsed.path.rstrip("/") == "/playlist":
        raise ValueError("This playlist URL is missing a valid playlist ID.")
    raise ValueError("This YouTube URL does not contain a supported video or playlist ID.")
