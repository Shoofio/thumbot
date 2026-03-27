"""
E2E tests that run against a live thumbot instance connected to a real Discord server.

The bot must be running and connected to the test server before these tests execute.
A warmup probe runs first to confirm the bot is online.
"""

import pytest

# ── Known test URLs ──────────────────────────────────────────────────────────
# These must be short/small enough to stay under the file-size limit so the
# bot can actually download and upload them.

TWITTER_VIDEO = "https://x.com/Osinttechnical/status/2028899082412908623"
INSTAGRAM_REEL = "https://www.instagram.com/reel/DVUVjI6EUDb/?igsh=YWc5NGtoaTZtcTZu"
INSTAGRAM_MULTI_IMAGE = "https://instagram.com/p/DR-vRaRjFyY"
REDDIT_NEEDS_COMPRESSION = "https://www.reddit.com/r/leagueoflegends/comments/r1x8lm/shadowbox_of_malphite_altered_the_original_art/"
YOUTUBE_SHORT = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
FACEBOOK_SHARE = "https://www.facebook.com/share/v/1FtYiBbiPb/"

# Instagram URLs that should produce Cobalt errors (not "file too large")
INSTAGRAM_UNAVAILABLE = "https://www.instagram.com/reel/DVJ6n17khYN/?igsh=MTN5azBxcWNzbXFuMg%3D%3D"
INSTAGRAM_AUTH_GATED = "https://www.instagram.com/reel/DRWyTq1k8_-/?igsh=MWZqc2NqOTF2dWN3cg%3D%3D"


# ── Warmup ───────────────────────────────────────────────────────────────────

class TestWarmup:
    """Verify the bot is online before running real tests."""

    @pytest.mark.timeout(300)
    async def test_bot_is_online(self, discord):
        """Send a supported URL and wait for the bot to respond.

        This doubles as a warmup probe: if the bot isn't deployed yet, we
        resend every 30s until we get a response or ~5 minutes elapse.
        """
        import asyncio

        response = None
        for attempt in range(10):
            sent = await discord.send_webhook_message(TWITTER_VIDEO)
            response = await discord.wait_for_bot_response(sent["id"], timeout=30)
            if response is not None:
                break
            await asyncio.sleep(2)

        assert response is not None, (
            "Bot did not respond after multiple attempts -- is it deployed and connected?"
        )
        assert response.attachments or response.embeds, (
            "Bot responded but with no attachments or embeds"
        )


# ── Happy-path tests ─────────────────────────────────────────────────────────

class TestHappyPath:
    """Test successful downloads from various providers."""

    @pytest.mark.timeout(60)
    async def test_twitter_video(self, discord):
        sent = await discord.send_webhook_message(TWITTER_VIDEO)
        response = await discord.wait_for_bot_response(sent["id"], timeout=45)
        assert response is not None, "No response for Twitter/X link"
        assert response.attachments, "Expected a file attachment for Twitter video"

    @pytest.mark.timeout(60)
    async def test_instagram_reel(self, discord):
        sent = await discord.send_webhook_message(INSTAGRAM_REEL)
        response = await discord.wait_for_bot_response(sent["id"], timeout=45)
        assert response is not None, "No response for Instagram reel"
        assert response.attachments, "Expected a file attachment for Instagram reel"

    @pytest.mark.timeout(180)
    async def test_reddit_needs_compression(self, discord):
        """A Reddit video that exceeds 10MB raw and needs compression."""
        sent = await discord.send_webhook_message(REDDIT_NEEDS_COMPRESSION)
        response = await discord.wait_for_bot_response(sent["id"], timeout=150)
        assert response is not None, "No response for Reddit link needing compression"
        assert response.attachments, "Expected a compressed file attachment"

    @pytest.mark.timeout(60)
    async def test_facebook_share_link(self, discord):
        """A Facebook share link should be resolved and downloaded."""
        sent = await discord.send_webhook_message(FACEBOOK_SHARE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=45)
        assert response is not None, "No response for Facebook share link"
        assert response.attachments, "Expected a file attachment for Facebook share video"

    @pytest.mark.timeout(60)
    async def test_instagram_multi_image(self, discord):
        """An Instagram post with multiple images (picker)."""
        sent = await discord.send_webhook_message(INSTAGRAM_MULTI_IMAGE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=45)
        assert response is not None, "No response for Instagram multi-image post"
        assert response.attachments or response.embeds, (
            "Expected attachments or embeds for multi-image post"
        )


# ── Error-handling tests ─────────────────────────────────────────────────────

class TestErrorHandling:
    """Verify the bot handles errors gracefully (no crash, no misleading messages)."""

    @pytest.mark.timeout(30)
    async def test_unavailable_instagram_reel(self, discord):
        """An Instagram reel that doesn't exist should NOT produce 'file too large'."""
        sent = await discord.send_webhook_message(INSTAGRAM_UNAVAILABLE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=20)
        if response is not None:
            assert "file too large" not in response.content.lower(), (
                "Bug regression: bot should NOT report 'file too large' for unavailable content"
            )

    @pytest.mark.timeout(30)
    async def test_auth_gated_instagram(self, discord):
        """Auth-gated Instagram content should fail gracefully."""
        sent = await discord.send_webhook_message(INSTAGRAM_AUTH_GATED)
        response = await discord.wait_for_bot_response(sent["id"], timeout=20)
        if response is not None:
            assert "file too large" not in response.content.lower(), (
                "Bug regression: bot should NOT report 'file too large' for auth-gated content"
            )

    @pytest.mark.timeout(25)
    async def test_unsupported_url_ignored(self, discord):
        """A URL from an unsupported provider should be silently ignored."""
        sent = await discord.send_webhook_message("https://example.com/video.mp4")
        response = await discord.wait_for_bot_response(sent["id"], timeout=15)
        assert response is None, "Bot should not respond to unsupported URLs"

    @pytest.mark.timeout(25)
    async def test_youtube_not_configured(self, discord):
        """YouTube is not a configured provider, bot should ignore it."""
        sent = await discord.send_webhook_message(YOUTUBE_SHORT)
        response = await discord.wait_for_bot_response(sent["id"], timeout=15)
        assert response is None, (
            "Bot should not respond to YouTube (not a configured provider)"
        )


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Misc edge-case scenarios."""

    @pytest.mark.timeout(60)
    async def test_message_with_text_and_link(self, discord):
        """A message containing both user text and a supported link."""
        sent = await discord.send_webhook_message(
            f"check this out! {TWITTER_VIDEO}"
        )
        response = await discord.wait_for_bot_response(sent["id"], timeout=45)
        assert response is not None, "No response for link embedded in text"
        assert response.attachments, "Expected a file attachment"

    @pytest.mark.timeout(25)
    async def test_plain_text_ignored(self, discord):
        """A message with no URL should be completely ignored."""
        sent = await discord.send_webhook_message("hello there, just chatting!")
        response = await discord.wait_for_bot_response(sent["id"], timeout=15)
        assert response is None, "Bot should not respond to plain text"
