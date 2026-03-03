"""Tests for downloader/compress.py -- compress_video, _get_video_duration, _compress_second_pass."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from thumbot.downloader.compress import compress_video, _get_video_duration, _compress_second_pass


def _mock_subprocess(returncode=0, stdout=b"", stderr=b""):
    """Create a mock async subprocess."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


# ---- _get_video_duration ----

class TestGetVideoDuration:

    async def test_success(self):
        proc = _mock_subprocess(returncode=0, stdout=b"12.345\n")
        with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", return_value=proc):
            result = await _get_video_duration("/fake/video.mp4")
        assert result == pytest.approx(12.345)

    async def test_ffprobe_failure(self):
        proc = _mock_subprocess(returncode=1, stderr=b"error")
        with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", return_value=proc):
            result = await _get_video_duration("/fake/video.mp4")
        assert result is None

    async def test_exception_returns_none(self):
        with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", side_effect=OSError("no ffprobe")):
            result = await _get_video_duration("/fake/video.mp4")
        assert result is None


# ---- compress_video ----

class TestCompressVideo:

    def test_missing_input_file(self):
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(compress_video("/nonexistent/file.mp4", 8.0))
        assert result is None

    async def test_zero_duration(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)

        with patch("thumbot.downloader.compress._get_video_duration", return_value=0):
            result = await compress_video(str(input_file), 8.0)
        assert result is None

    async def test_bitrate_too_low(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)

        # Very long video + tiny target = bitrate below 100kbps
        with patch("thumbot.downloader.compress._get_video_duration", return_value=10000.0):
            result = await compress_video(str(input_file), 0.01)
        assert result is None

    async def test_ffmpeg_success_within_target(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)
        output_file = tmp_path / "video_compressed.mp4"

        proc = _mock_subprocess(returncode=0)

        async def fake_exec(*args, **kwargs):
            # Simulate ffmpeg creating a small output file
            output_file.write_bytes(b"y" * 3_000_000)
            return proc

        with patch("thumbot.downloader.compress._get_video_duration", return_value=30.0):
            with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", side_effect=fake_exec):
                result = await compress_video(str(input_file), 8.0)
        assert result == str(output_file)

    async def test_ffmpeg_output_too_large_triggers_second_pass(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)
        output_file = tmp_path / "video_compressed.mp4"

        proc = _mock_subprocess(returncode=0)

        async def fake_exec(*args, **kwargs):
            output_file.write_bytes(b"y" * 9_500_000)  # > 8.0 * 1.1
            return proc

        with patch("thumbot.downloader.compress._get_video_duration", return_value=30.0):
            with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", side_effect=fake_exec):
                with patch("thumbot.downloader.compress._compress_second_pass", return_value=None) as mock_second:
                    result = await compress_video(str(input_file), 8.0)
                    mock_second.assert_called_once()
        assert result is None

    async def test_ffmpeg_failure(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)

        proc = _mock_subprocess(returncode=1, stderr=b"encoding failed")

        with patch("thumbot.downloader.compress._get_video_duration", return_value=30.0):
            with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", return_value=proc):
                result = await compress_video(str(input_file), 8.0)
        assert result is None


# ---- _compress_second_pass ----

class TestCompressSecondPass:

    async def test_success(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)
        output_file = tmp_path / "video_compressed.mp4"

        proc = _mock_subprocess(returncode=0)

        async def fake_exec(*args, **kwargs):
            output_file.write_bytes(b"y" * 5_000_000)
            return proc

        with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await _compress_second_pass(str(input_file), 8.0, 30.0, str(output_file))
        assert result == str(output_file)

    async def test_bitrate_too_low(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)

        result = await _compress_second_pass(str(input_file), 0.01, 10000.0, "/out.mp4")
        assert result is None

    async def test_ffmpeg_failure(self, tmp_path):
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"x" * 10_000_000)

        proc = _mock_subprocess(returncode=1, stderr=b"failed")

        with patch("thumbot.downloader.compress.asyncio.create_subprocess_exec", return_value=proc):
            result = await _compress_second_pass(str(input_file), 8.0, 30.0, str(tmp_path / "out.mp4"))
        assert result is None
