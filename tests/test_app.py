import asyncio
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app
from youtube_tool.calculations import (
    estimate_finish_date,
    format_duration,
    parse_iso_duration,
    playback_times,
    progress_for_videos,
)
from youtube_tool.config import (
    ConfigurationError,
    ENV_FILE,
    configured_api_keys,
    select_api_key,
    validate_user_api_key,
)
from youtube_tool.inputs import parse_youtube_input
from youtube_tool.service import _range_bounds, analyze_inputs
from youtube_tool.thumbnails import thumbnail_variants
from youtube_tool.timestamp import parse_timestamp, timestamp_link
from youtube_tool.youtube_api import YouTubeApi, YouTubeApiError


client = TestClient(app)
FAKE_KEY = "AIzaSyC0piedfakekey_0123456789ab"
PLAYLIST_ID = "PLABCDEFGHIJKLMNO"
VIDEO_ONE = "abcdefghijk"
VIDEO_TWO = "LMNOPQRSTUV"
VIDEO_THREE = "xyZabcdef12"


def _video_response(video_id: str, title: str, duration: str) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "channelTitle": "Example channel",
            "thumbnails": {"high": {"url": f"https://example.test/{video_id}.jpg"}},
        },
        "contentDetails": {"duration": duration},
    }


def _mock_youtube_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path.endswith("/playlists"):
            return httpx.Response(200, json={
                "items": [{
                    "id": PLAYLIST_ID,
                    "snippet": {"title": "Mock playlist", "channelTitle": "Playlist author"},
                }]
            })
        if request.url.path.endswith("/playlistItems"):
            if params.get("pageToken") == "page-2":
                return httpx.Response(200, json={
                    "items": [
                        {
                            "id": "item-2",
                            "contentDetails": {"videoId": VIDEO_TWO},
                            "snippet": {"title": "Duplicate page boundary"},
                        },
                        {
                            "id": "item-3",
                            "contentDetails": {"videoId": VIDEO_THREE},
                            "snippet": {"title": "Third"},
                        },
                    ]
                })
            return httpx.Response(200, json={
                "items": [
                    {
                        "id": "item-1",
                        "contentDetails": {"videoId": VIDEO_ONE},
                        "snippet": {"title": "First"},
                    },
                    {
                        "id": "item-2",
                        "contentDetails": {"videoId": VIDEO_TWO},
                        "snippet": {"title": "Second"},
                    },
                ],
                "nextPageToken": "page-2",
            })
        if request.url.path.endswith("/videos"):
            return httpx.Response(200, json={
                "items": [
                    _video_response(VIDEO_ONE, "First video", "PT1H"),
                    _video_response(VIDEO_TWO, "Second video", "PT30M"),
                    _video_response(VIDEO_THREE, "Third video", "PT45S"),
                ]
            })
        return httpx.Response(404, json={"error": {"message": "unexpected endpoint"}})

    return httpx.MockTransport(handler)


def test_home_page_has_playlist_form_and_shared_navigation():
    response = client.get("/")

    assert response.status_code == 200
    assert "Find the length of any YouTube playlist" in response.text
    assert "Watch Schedule" in response.text
    assert "Analyze Playlist" in response.text
    assert 'href="/thumbnails"' in response.text
    assert 'href="/timestamp"' in response.text
    assert 'id="analysis-form"' in response.text


def test_additional_tool_shells_load():
    thumbnail_response = client.get("/thumbnails")
    timestamp_response = client.get("/timestamp")

    assert thumbnail_response.status_code == 200
    assert "Download thumbnails for any YouTube video" in thumbnail_response.text
    assert timestamp_response.status_code == 200
    assert "Generate a YouTube timestamp link" in timestamp_response.text


def test_seo_navigation_robots_sitemap_and_health_routes():
    home = client.get("/")
    thumbnails = client.get("/thumbnails")
    timestamp = client.get("/timestamp")
    robots = client.get("/robots.txt")
    sitemap_response = client.get("/sitemap.xml")
    health = client.get("/healthz")

    assert 'rel="canonical" href="http://localhost:8000/"' in home.text
    assert 'aria-current="page">Playlist Length</a>' in home.text
    assert 'aria-current="page">Thumbnail Downloader</a>' in thumbnails.text
    assert 'aria-current="page">Timestamp Generator</a>' in timestamp.text
    assert "Disallow: /api/" in robots.text
    assert "<loc>http://localhost:8000/timestamp</loc>" in sitemap_response.text
    assert health.json() == {"status": "ok"}


def test_static_assets_are_served():
    stylesheet = client.get("/static/css/styles.css")
    script = client.get("/static/js/site.js")

    assert stylesheet.status_code == 200
    assert "--page: #09090d" in stylesheet.text
    assert script.status_code == 200
    assert "/api/analyze" in script.text


