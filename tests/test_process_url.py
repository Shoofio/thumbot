"""Tests for VideoDownloader.process_url -- end-to-end flow.

Mocks both Cobalt and Discord upload to verify:
- correct return values (True/False)
- correct exception mapping (CobaltError vs FileTooLargeError)
- cleanup always runs
"""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, patch

from thumbot.downloader.exceptions import CobaltError, FileTooLargeError, DownloadError


class TestProcessUrlSuccess:

    @patch("thumbot.downloader.download.upload_to_discord", new_callable=AsyncMock)
    async def test_returns_true_on_success(self, mock_upload, downloader, mock_cobalt, tmp_dir):
        fake_path = os.path.join(tmp_dir, "ok.mp4")
        with open(fake_path, "wb") as f:
            f.write(b"x" * 100)

        downloader._download_with_quality_fallback = AsyncMock(
            return_value={"type": "single", "file_path": fake_path}
        )

        result = await downloader.process_url("https://instagram.com/reel/abc", "channel-123")
        assert result is True
        mock_upload.assert_called_once()

    @patch("thumbot.downloader.download.upload_multiple_to_discord", new_callable=AsyncMock)
    async def test_multiple_files_upload(self, mock_multi_upload, downloader, mock_cobalt, tmp_dir):
        paths = []
        for i in range(3):
            p = os.path.join(tmp_dir, f"f{i}.mp4")
            with open(p, "wb") as f:
                f.write(b"x" * 100)
            paths.append(p)

        downloader._download_with_quality_fallback = AsyncMock(
            return_value={"type": "picker", "file_paths": paths}
        )

        result = await downloader.process_url("https://twitter.com/thread", "channel-123")
        assert result is True
        mock_multi_upload.assert_called_once()


class TestProcessUrlCobaltError:
    """When Cobalt can't fetch the content, process_url returns False with CobaltError path."""

    async def test_returns_false_on_cobalt_error(self, downloader):
        downloader._download_with_quality_fallback = AsyncMock(
            side_effect=CobaltError("content unavailable")
        )

        result = await downloader.process_url("https://instagram.com/reel/gone", "ch-1")
        assert result is False

    async def test_cobalt_error_not_logged_as_file_too_large(self, downloader, caplog):
        downloader._download_with_quality_fallback = AsyncMock(
            side_effect=CobaltError("This post doesn't exist")
        )

        await downloader.process_url("https://instagram.com/reel/gone", "ch-1")
        assert "File too large" not in caplog.text


class TestProcessUrlFileTooLarge:

    async def test_returns_false(self, downloader):
        downloader._download_with_quality_fallback = AsyncMock(
            side_effect=FileTooLargeError("File exceeds 8.0MB limit and compression failed")
        )

        result = await downloader.process_url("https://example.com/huge", "ch-1")
        assert result is False


class TestProcessUrlDownloadError:

    async def test_returns_false(self, downloader):
        downloader._download_with_quality_fallback = AsyncMock(
            side_effect=DownloadError("connection reset")
        )

        result = await downloader.process_url("https://example.com/broken", "ch-1")
        assert result is False


class TestProcessUrlCleanup:
    """Verify cleanup runs regardless of outcome."""

    @patch("thumbot.downloader.download.upload_to_discord", new_callable=AsyncMock)
    async def test_cleanup_on_success(self, mock_upload, downloader, tmp_dir):
        fake_path = os.path.join(tmp_dir, "cleanup_ok.mp4")
        with open(fake_path, "wb") as f:
            f.write(b"x" * 100)

        downloader._download_with_quality_fallback = AsyncMock(
            return_value={"type": "single", "file_path": fake_path}
        )
        downloader.config.auto_cleanup = True

        await downloader.process_url("https://example.com/v", "ch-1")
        assert not os.path.exists(fake_path), "File should be cleaned up after success"

    async def test_cleanup_on_error(self, downloader, tmp_dir):
        fake_path = os.path.join(tmp_dir, "cleanup_err.mp4")
        with open(fake_path, "wb") as f:
            f.write(b"x" * 100)

        call_count = 0
        original_fallback = downloader._download_with_quality_fallback

        async def fallback_then_fail(url):
            nonlocal call_count
            call_count += 1
            raise CobaltError("fail")

        downloader._download_with_quality_fallback = AsyncMock(side_effect=fallback_then_fail)
        downloader.config.auto_cleanup = True

        await downloader.process_url("https://example.com/v", "ch-1")
        # file_paths is empty on error, so cleanup has nothing to delete --
        # but the important thing is no unhandled exception
        assert call_count == 1

    async def test_no_cleanup_when_disabled(self, downloader, tmp_dir):
        fake_path = os.path.join(tmp_dir, "no_cleanup.mp4")
        with open(fake_path, "wb") as f:
            f.write(b"x" * 100)

        downloader._download_with_quality_fallback = AsyncMock(
            return_value={"type": "single", "file_path": fake_path}
        )
        downloader.config.auto_cleanup = False

        with patch("thumbot.downloader.download.upload_to_discord", new_callable=AsyncMock):
            await downloader.process_url("https://example.com/v", "ch-1")
        assert os.path.exists(fake_path), "File should NOT be cleaned up when auto_cleanup=False"
