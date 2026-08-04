"""Tests for bot/handlers.py -- URL extraction, provider matching, message handling."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from thumbot.config import Config, VideoQuality, PickerBehavior


def _make_handler(config):
    """Create a MessageHandler without triggering real I/O."""
    with patch("thumbot.bot.handlers.VideoDownloader"):
        with patch("thumbot.bot.handlers.load_providers", return_value=[
            "reddit",
            "instagram.com/reel",
            "instagram.com/p",
            "facebook.com/watch",
            "facebook.com/reel",
            "facebook.com/share/v",
            "facebook.com/share/r",
            "fb.watch",
            "x.com",
            "twitter.com",
        ]):
            from thumbot.bot.handlers import MessageHandler
            return MessageHandler(config)


def _make_message(content, bot=False, author_name="testuser", channel_id="12345", user_id="99"):
    """Create a mock discord.Message."""
    msg = MagicMock()
    msg.content = content
    msg.author.bot = bot
    msg.author.display_name = author_name
    msg.author.id = user_id
    msg.author.display_avatar.url = "https://cdn.discord.com/avatar.png"
    msg.channel.id = channel_id
    return msg


# ---- _extract_url ----

class TestExtractUrl:

    @pytest.fixture(autouse=True)
    def setup(self, config):
        self.handler = _make_handler(config)

    def test_raw_url(self):
        assert self.handler._extract_url(
            "check this https://instagram.com/reel/abc"
        ) == ("https://instagram.com/reel/abc", False)

    def test_markdown_link(self):
        assert self.handler._extract_url(
            "[cool video](https://reddit.com/r/foo/comments/123)"
        ) == ("https://reddit.com/r/foo/comments/123", False)

    def test_no_url(self):
        assert self.handler._extract_url("just some text with no link") == (None, False)

    def test_multiple_urls_returns_first(self):
        url, spoiler = self.handler._extract_url(
            "first https://instagram.com/reel/1 second https://reddit.com/2"
        )
        assert url == "https://instagram.com/reel/1"
        assert spoiler is False

    def test_url_with_query_params(self):
        url, _ = self.handler._extract_url(
            "https://instagram.com/reel/abc?igsh=MTN5azBx&foo=bar"
        )
        assert "igsh=MTN5azBx" in url

    def test_url_in_parentheses_no_trailing_paren(self):
        url, _ = self.handler._extract_url("(https://x.com/post/123)")
        assert url == "https://x.com/post/123"
        assert not url.endswith(")")

    def test_empty_string(self):
        assert self.handler._extract_url("") == (None, False)

    def test_spoiler_wrapped_url(self):
        assert self.handler._extract_url(
            "||https://instagram.com/reel/abc||"
        ) == ("https://instagram.com/reel/abc", True)

    def test_spoiler_wrapped_markdown_link(self):
        assert self.handler._extract_url(
            "||[nsfw](https://reddit.com/r/foo/comments/123)||"
        ) == ("https://reddit.com/r/foo/comments/123", True)


# ---- _extract_user_text ----

class TestExtractUserText:

    @pytest.fixture(autouse=True)
    def setup(self, config):
        self.handler = _make_handler(config)

    def test_raw_url_with_text(self):
        result = self.handler._extract_user_text(
            "look at this https://instagram.com/reel/abc",
            "https://instagram.com/reel/abc"
        )
        assert "look at this" in result
        assert "https://instagram.com/reel/abc" in result

    def test_markdown_link_replaced(self):
        url = "https://reddit.com/r/funny/post"
        result = self.handler._extract_user_text(
            f"check [this video]({url}) out",
            url
        )
        assert "🔗 this video" in result
        assert url in result

    def test_url_only(self):
        url = "https://instagram.com/reel/abc"
        result = self.handler._extract_user_text(url, url)
        assert result == url

    def test_empty_string_returns_none(self):
        assert self.handler._extract_user_text("", "https://x.com") is None

    def test_multiline_strips_blanks(self):
        result = self.handler._extract_user_text(
            "line1\n\n\nline2\n\nhttps://x.com/post",
            "https://x.com/post"
        )
        assert "\n\n\n" not in result
        assert "line1" in result
        assert "line2" in result


# ---- _check_provider ----

class TestCheckProvider:

    @pytest.fixture(autouse=True)
    def setup(self, config):
        self.handler = _make_handler(config)

    def test_supported_instagram_reel(self):
        provider, supported = self.handler._check_provider(
            "https://www.instagram.com/reel/DVJ6n17khYN/"
        )
        assert provider == "instagram.com/reel"
        assert supported is True

    def test_supported_reddit(self):
        provider, supported = self.handler._check_provider(
            "https://www.reddit.com/r/funny/comments/abc"
        )
        assert provider == "reddit"
        assert supported is True

    def test_unsupported_youtube(self):
        provider, supported = self.handler._check_provider(
            "https://www.youtube.com/watch?v=abc"
        )
        assert supported is False
        assert "youtube.com" in provider

    def test_malformed_url(self):
        provider, supported = self.handler._check_provider("not-a-url")
        assert supported is False


# ---- handle_message ----

class TestHandleMessage:

    @pytest.fixture(autouse=True)
    def setup(self, config):
        self.handler = _make_handler(config)

    async def test_ignores_bot_messages(self):
        msg = _make_message("https://instagram.com/reel/abc", bot=True)
        await self.handler.handle_message(msg)
        assert self.handler.queue_size == 0

    async def test_no_url_not_queued(self):
        msg = _make_message("hello world no links here")
        await self.handler.handle_message(msg)
        assert self.handler.queue_size == 0

    async def test_unsupported_provider_not_queued(self):
        msg = _make_message("https://youtube.com/watch?v=abc")
        await self.handler.handle_message(msg)
        assert self.handler.queue_size == 0

    async def test_supported_provider_queued(self):
        msg = _make_message("https://www.instagram.com/reel/abc123")
        await self.handler.handle_message(msg)
        assert self.handler.queue_size == 1

    async def test_queued_task_has_correct_fields(self):
        msg = _make_message("https://www.instagram.com/reel/abc123", author_name="shoofio")
        await self.handler.handle_message(msg)
        task = self.handler._task_queue.get_nowait()
        assert task.url == "https://www.instagram.com/reel/abc123"
        assert task.provider == "instagram.com/reel"
        assert task.username == "shoofio"