def test_supported_youtube_url_and_id_parsing():
    assert parse_youtube_input(
        "https://www.youtube.com/watch?v=abcdefghijk"
    ) == {"kind": "video", "id": VIDEO_ONE}
    assert parse_youtube_input("youtu.be/abcdefghijk") == {
        "kind": "video",
        "id": VIDEO_ONE,
    }
    assert parse_youtube_input("youtube.com/shorts/abcdefghijk") == {
        "kind": "video",
        "id": VIDEO_ONE,
    }
    assert parse_youtube_input(
        f"https://youtube.com/playlist?list={PLAYLIST_ID}"
    ) == {"kind": "playlist", "id": PLAYLIST_ID}
    assert parse_youtube_input(VIDEO_ONE) == {"kind": "video", "id": VIDEO_ONE}
    assert parse_youtube_input(PLAYLIST_ID) == {"kind": "playlist", "id": PLAYLIST_ID}


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/watch?v=abcdefghijk",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/playlist",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "https://user:password@youtube.com/watch?v=abcdefghijk",
        "",
    ],
)
def test_unsupported_or_malformed_input_is_rejected(value):
    with pytest.raises(ValueError):
        parse_youtube_input(value)


def test_duration_parsing_formatting_and_speed_calculations():
    seconds = parse_iso_duration("P1DT2H3M4S")

    assert seconds == 93784
    assert format_duration(seconds) == "1 day, 2 hours, 3 minutes, 4 seconds"
    assert format_duration(0) == "0 seconds"
    assert playback_times(3600)[0] == {
        "speed": 1.25,
        "seconds": 2880,
        "duration": "48 minutes",
    }
    with pytest.raises(ValueError):
        parse_iso_duration("PTnot-a-duration")


def test_range_and_progress_validation():
    assert _range_bounds(20, 10, 50) == (10, 20)
    assert _range_bounds(20, None, None) == (1, 20)
    with pytest.raises(ValueError):
        _range_bounds(20, 21, None)
    with pytest.raises(ValueError):
        _range_bounds(20, 10, 9)
    with pytest.raises(ValueError):
        _range_bounds(20, 0, None)

    progress = progress_for_videos(
        [
            {"duration_seconds": 30, "accessible": True},
            {"duration_seconds": None, "accessible": False},
            {"duration_seconds": 70, "accessible": True},
        ],
        2,
    )
    assert progress == {
        "watched_count": 2,
        "video_count": 3,
        "watched_seconds": 30,
        "remaining_seconds": 70,
        "total_seconds": 100,
        "percent": 30,
        "unavailable_watched_count": 1,
        "unavailable_remaining_count": 0,
    }
    with pytest.raises(ValueError):
        progress_for_videos([], 1)


def test_watch_schedule_respects_weekdays_speed_and_include_today():
    monday = date(2024, 1, 1)

    assert estimate_finish_date(1800, 3600, {0, 2}, monday) == monday
    assert estimate_finish_date(5400, 3600, {0, 2}, monday) == date(2024, 1, 3)
    assert estimate_finish_date(1800, 3600, {0, 2}, monday, False) == date(2024, 1, 3)
    assert estimate_finish_date(10, 0, {0}, monday) is None
    assert estimate_finish_date(10, 3600, set(), monday) is None


def test_analyze_playlist_uses_order_inclusive_range_and_ignores_duplicate_page_items():
    async def run():
        return await analyze_inputs(
            f"https://youtube.com/playlist?list={PLAYLIST_ID}",
            api_key=FAKE_KEY,
            range_start=2,
            range_end=3,
            custom_speed=2.25,
            watched_count=1,
            transport=_mock_youtube_transport(),
        )

    results = asyncio.run(run())
    result = results[0]

    assert result["title"] == "Mock playlist"
    assert result["creator"] == "Playlist author"
    assert result["range"] == {"start": 2, "end": 3}
    assert result["video_count"] == 2
    assert result["total_seconds"] == 1845
    assert result["progress"]["watched_seconds"] == 1800
    assert result["progress"]["remaining_seconds"] == 45
    assert result["playback_times"][-1]["speed"] == 2.25
    assert [video["video_id"] for video in result["videos"]] == [VIDEO_TWO, VIDEO_THREE]


def test_mixed_valid_and_invalid_inputs_return_individual_results():
    async def run():
        return await analyze_inputs(
            f"https://youtube.com/playlist?list={PLAYLIST_ID}\nhttps://not-youtube.example/video",
            api_key=FAKE_KEY,
            transport=_mock_youtube_transport(),
        )

    results = asyncio.run(run())

    assert results[0]["title"] == "Mock playlist"
    assert "Only YouTube" in results[1]["error"]


