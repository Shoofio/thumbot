"""Tests for remaining VideoDownloader methods: _download_file, _handle_picker_with_size_check, _download_and_compress."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aioresponses import aioresponses

from thumbot.config import Config, VideoQuality, PickerBehavior
from thumbot.downloader.download import VideoDownloader
from thumbot.downloader.exceptions import CobaltError, DownloadError


# ---- _download_file ----

class TestDownloadFile:

    async def test_success(self, downloader, tmp_dir):
        video_url = "https://cdn.example.com/video.mp4"
        with aioresponses() as m:
            m.get(video_url, body=b"fakevideo" * 100)
            path = await downloader._download_file(video_url, "test.mp4")
        assert os.path.exists(path)
        assert path.endswith("test.mp4")
        assert os.path.getsize(path) == 900

    async def test_auto_filename_from_url(self, downloader, tmp_dir):
        video_url = "https://cdn.example.com/path/clip.mp4"
        with aioresponses() as m:
            m.get(video_url, body=b"data")
            path = await downloader._download_file(video_url)
        assert "clip.mp4" in os.path.basename(path)

    async def test_no_extension_gets_mp4(self, downloader, tmp_dir):
        video_url = "https://cdn.example.com/videostream"
        with aioresponses() as m:
            m.get(video_url, body=b"data")
            path = await downloader._download_file(video_url)
        assert path.endswith(".mp4")

    async def test_sanitizes_filename(self, downloader, tmp_dir):
        video_url = "https://cdn.example.com/video.mp4"
        with aioresponses() as m:
            m.get(video_url, body=b"data")
            path = await downloader._download_file(video_url, "bad<>file|name.mp4")
        basename = os.path.basename(path)
        assert "<" not in basename
        assert ">" not in basename
        assert "|" not in basename

    async def test_client_error_raises_download_error(self, downloader, tmp_dir):
        import aiohttp
        video_url = "https://cdn.example.com/broken.mp4"
        with aioresponses() as m:
            m.get(video_url, exception=aiohttp.ClientConnectionError("refused"))
            with pytest.raises(DownloadError, match="Failed to download"):
                await downloader._download_file(video_url, "broken.mp4")
        assert not os.path.exists(os.path.join(tmp_dir, "broken.mp4"))


# ---- _handle_picker_with_size_check ----

class TestHandlePickerWithSizeCheck:

    async def test_empty_items_raises(self, downloader):
        with pytest.raises(CobaltError, match="No files in picker"):
            await downloader._handle_picker_with_size_check([], VideoQuality.MAX)

    async def test_first_behavior_downloads_only_first(self, downloader, mock_cobalt, tmp_dir):
        downloader.config.picker_behavior = PickerBehavior.FIRST
        mock_cobalt.get_file_size.return_value = 100

        items = [
            {"url": "https://cdn/1.mp4", "thumb": None},
            {"url": "https://cdn/2.mp4", "thumb": None},
            {"url": "https://cdn/3.mp4", "thumb": None},
        ]

        fake_path = os.path.join(tmp_dir, "1.mp4")

        async def fake_download(url, filename=None):
            with open(fake_path, "wb") as f:
                f.write(b"x" * 100)
            return fake_path

        downloader._download_file = AsyncMock(side_effect=fake_download)

        paths = await downloader._handle_picker_with_size_check(items, VideoQuality.MAX)
        assert len(paths) == 1
        downloader._download_file.assert_called_once()

    async def test_last_behavior_downloads_only_last(self, downloader, mock_cobalt, tmp_dir):
        downloader.config.picker_behavior = PickerBehavior.LAST
        mock_cobalt.get_file_size.return_value = 100

        items = [
            {"url": "https://cdn/1.mp4", "thumb": None},
            {"url": "https://cdn/2.mp4", "thumb": None},
        ]

        fake_path = os.path.join(tmp_dir, "2.mp4")

        async def fake_download(url, filename=None):
            with open(fake_path, "wb") as f:
                f.write(b"x" * 100)
            return fake_path

        downloader._download_file = AsyncMock(side_effect=fake_download)

        paths = await downloader._handle_picker_with_size_check(items, VideoQuality.MAX)
        assert len(paths) == 1

    async def test_item_too_large_triggers_compression(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.get_file_size.return_value = 20 * 1024 * 1024  # 20MB, over 8MB limit

        items = [{"url": "https://cdn/big.mp4", "thumb": None}]
        compressed = os.path.join(tmp_dir, "compressed.mp4")

        downloader._download_and_compress = AsyncMock(return_value=compressed)

        paths = await downloader._handle_picker_with_size_check(items, VideoQuality.MAX)
        assert compressed in paths
        downloader._download_and_compress.assert_called_once()

    async def test_per_item_exception_skipped(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.get_file_size.side_effect = Exception("network error")

        items = [{"url": "https://cdn/1.mp4", "thumb": None}]

        paths = await downloader._handle_picker_with_size_check(items, VideoQuality.MAX)
        assert paths == []


# ---- _download_and_compress ----

class TestDownloadAndCompress:

    async def test_compression_succeeds(self, downloader, config, tmp_dir):
        original = os.path.join(tmp_dir, "original.mp4")
        compressed = os.path.join(tmp_dir, "original_compressed.mp4")

        async def fake_download(url, filename=None):
            with open(original, "wb") as f:
                f.write(b"x" * 10_000_000)
            return original

        downloader._download_file = AsyncMock(side_effect=fake_download)

        async def fake_compress(input_path, target):
            with open(compressed, "wb") as f:
                f.write(b"y" * 3_000_000)
            return compressed

        with patch("thumbot.downloader.download.compress_video", side_effect=fake_compress):
            result = await downloader._download_and_compress("https://cdn/v.mp4", "v.mp4", 8.0)
        assert result == compressed
        assert not os.path.exists(original), "Original should be cleaned up"

    async def test_compression_fails_cleans_up(self, downloader, tmp_dir):
        original = os.path.join(tmp_dir, "original.mp4")

        async def fake_download(url, filename=None):
            with open(original, "wb") as f:
                f.write(b"x" * 10_000_000)
            return original

        downloader._download_file = AsyncMock(side_effect=fake_download)

        with patch("thumbot.downloader.download.compress_video", return_value=None):
            result = await downloader._download_and_compress("https://cdn/v.mp4", "v.mp4", 8.0)
        assert result is None
        assert not os.path.exists(original), "Original should be cleaned up on failure"

    async def test_compressed_still_too_large(self, downloader, config, tmp_dir):
        original = os.path.join(tmp_dir, "original.mp4")
        compressed = os.path.join(tmp_dir, "original_compressed.mp4")

        async def fake_download(url, filename=None):
            with open(original, "wb") as f:
                f.write(b"x" * 10_000_000)
            return original

        downloader._download_file = AsyncMock(side_effect=fake_download)

        async def fake_compress(input_path, target):
            with open(compressed, "wb") as f:
                f.write(b"y" * 9_000_000)  # Still over 8MB
            return compressed

        with patch("thumbot.downloader.download.compress_video", side_effect=fake_compress):
            result = await downloader._download_and_compress("https://cdn/v.mp4", "v.mp4", 8.0)
        assert result is None
