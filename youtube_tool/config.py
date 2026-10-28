import itertools
import os
import re
from threading import Lock
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


_API_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,200}$")
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_key_cycle = itertools.count()
_key_lock = Lock()


class ConfigurationError(ValueError):
    pass


def configured_api_keys() -> list[str]:
    load_dotenv(ENV_FILE, override=False)
    file_values = dotenv_values(ENV_FILE)
    raw_keys = (
        os.getenv("YOUTUBE_API_KEYS")
        or file_values.get("YOUTUBE_API_KEYS")
        or os.getenv("YOUTUBE_API_KEY")
        or file_values.get("YOUTUBE_API_KEY")
        or os.getenv("APIS")
        or file_values.get("APIS", "")
    )
    keys = list(dict.fromkeys(key.strip() for key in raw_keys.split(";") if key.strip()))
    for key in keys:
        if not _API_KEY_PATTERN.fullmatch(key):
            raise ConfigurationError(
                "A configured YouTube API key has an invalid format. "
                "Check YOUTUBE_API_KEY or YOUTUBE_API_KEYS."
            )
    return keys


def validate_user_api_key(key: str | None) -> str | None:
    if key is None or not key.strip():
        return None
    normalized_key = key.strip()
    if not _API_KEY_PATTERN.fullmatch(normalized_key):
        raise ConfigurationError("The API key format is invalid.")
    return normalized_key


def select_api_key(user_key: str | None = None) -> str:
    keys = configured_api_keys()
    if keys:
        with _key_lock:
            index = next(_key_cycle)
        return keys[index % len(keys)]
    validated_user_key = validate_user_api_key(user_key)
    if validated_user_key:
        return validated_user_key
    raise ConfigurationError(
        "YouTube analysis is not configured. Set YOUTUBE_API_KEY on the server "
        "or enter your own key in the optional API key field."
    )