def test_empty_playlist_returns_zero_duration_without_fake_video_data():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/playlists"):
            return httpx.Response(200, json={
                "items": [{
                    "id": PLAYLIST_ID,
                    "snippet": {"title": "Empty playlist", "channelTitle": "Author"},
                }]
            })
        if request.url.path.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"Unexpected request: {request.url.path}")

    results = asyncio.run(analyze_inputs(
        f"https://youtube.com/playlist?list={PLAYLIST_ID}",
        api_key=FAKE_KEY,
        transport=httpx.MockTransport(handler),
    ))

    assert results[0]["title"] == "Empty playlist"
    assert results[0]["video_count"] == 0
    assert results[0]["total_seconds"] == 0
    assert results[0]["videos"] == []


def test_multiple_video_inputs_are_batched_and_keep_input_order():
    results = asyncio.run(analyze_inputs(
        f"{VIDEO_ONE}\n{VIDEO_TWO}",
        api_key=FAKE_KEY,
        transport=_mock_youtube_transport(),
    ))

    assert [result.get("video_id") for result in results] == [VIDEO_ONE, VIDEO_TWO]
    assert [result.get("total_seconds") for result in results] == [3600, 1800]


def test_api_quota_errors_are_user_facing_and_do_not_include_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={
            "error": {
                "message": "quota exceeded",
                "errors": [{"reason": "quotaExceeded"}],
            }
        })

    async def run():
        async with YouTubeApi(FAKE_KEY, transport=httpx.MockTransport(handler)) as api:
            await api.get_playlist_metadata([PLAYLIST_ID])

    with pytest.raises(YouTubeApiError, match="quota has been exceeded") as error:
        asyncio.run(run())
    assert FAKE_KEY not in str(error.value)


def test_youtube_api_service_receives_key_without_returning_it():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["has_key"] = request.url.params.get("key") == FAKE_KEY
        return httpx.Response(200, json={"items": []})

    async def run():
        async with YouTubeApi(
            FAKE_KEY,
            transport=httpx.MockTransport(handler),
        ) as api:
            await api.get_video_metadata([VIDEO_ONE])

    asyncio.run(run())
    assert observed["has_key"] is True


def test_api_network_and_malformed_response_errors_are_friendly():
    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async def timeout_call():
        async with YouTubeApi(
            FAKE_KEY,
            transport=httpx.MockTransport(timeout_handler),
        ) as api:
            await api.get_playlist_metadata([PLAYLIST_ID])

    with pytest.raises(YouTubeApiError, match="did not respond in time"):
        asyncio.run(timeout_call())

    def malformed_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": "not-a-list"})

    async def malformed_call():
        async with YouTubeApi(
            FAKE_KEY,
            transport=httpx.MockTransport(malformed_handler),
        ) as api:
            await api.get_playlist_metadata([PLAYLIST_ID])

    with pytest.raises(YouTubeApiError, match="malformed playlist metadata"):
        asyncio.run(malformed_call())


def test_api_key_validation():
    with pytest.raises(ConfigurationError):
        validate_user_api_key("not a valid key")
    assert validate_user_api_key(FAKE_KEY) == FAKE_KEY


def test_dotenv_api_key_is_loaded_and_preferred_to_user_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"YOUTUBE_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    monkeypatch.setattr("youtube_tool.config.ENV_FILE", env_file)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEYS", raising=False)
    monkeypatch.delenv("APIS", raising=False)

    assert configured_api_keys() == [FAKE_KEY]
    assert select_api_key("AIzaOtherfakekey_0123456789abcdefgh") == FAKE_KEY


def test_user_api_key_is_fallback_when_server_key_is_missing(monkeypatch):
    monkeypatch.setattr("youtube_tool.config.ENV_FILE", ENV_FILE.parent / "missing-test-env")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEYS", raising=False)
    monkeypatch.delenv("APIS", raising=False)

    assert select_api_key(FAKE_KEY) == FAKE_KEY
    with pytest.raises(ConfigurationError, match="not configured"):
        select_api_key()


def test_analysis_endpoint_keeps_user_key_server_side(monkeypatch):
    captured = {}
    monkeypatch.setattr("youtube_tool.config.configured_api_keys", lambda: [])
    monkeypatch.setattr(
        "youtube_tool.config.ENV_FILE",
        ENV_FILE.parent / "missing-user-key-test-env",
    )
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEYS", raising=False)
    monkeypatch.delenv("APIS", raising=False)

    async def fake_analyze(input_text, **kwargs):
        captured.update(input_text=input_text, **kwargs)
        return [{"title": "Mock result"}]

    monkeypatch.setattr(app_module, "analyze_inputs", fake_analyze)
    response = client.post(
        "/api/analyze",
        json={"input_text": VIDEO_ONE, "api_key": FAKE_KEY},
    )

    assert response.status_code == 200
    assert response.json() == {"results": [{"title": "Mock result"}]}
    assert captured["api_key"] == FAKE_KEY
    assert FAKE_KEY not in response.text


