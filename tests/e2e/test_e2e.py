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
# A reel ID that doesn't exist (mistyped) — IG returns the standard "post not
# found" page; bot should react failure rather than upload anything.
INSTAGRAM_DELETED = "https://www.instagram.com/reel/DRWyq1k8_-"
# An age/sensitive-restricted IG photo. Requires the cookie-authenticated
# mobile-API path in Cobalt (anonymous embed fallback can't see it).
INSTAGRAM_RESTRICTED_PHOTO = "https://www.instagram.com/p/CNjarYuszEZ/"
# An auth-gated IG photo post (/p/, single image, not publicly embeddable) —
# the exact shape that used to fail before the Cobalt fork added x-ig-app-id
# to the mobile-API headers.
INSTAGRAM_AUTH_GATED_PHOTO = "https://www.instagram.com/p/DbfTo5Vyauo/"
# Reddit gallery (2 images) and a single i.redd.it image — both need the
# Cobalt fork's reddit_web cookie + gallery/image extraction.
REDDIT_GALLERY = "https://www.reddit.com/r/EscapefromTarkov/s/VLja5GqcIt"
REDDIT_IMAGE = "https://www.reddit.com/r/NuPhy/comments/1v92i8o/nuphy_wh80_caps_lock_led/"


# ── Warmup ───────────────────────────────────────────────────────────────────

