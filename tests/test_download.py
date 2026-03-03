"""Tests for VideoDownloader._download_with_quality_fallback

Covers the bug fix where CobaltError was incorrectly reported as FileTooLargeError
when content is unavailable or auth-gated.
"""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, patch

from thumbot.config import VideoQuality
from thumbot.downloader.exceptions import CobaltError, FileTooLargeError


class TestAllQualitiesCobaltError:
    """The bug: when every quality raises CobaltError, should NOT raise FileTooLargeError."""

    async def test_raises_cobalt_error_not_file_too_large(self, downloader, mock_cobalt):
        mock_cobalt.download_video.side_effect = CobaltError("content unavailable")

        with pytest.raises(CobaltError, match="content unavailable"):
            await downloader._download_with_quality_fallback(
                "https://instagram.com/reel/nonexistent"
            )

    async def test_does_not_raise_file_too_large(self, downloader, mock_cobalt):
        mock_cobalt.download_video.side_effect = CobaltError("auth required")

        with pytest.raises(CobaltError):
            await downloader._download_with_quality_fallback(
                "https://instagram.com/reel/private"
            )
        # Explicitly verify it's NOT FileTooLargeError
        try:
            await downloader._download_with_quality_fallback(
                "https://instagram.com/reel/private"
            )
        except CobaltError:
            pass
        except FileTooLargeError:
            pytest.fail("Got FileTooLargeError when CobaltError was expected")

    async def test_preserves_last_cobalt_error_message(self, downloader, mock_cobalt):
        errors = [
            CobaltError("Quality not available: max"),
            CobaltError("Quality not available: 4k"),
            CobaltError("content.unavailable: This post doesn't exist"),
        ]
        mock_cobalt.download_video.side_effect = errors * 3  # enough for all qualities

        with pytest.raises(CobaltError, match="content.unavailable"):
            await downloader._download_with_quality_fallback(
                "https://instagram.com/reel/gone"
            )


class TestHappyPath:
    """Cobalt returns a URL, file fits within size limit."""

    async def test_single_file_within_limit(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.download_video.return_value = {
            "status": "redirect",
            "url": "https://cdn.example.com/video.mp4",
            "filename": "video.mp4",
        }
        mock_cobalt.process_response.return_value = {
            "type": "single",
            "url": "https://cdn.example.com/video.mp4",
            "filename": "video.mp4",
        }
        mock_cobalt.get_file_size.return_value = 1_000_000  # 1MB, under 8MB limit

        fake_path = os.path.join(tmp_dir, "video.mp4")

        async def fake_download(url, filename=None):
            with open(fake_path, "wb") as f:
                f.write(b"x" * 1_000_000)
            return fake_path

        downloader._download_file = AsyncMock(side_effect=fake_download)

        result = await downloader._download_with_quality_fallback(
            "https://instagram.com/reel/abc"
        )
        assert result["type"] == "single"
        assert result["file_path"] == fake_path

    async def test_unknown_size_proceeds_with_download(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.download_video.return_value = {"status": "tunnel", "url": "https://cdn.example.com/v.mp4"}
        mock_cobalt.process_response.return_value = {
            "type": "single",
            "url": "https://cdn.example.com/v.mp4",
            "filename": "v.mp4",
        }
        mock_cobalt.get_file_size.return_value = 0  # unknown

        fake_path = os.path.join(tmp_dir, "v.mp4")

        async def fake_download(url, filename=None):
            with open(fake_path, "wb") as f:
                f.write(b"x" * 500_000)
            return fake_path

        downloader._download_file = AsyncMock(side_effect=fake_download)

        result = await downloader._download_with_quality_fallback("https://example.com/video")
        assert result["type"] == "single"


class TestFileTooLarge:
    """All qualities too large -- compression path."""

    async def test_compression_succeeds(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.download_video.return_value = {"status": "redirect", "url": "https://cdn/v.mp4"}
        mock_cobalt.process_response.return_value = {
            "type": "single",
            "url": "https://cdn/v.mp4",
            "filename": "big.mp4",
        }
        # Every quality reports 20MB (over 8MB limit)
        mock_cobalt.get_file_size.return_value = 20 * 1024 * 1024

        compressed = os.path.join(tmp_dir, "compressed.mp4")
        with open(compressed, "wb") as f:
            f.write(b"x" * 5_000_000)  # 5MB compressed

        downloader._download_and_compress = AsyncMock(return_value=compressed)

        result = await downloader._download_with_quality_fallback("https://example.com/big")
        assert result["type"] == "single"
        assert result["file_path"] == compressed
        downloader._download_and_compress.assert_called_once()

    async def test_compression_fails_raises_file_too_large(self, downloader, mock_cobalt):
        mock_cobalt.download_video.return_value = {"status": "redirect", "url": "https://cdn/v.mp4"}
        mock_cobalt.process_response.return_value = {
            "type": "single",
            "url": "https://cdn/v.mp4",
            "filename": "huge.mp4",
        }
        mock_cobalt.get_file_size.return_value = 100 * 1024 * 1024  # 100MB

        downloader._download_and_compress = AsyncMock(return_value=None)

        with pytest.raises(FileTooLargeError, match="compression failed"):
            await downloader._download_with_quality_fallback("https://example.com/huge")


class TestMixedResults:
    """Some qualities fail with CobaltError, others succeed."""

    async def test_first_quality_fails_second_succeeds(self, downloader, mock_cobalt, tmp_dir, config):
        # Only test with two qualities to keep it simple
        config.preferred_quality = VideoQuality.FHD_1080P

        call_count = 0

        async def download_video_side_effect(url, quality):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CobaltError("Quality not available: 1080p")
            return {"status": "redirect", "url": "https://cdn/v720.mp4", "filename": "v.mp4"}

        mock_cobalt.download_video.side_effect = download_video_side_effect
        mock_cobalt.process_response.return_value = {
            "type": "single",
            "url": "https://cdn/v720.mp4",
            "filename": "v.mp4",
        }
        mock_cobalt.get_file_size.return_value = 2_000_000  # 2MB

        fake_path = os.path.join(tmp_dir, "v.mp4")

        async def fake_download(url, filename=None):
            with open(fake_path, "wb") as f:
                f.write(b"x" * 2_000_000)
            return fake_path

        downloader._download_file = AsyncMock(side_effect=fake_download)

        result = await downloader._download_with_quality_fallback("https://example.com/video")
        assert result["type"] == "single"
        assert call_count == 2  # first failed, second succeeded


class TestPickerResponse:
    """Cobalt returns a picker (multi-file) response."""

    async def test_picker_files_returned(self, downloader, mock_cobalt, tmp_dir):
        mock_cobalt.download_video.return_value = {"status": "picker", "picker": []}
        mock_cobalt.process_response.return_value = {
            "type": "picker",
            "items": [
                {"url": "https://cdn/1.mp4", "thumb": None},
                {"url": "https://cdn/2.mp4", "thumb": None},
            ],
        }

        paths = [os.path.join(tmp_dir, f"{i}.mp4") for i in range(2)]
        for p in paths:
            with open(p, "wb") as f:
                f.write(b"x" * 100)

        downloader._handle_picker_with_size_check = AsyncMock(return_value=paths)

        result = await downloader._download_with_quality_fallback("https://twitter.com/thread")
        assert result["type"] == "picker"
        assert len(result["file_paths"]) == 2