def test_analysis_endpoint_uses_server_configured_key(monkeypatch):
    captured = {}

    async def fake_analyze(input_text, **kwargs):
        captured.update(input_text=input_text, **kwargs)
        return [{"title": "Mock result"}]

    monkeypatch.setenv("YOUTUBE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("YOUTUBE_API_KEYS", "")
    monkeypatch.setenv("APIS", "")
    monkeypatch.setattr(app_module, "analyze_inputs", fake_analyze)
    response = client.post(
        "/api/analyze",
        json={
            "input_text": VIDEO_ONE,
            "api_key": "not-a-valid-key",
        },
    )

    assert response.status_code == 200
    assert captured["api_key"] == FAKE_KEY
    assert FAKE_KEY not in response.text


def test_analysis_endpoint_reports_missing_server_key(monkeypatch):
    def no_key(_user_key=None):
        raise ConfigurationError("YouTube analysis is not configured.")

    monkeypatch.setattr(app_module, "select_api_key", no_key)
    response = client.post("/api/analyze", json={"input_text": VIDEO_ONE})

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_thumbnail_variant_generation_and_api_validation():
    variants = thumbnail_variants(f"https://youtu.be/{VIDEO_ONE}")

    assert variants["video_id"] == VIDEO_ONE
    assert len(variants["variants"]) == 5
    assert variants["variants"][0]["url"] == (
        f"https://img.youtube.com/vi/{VIDEO_ONE}/maxresdefault.jpg"
    )
    assert client.post(
        "/api/thumbnail-variants",
        json={"video_input": f"https://youtube.com/watch?v={VIDEO_ONE}"},
    ).status_code == 200
    assert client.post(
        "/api/thumbnail-variants",
        json={"video_input": f"https://youtube.com/playlist?list={PLAYLIST_ID}"},
    ).status_code == 422


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("90", 90), ("1:30", 90), ("1:02:03", 3723), ("0", 0)],
)
def test_timestamp_formats(value, seconds):
    assert parse_timestamp(value) == seconds


@pytest.mark.parametrize("value", ["", "-1", "1:60", "1:2:60", "1:2:3:4", "1000:00:00"])
def test_invalid_timestamps_are_rejected(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


def test_timestamp_link_preserves_other_query_parameters_and_replaces_start():
    generated = timestamp_link(
        f"https://youtu.be/{VIDEO_ONE}?si=share-token&t=12",
        "1:02",
    )

    assert generated == {
        "video_id": VIDEO_ONE,
        "seconds": 62,
        "url": f"https://www.youtube.com/watch?si=share-token&v={VIDEO_ONE}&t=62",
    }
    response = client.post(
        "/api/timestamp",
        json={"video_input": f"https://youtube.com/shorts/{VIDEO_ONE}", "timestamp": "2:03"},
    )
    assert response.status_code == 200
    assert response.json()["url"].endswith(f"v={VIDEO_ONE}&t=123")
    assert client.post(
        "/api/timestamp",
        json={"video_input": f"https://youtube.com/playlist?list={PLAYLIST_ID}", "timestamp": "10"},
    ).status_code == 422


def test_invalid_input_is_reported_without_api_credentials(monkeypatch):
    def no_key(_user_key=None):
        raise ConfigurationError("YouTube analysis is not configured.")

    monkeypatch.setattr(app_module, "select_api_key", no_key)
    response = client.post(
        "/api/analyze",
        json={"input_text": "https://not-youtube.example/video"},
    )

    assert response.status_code == 200
    assert "Only YouTube" in response.json()["results"][0]["error"]


def test_schedule_endpoint_and_invalid_weekdays():
    response = client.post(
        "/api/schedule",
        json={
            "remaining_seconds": 5400,
            "daily_seconds": 3600,
            "watching_weekdays": [0, 2],
            "speed": 1.0,
            "include_today": True,
            "start_date": "2024-01-01",
        },
    )
    invalid = client.post(
        "/api/schedule",
        json={
            "remaining_seconds": 20,
            "daily_seconds": 3600,
            "watching_weekdays": [7],
            "speed": 1.0,
            "include_today": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["finish_date"] == "2024-01-03"
    assert invalid.status_code == 422
