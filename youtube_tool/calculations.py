import math
import re
from datetime import date, timedelta


_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
STANDARD_SPEEDS = (1.25, 1.5, 1.75, 2.0)


def parse_iso_duration(value: str) -> int:
    match = _DURATION_PATTERN.fullmatch(value)
    if (
        not match
        or not any(match.groupdict().values())
        or ("T" in value and not any(
            match.group(name) for name in ("hours", "minutes", "seconds")
        ))
    ):
        raise ValueError("Invalid ISO 8601 video duration.")
    parts = {name: int(component or 0) for name, component in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def format_duration(seconds: int) -> str:
    if seconds < 0:
        raise ValueError("Duration cannot be negative.")
    if seconds == 0:
        return "0 seconds"
    units = (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1))
    remaining = seconds
    formatted = []
    for label, unit_seconds in units:
        amount, remaining = divmod(remaining, unit_seconds)
        if amount:
            formatted.append(f"{amount} {label}{'' if amount == 1 else 's'}")
    return ", ".join(formatted)


def playback_times(total_seconds: int, custom_speed: float | None = None) -> list[dict]:
    speeds = list(STANDARD_SPEEDS)
    if custom_speed is not None and custom_speed not in speeds:
        speeds.append(custom_speed)
    return [
        {
            "speed": speed,
            "seconds": math.floor(total_seconds / speed + 0.5),
            "duration": format_duration(math.floor(total_seconds / speed + 0.5)),
        }
        for speed in speeds
    ]


def progress_for_videos(videos: list[dict], watched_count: int) -> dict:
    if watched_count < 0 or watched_count > len(videos):
        raise ValueError(f"Videos watched must be between 0 and {len(videos)}.")
    known_durations = [
        video["duration_seconds"]
        if video.get("duration_seconds") is not None
        else 0
        for video in videos
    ]
    total = sum(known_durations)
    watched = sum(known_durations[:watched_count])
    remaining = total - watched
    percent = round(watched * 100 / total) if total else 0
    return {
        "watched_count": watched_count,
        "video_count": len(videos),
        "watched_seconds": watched,
        "remaining_seconds": remaining,
        "total_seconds": total,
        "percent": percent,
        "unavailable_watched_count": sum(
            1 for video in videos[:watched_count] if video.get("duration_seconds") is None
        ),
        "unavailable_remaining_count": sum(
            1 for video in videos[watched_count:] if video.get("duration_seconds") is None
        ),
    }


def estimate_finish_date(
    remaining_seconds: int,
    daily_seconds: int,
    watching_weekdays: set[int],
    start_date: date,
    include_today: bool = True,
) -> date | None:
    if remaining_seconds < 0:
        raise ValueError("Remaining time cannot be negative.")
    if daily_seconds < 0:
        raise ValueError("Daily watch time cannot be negative.")
    if any(day < 0 or day > 6 for day in watching_weekdays):
        raise ValueError("Watching weekdays must be between 0 and 6.")
    if remaining_seconds == 0:
        return start_date
    if daily_seconds == 0 or not watching_weekdays:
        return None

    viewing_days_required = (remaining_seconds + daily_seconds - 1) // daily_seconds
    day_offset = 0 if include_today else 1
    try:
        first_date = start_date + timedelta(days=day_offset)
        for _ in range(7):
            if first_date.weekday() in watching_weekdays:
                break
            first_date += timedelta(days=1)
        if viewing_days_required == 1:
            return first_date

        selected_weekdays = sorted(watching_weekdays)
        current_weekday_index = selected_weekdays.index(first_date.weekday())
        additional_days = viewing_days_required - 1
        full_weeks, extra_days = divmod(additional_days, len(selected_weekdays))
        day_offset_from_first = full_weeks * 7
        for _ in range(extra_days):
            current_weekday = selected_weekdays[current_weekday_index]
            current_weekday_index = (current_weekday_index + 1) % len(selected_weekdays)
            next_weekday = selected_weekdays[current_weekday_index]
            step = (next_weekday - current_weekday) % 7 or 7
            day_offset_from_first += step
        return first_date + timedelta(days=day_offset_from_first)
    except OverflowError:
        return None
