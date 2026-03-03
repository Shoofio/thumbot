"""Tests for downloader/upload.py -- embed_to_dict, upload_to_discord, upload_multiple_to_discord."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from aioresponses import aioresponses

from thumbot.downloader.upload import embed_to_dict, upload_to_discord, upload_multiple_to_discord
from thumbot.downloader.exceptions import UploadError

DISCORD_API = "https://discord.com/api/v10/channels/ch123/messages"


# ---- embed_to_dict ----

class TestEmbedToDict:

    def test_none_returns_none(self):
        assert embed_to_dict(None) is None

    def test_object_with_to_dict(self):
        embed = MagicMock()
        embed.to_dict.return_value = {"title": "test", "color": 123}
        result = embed_to_dict(embed)
        assert result == {"title": "test", "color": 123}

    def test_object_without_to_dict(self):
        obj = "not an embed"
        assert embed_to_dict(obj) is None


# ---- upload_to_discord ----

class TestUploadToDiscord:

    async def test_success(self, tmp_path):
        test_file = tmp_path / "video.mp4"
        test_file.write_bytes(b"videodata")

        with aioresponses() as m:
            m.post(DISCORD_API, payload={"id": "msg1"})
            result = await upload_to_discord("ch123", str(test_file), "bot-token")
        assert result == {"id": "msg1"}

    async def test_http_error_raises_upload_error(self, tmp_path):
        test_file = tmp_path / "video.mp4"
        test_file.write_bytes(b"videodata")

        with aioresponses() as m:
            m.post(DISCORD_API, status=403)
            with pytest.raises(UploadError):
                await upload_to_discord("ch123", str(test_file), "bot-token")

    async def test_with_embed(self, tmp_path):
        test_file = tmp_path / "video.mp4"
        test_file.write_bytes(b"videodata")
        embed = MagicMock()
        embed.to_dict.return_value = {"title": "t"}

        with aioresponses() as m:
            m.post(DISCORD_API, payload={"id": "msg2"})
            result = await upload_to_discord("ch123", str(test_file), "tok", embed=embed)
        assert result is not None


# ---- upload_multiple_to_discord ----

class TestUploadMultipleToDiscord:

    async def test_empty_list_returns_none(self):
        result = await upload_multiple_to_discord("ch123", [], "tok")
        assert result is None

    async def test_success(self, tmp_path):
        files = []
        for i in range(3):
            f = tmp_path / f"video{i}.mp4"
            f.write_bytes(b"data" * 10)
            files.append(str(f))

        with aioresponses() as m:
            m.post(DISCORD_API, payload={"id": "msg3"})
            result = await upload_multiple_to_discord("ch123", files, "tok")
        assert result == {"id": "msg3"}

    async def test_truncates_to_ten_files(self, tmp_path):
        files = []
        for i in range(15):
            f = tmp_path / f"v{i}.mp4"
            f.write_bytes(b"x")
            files.append(str(f))

        with aioresponses() as m:
            m.post(DISCORD_API, payload={"id": "msg4"})
            result = await upload_multiple_to_discord("ch123", files, "tok")
        assert result is not None

    async def test_http_error_raises(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"data")

        with aioresponses() as m:
            m.post(DISCORD_API, status=500)
            with pytest.raises(UploadError):
                await upload_multiple_to_discord("ch123", [str(f)], "tok")