class TestWarmup:
    """Verify the bot is online before running real tests."""

    @pytest.mark.timeout(180)
    async def test_bot_is_online(self, discord):
        """Send a supported URL and wait for the bot to respond.

        This doubles as a warmup probe: if the bot isn't deployed yet, we
        resend every 15s until we get a response or ~3 minutes elapse.
        """
        import asyncio

        response = None
        for attempt in range(10):
            sent = await discord.send_webhook_message(TWITTER_VIDEO)
            response = await discord.wait_for_bot_response(sent["id"], timeout=15)
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

    @pytest.mark.timeout(30)
    async def test_twitter_video(self, discord):
        sent = await discord.send_webhook_message(TWITTER_VIDEO)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for Twitter/X link"
        assert response.attachments, "Expected a file attachment for Twitter video"

    @pytest.mark.timeout(30)
    async def test_instagram_reel(self, discord):
        sent = await discord.send_webhook_message(INSTAGRAM_REEL)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for Instagram reel"
        assert response.attachments, "Expected a file attachment for Instagram reel"

    @pytest.mark.timeout(180)
    async def test_reddit_needs_compression(self, discord):
        """A Reddit video that exceeds 10MB raw and needs compression."""
        sent = await discord.send_webhook_message(REDDIT_NEEDS_COMPRESSION)
        response = await discord.wait_for_bot_response(sent["id"], timeout=150)
        assert response is not None, "No response for Reddit link needing compression"
        assert response.attachments, "Expected a compressed file attachment"

    @pytest.mark.timeout(30)
    async def test_facebook_share_link(self, discord):
        """A Facebook share link should be resolved and downloaded."""
        sent = await discord.send_webhook_message(FACEBOOK_SHARE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for Facebook share link"
        assert response.attachments, "Expected a file attachment for Facebook share video"

    @pytest.mark.timeout(30)
    async def test_instagram_multi_image(self, discord):
        """An Instagram post with multiple images (picker)."""
        sent = await discord.send_webhook_message(INSTAGRAM_MULTI_IMAGE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for Instagram multi-image post"
        assert response.attachments or response.embeds, (
            "Expected attachments or embeds for multi-image post"
        )

    @pytest.mark.timeout(30)
    async def test_instagram_auth_gated_photo(self, discord):
        """An auth-gated Instagram photo post (/p/, not a reel). Needs Cobalt's
        cookie-authenticated mobile-API path — this shape was 0/7 before the
        x-ig-app-id fork fix."""
        sent = await discord.send_webhook_message(INSTAGRAM_AUTH_GATED_PHOTO)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, (
            "No response for auth-gated IG photo — cookie or x-ig-app-id path broken?"
        )
        assert response.attachments, (
            "Expected an image attachment for auth-gated IG photo post"
        )

    @pytest.mark.timeout(40)
    async def test_reddit_gallery_uploads_all_images(self, discord):
        """A Reddit gallery post → Cobalt picker → all images uploaded
        (PICKER_BEHAVIOR=all). Needs the fork's reddit_web cookie and
        gallery extraction."""
        sent = await discord.send_webhook_message(REDDIT_GALLERY)
        response = await discord.wait_for_bot_response(sent["id"], timeout=35)
        assert response is not None, (
            "No response for Reddit gallery — reddit_web cookie expired or gallery path broken?"
        )
        assert len(response.attachments) >= 2, (
            f"Gallery has 2 images but got {len(response.attachments)} attachment(s)"
        )

    @pytest.mark.timeout(30)
    async def test_reddit_image(self, discord):
        """A single i.redd.it image post. Needs the fork's reddit_web cookie
        and post_hint:image extraction."""
        sent = await discord.send_webhook_message(REDDIT_IMAGE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, (
            "No response for Reddit image — reddit_web cookie expired or image path broken?"
        )
        assert response.attachments, (
            "Expected an image attachment for Reddit image post"
        )


# ── Error-handling tests ─────────────────────────────────────────────────────

class TestErrorHandling:
    """Verify the bot handles errors gracefully (no crash, no misleading messages)."""

    @pytest.mark.timeout(25)
    async def test_unavailable_instagram_reel(self, discord):
        """An Instagram reel that doesn't exist should NOT produce 'file too large'."""
        sent = await discord.send_webhook_message(INSTAGRAM_UNAVAILABLE)
        response = await discord.wait_for_bot_response(sent["id"], timeout=20)
        if response is not None:
            assert "file too large" not in response.content.lower(), (
                "Bug regression: bot should NOT report 'file too large' for unavailable content"
            )

    @pytest.mark.timeout(30)
    async def test_auth_gated_instagram_with_cookies(self, discord):
        """An auth-gated Instagram reel should now upload successfully — the
        cobalt deployment carries IG session cookies, so Cobalt can fetch
        restricted content. (Pre-cookies this used to fail.)"""
        sent = await discord.send_webhook_message(INSTAGRAM_AUTH_GATED)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, (
            "No response for auth-gated reel — Cobalt cookies missing or expired?"
        )
        assert response.attachments, (
            "Auth-gated reel should upload an attachment when cobalt cookies are configured"
        )

    @pytest.mark.timeout(35)
    async def test_deleted_instagram_reel_reacts_failure(self, discord):
        """A reel URL that doesn't exist should produce a failure reaction
        on the user's message, not an upload."""
        sent = await discord.send_webhook_message(INSTAGRAM_DELETED)
        # Wait for the failure reaction first — that's the signal the bot
        # tried + failed. Then a quick check confirms no upload sneaked in.
        reactions = await discord.wait_for_reaction(sent["id"], timeout=25)
        assert reactions, "Bot should react with :thumbot_fail: (or ❌) on failure"
        response = await discord.wait_for_bot_response(sent["id"], timeout=3)
        assert response is None or not response.attachments, (
            "404 URL should not produce an attachment upload"
        )

    @pytest.mark.timeout(30)
    async def test_restricted_instagram_photo_uploads(self, discord):
        """A restricted IG photo must succeed on the first attempt via the
        cookie-authenticated mobile-API path — no retry layer exists anymore
        (the old flakiness was a deterministic missing-header bug, since
        fixed in the Cobalt fork)."""
        sent = await discord.send_webhook_message(INSTAGRAM_RESTRICTED_PHOTO)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, (
            "No response for restricted photo — cobalt cookies may have expired"
        )
        assert response.attachments, (
            "Expected an upload for the restricted photo"
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

    @pytest.mark.timeout(30)
    async def test_message_with_text_and_link(self, discord):
        """A message containing both user text and a supported link."""
        sent = await discord.send_webhook_message(
            f"check this out! {TWITTER_VIDEO}"
        )
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for link embedded in text"
        assert response.attachments, "Expected a file attachment"

    @pytest.mark.timeout(25)
    async def test_plain_text_ignored(self, discord):
        """A message with no URL should be completely ignored."""
        sent = await discord.send_webhook_message("hello there, just chatting!")
        response = await discord.wait_for_bot_response(sent["id"], timeout=15)
        assert response is None, "Bot should not respond to plain text"


# ── Spoilers ─────────────────────────────────────────────────────────────────

class TestSpoilers:
    """When the user wraps the URL in Discord's ||...|| spoiler markdown,
    uploaded attachments should be SPOILER_-prefixed so Discord blurs them."""

    @pytest.mark.timeout(30)
    async def test_spoiler_marked_url_uploads_with_spoiler_prefix(self, discord):
        sent = await discord.send_webhook_message(f"||{TWITTER_VIDEO}||")
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for spoiler-marked URL"
        assert response.attachments, "Expected an upload for spoiler-marked URL"
        for att in response.attachments:
            assert att.get("filename", "").startswith("SPOILER_"), (
                f"Spoiler-marked URL produced un-spoilered attachment: "
                f"{att.get('filename')!r}"
            )

    @pytest.mark.timeout(30)
    async def test_unmarked_url_does_not_get_spoiler_prefix(self, discord):
        """Counter-control: a normal URL shouldn't accidentally get SPOILER_."""
        sent = await discord.send_webhook_message(TWITTER_VIDEO)
        response = await discord.wait_for_bot_response(sent["id"], timeout=25)
        assert response is not None, "No response for plain URL"
        assert response.attachments, "Expected an upload for plain URL"
        for att in response.attachments:
            assert not att.get("filename", "").startswith("SPOILER_"), (
                f"Plain URL got an unexpected SPOILER_ prefix: "
                f"{att.get('filename')!r}"
            )
