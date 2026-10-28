from youtube_tool.inputs import parse_youtube_input


THUMBNAIL_VARIANTS = (
    {"key": "maxresdefault", "label": "Maximum resolution", "resolution": "1280 × 720"},
    {"key": "sddefault", "label": "Standard definition", "resolution": "640 × 480"},
    {"key": "hqdefault", "label": "High quality", "resolution": "480 × 360"},
    {"key": "mqdefault", "label": "Medium quality", "resolution": "320 × 180"},
    {"key": "default", "label": "Default", "resolution": "120 × 90"},
)


def thumbnail_variants(value: str) -> dict:
    parsed = parse_youtube_input(value)
    if parsed["kind"] != "video":
        raise ValueError("Enter a YouTube video URL or 11-character video ID.")
    video_id = parsed["id"]
    return {
        "video_id": video_id,
        "variants": [
            {
                **variant,
                "url": f"https://img.youtube.com/vi/{video_id}/{variant['key']}.jpg",
            }
            for variant in THUMBNAIL_VARIANTS
        ],
    }
