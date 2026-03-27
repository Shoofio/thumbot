import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from aioresponses import aioresponses

from thumbot.downloader.cobalt import CobaltClient
from thumbot.downloader.exceptions import CobaltError
from thumbot.config import VideoQuality


COBALT_URL = "http://cobalt-test:9000"


@pytest.fixture
async def cobalt():
    client = CobaltClient(COBALT_URL, timeout=5)
    yield client
    await client.close()


# --- process_response (pure, no I/O) ---

class TestProcessResponse:
    def setup_method(self):
        self.client = CobaltClient(COBALT_URL)

    def test_redirect_response(self):
        result = self.client.process_response({
            "status": "redirect",
            "url": "https://cdn.example.com/video.mp4",
            "filename": "video.mp4",
        })
        assert result["type"] == "single"
        assert result["url"] == "https://cdn.example.com/video.mp4"
        assert result["filename"] == "video.mp4"

    def test_tunnel_response(self):
        result = self.client.process_response({
            "status": "tunnel",
            "url": "https://cdn.example.com/tunnel/abc",
            "filename": "clip.mp4",
        })
        assert result["type"] == "single"
        assert result["url"] == "https://cdn.example.com/tunnel/abc"

    def test_picker_response(self):
        result = self.client.process_response({
            "status": "picker",
            "picker": [
                {"url": "https://cdn.example.com/1.mp4", "thumb": "https://t1.jpg"},
                {"url": "https://cdn.example.com/2.mp4", "thumb": "https://t2.jpg"},
            ],
        })
        assert result["type"] == "picker"
        assert len(result["items"]) == 2
        assert result["items"][0]["url"] == "https://cdn.example.com/1.mp4"

    def test_error_response_raises(self):
        with pytest.raises(CobaltError, match="Cobalt processing error"):
            self.client.process_response({
                "status": "error",
                "error": {"code": "content.unavailable"},
            })

    def test_unknown_status_returns_raw(self):
        raw = {"status": "something_new", "data": 123}
        result = self.client.process_response(raw)
        assert result == raw


# --- download_video (HTTP calls) ---

class TestDownloadVideo:

    async def test_success_redirect(self, cobalt):
        body = {"status": "redirect", "url": "https://cdn.example.com/v.mp4"}
        with aioresponses() as m:
            m.post(COBALT_URL + "/", payload=body)
            result = await cobalt.download_video("https://instagram.com/reel/abc")
        assert result["status"] == "redirect"

    async def test_success_with_quality(self, cobalt):
        body = {"status": "tunnel", "url": "https://cdn.example.com/v720.mp4"}
        with aioresponses() as m:
            m.post(COBALT_URL + "/", payload=body)
            result = await cobalt.download_video(
                "https://instagram.com/reel/abc", VideoQuality.HD_720P
            )
        assert result["status"] == "tunnel"

    async def test_http_400_raises_cobalt_error(self, cobalt):
        with aioresponses() as m:
            m.post(COBALT_URL + "/", status=400)
            with pytest.raises(CobaltError, match="unknown"):
                await cobalt.download_video(
                    "https://instagram.com/reel/abc", VideoQuality.UHD_4K
                )

    async def test_error_status_in_json_raises(self, cobalt):
        body = {
            "status": "error",
            "error": {"code": "content.unavailable"},
            "text": "This content is not available",
        }
        with aioresponses() as m:
            m.post(COBALT_URL + "/", payload=body)
            with pytest.raises(CobaltError, match="content.unavailable"):
                await cobalt.download_video("https://instagram.com/reel/gone")

    async def test_network_error_raises(self, cobalt):
        import aiohttp
        with aioresponses() as m:
            m.post(COBALT_URL + "/", exception=aiohttp.ClientConnectionError("refused"))
            with pytest.raises(CobaltError, match="Cobalt request failed"):
                await cobalt.download_video("https://instagram.com/reel/abc")

    async def test_http_500_raises(self, cobalt):
        with aioresponses() as m:
            m.post(COBALT_URL + "/", status=500)
            with pytest.raises(CobaltError):
                await cobalt.download_video("https://instagram.com/reel/abc")


# --- get_file_size ---

class TestGetFileSize:

    async def test_returns_content_length(self, cobalt):
        with aioresponses() as m:
            m.head(
                "https://cdn.example.com/video.mp4",
                headers={"content-length": "5242880"},
            )
            size = await cobalt.get_file_size("https://cdn.example.com/video.mp4")
        assert size == 5242880

    async def test_returns_zero_when_missing(self, cobalt):
        with aioresponses() as m:
            m.head("https://cdn.example.com/video.mp4", headers={})
            size = await cobalt.get_file_size("https://cdn.example.com/video.mp4")
        assert size == 0

    async def test_returns_zero_on_error(self, cobalt):
        import aiohttp
        with aioresponses() as m:
            m.head(
                "https://cdn.example.com/video.mp4",
                exception=aiohttp.ClientError("timeout"),
            )
            size = await cobalt.get_file_size("https://cdn.example.com/video.mp4")
        assert size == 0
