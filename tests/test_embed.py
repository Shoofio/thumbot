"""Tests for bot/embed.py -- get_platform_color, create_video_embed."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import discord
from thumbot.bot.embed import get_platform_color, create_video_embed, DEFAULT_COLOR


# ---- get_platform_color ----

class TestGetPlatformColor:

    def test_instagram(self):
        assert get_platform_color("https://instagram.com/reel/abc") == 0xE1306C

    def test_reddit(self):
        assert get_platform_color("https://www.reddit.com/r/funny") == 0xFF4500

    def test_facebook(self):
        assert get_platform_color("https://facebook.com/share/v/123") == 0x1877F2

    def test_x_com(self):
        assert get_platform_color("https://x.com/user/status/123") == 0x1DA1F2

    def test_unknown_returns_default(self):
        assert get_platform_color("https://example.com/video") == DEFAULT_COLOR


# ---- create_video_embed ----

class TestCreateVideoEmbed:

    def test_basic_embed(self):
        embed = create_video_embed(
            username="shoofio",
            avatar_url="https://cdn.discord.com/avatar.png",
            original_url="https://instagram.com/reel/abc",
            user_id="12345",
        )
        assert isinstance(embed, discord.Embed)
        assert embed.color.value == 0xE1306C
        assert embed.author.name == "shoofio"

    def test_with_user_text(self):
        embed = create_video_embed(
            username="user",
            avatar_url="https://avatar.url",
            original_url="https://reddit.com/r/funny",
            user_id="1",
            user_text="check this out!",
        )
        assert embed.description == "check this out!"

    def test_without_user_text(self):
        embed = create_video_embed(
            username="user",
            avatar_url="https://avatar.url",
            original_url="https://reddit.com/r/funny",
            user_id="1",
        )
        assert embed.description is None or embed.description == discord.Embed.Empty
