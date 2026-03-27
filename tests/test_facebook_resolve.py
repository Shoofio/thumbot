"""Tests for VideoDownloader._resolve_facebook_share_url"""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, MagicMock
from yarl import URL

import aiohttp


def _mock_session_with_resolved_url(resolved_url: str):
    """Create a mock session where GET returns an async context manager with the given resolved URL."""
    mock_response = MagicMock()
    mock_response.url = URL(resolved_url)

    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_response

    mock_session = MagicMock()
    mock_session.get.return_value = ctx

    return mock_session


class TestResolveFacebookShareUrl:
    """Resolve Facebook share links to actual content URLs before Cobalt."""

    async def test_resolves_share_v_url(self, downloader):
        mock_session = _mock_session_with_resolved_url(
            "https://www.facebook.com/reel/2473437046437075/"
        )
        downloader._get_session = AsyncMock(return_value=mock_session)

        result = await downloader._resolve_facebook_share_url(
            "https://www.facebook.com/share/v/1FtYiBbiPb/"
        )
        assert result == "https://www.facebook.com/reel/2473437046437075/"
        mock_session.get.assert_called_once()

    async def test_resolves_share_r_url(self, downloader):
        mock_session = _mock_session_with_resolved_url(
            "https://www.facebook.com/reel/123456/"
        )
        downloader._get_session = AsyncMock(return_value=mock_session)

        result = await downloader._resolve_facebook_share_url(
            "https://www.facebook.com/share/r/abc123/"
        )
        assert result == "https://www.facebook.com/reel/123456/"

    async def test_non_facebook_url_passes_through(self, downloader):
        mock_session = MagicMock()
        downloader._get_session = AsyncMock(return_value=mock_session)

        result = await downloader._resolve_facebook_share_url(
            "https://www.instagram.com/reel/abc123/"
        )
        assert result == "https://www.instagram.com/reel/abc123/"
        mock_session.get.assert_not_called()

    async def test_facebook_non_share_url_passes_through(self, downloader):
        mock_session = MagicMock()
        downloader._get_session = AsyncMock(return_value=mock_session)

        result = await downloader._resolve_facebook_share_url(
            "https://www.facebook.com/reel/2473437046437075/"
        )
        assert result == "https://www.facebook.com/reel/2473437046437075/"
        mock_session.get.assert_not_called()

    async def test_falls_back_on_network_error(self, downloader):
        ctx = AsyncMock()
        ctx.__aenter__.side_effect = aiohttp.ClientError("timeout")

        mock_session = MagicMock()
        mock_session.get.return_value = ctx

        downloader._get_session = AsyncMock(return_value=mock_session)

        original = "https://www.facebook.com/share/v/1FtYiBbiPb/"
        result = await downloader._resolve_facebook_share_url(original)
        assert result == original
