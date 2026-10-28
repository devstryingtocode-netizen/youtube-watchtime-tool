import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from youtube_tool.inputs import parse_youtube_input


_TIMESTAMP_PATTERN = re.compile(r"^\d+(?::\d{1,2}){0,2}$")
MAX_TIMESTAMP_HOURS = 999


def parse_timestamp(value: str) -> int:
    timestamp = value.strip()
    if not timestamp or not _TIMESTAMP_PATTERN.fullmatch(timestamp):
        raise ValueError("Enter a timestamp in seconds, MM:SS, or HH:MM:SS format.")
    parts = [int(part) for part in timestamp.split(":")]
    if len(parts) == 1:
        seconds = parts[0]
    elif len(parts) == 2:
        minutes, subsecond = parts
        if subsecond > 59:
            raise ValueError("Seconds in MM:SS must be between 0 and 59.")
        seconds = minutes * 60 + subsecond
    else:
        hours, minutes, subsecond = parts
        if hours > MAX_TIMESTAMP_HOURS:
            raise ValueError(f"Hours must not exceed {MAX_TIMESTAMP_HOURS}.")
        if minutes > 59 or subsecond > 59:
            raise ValueError("Minutes and seconds in HH:MM:SS must be between 0 and 59.")
        seconds = hours * 3600 + minutes * 60 + subsecond
    return seconds


def timestamp_link(video_input: str, timestamp: str) -> dict:
    parsed_input = parse_youtube_input(video_input)
    if parsed_input["kind"] != "video":
        raise ValueError("Enter a YouTube video URL or video ID.")
    seconds = parse_timestamp(timestamp)

    original = video_input.strip()
    candidate = original if "://" in original else f"https://{original}"
    parsed_url = urlsplit(candidate)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
        if key not in {"v", "t", "start"}
    ]
    query.extend((("v", parsed_input["id"]), ("t", str(seconds))))
    url = urlunsplit(
        ("https", "www.youtube.com", "/watch", urlencode(query), "")
    )
    return {"video_id": parsed_input["id"], "seconds": seconds, "url": url}
