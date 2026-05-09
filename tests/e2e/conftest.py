"""
E2E test fixtures and Discord API helpers.

Requires env vars:
  DISCORD_E2E_BOT_TOKEN   - bot token for reading channel messages
  DISCORD_E2E_WEBHOOK_URL - webhook URL for sending test messages
  DISCORD_E2E_CHANNEL_ID  - channel ID where the bot listens
"""

import os
import json
import asyncio
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass

import aiohttp
import pytest
import pytest_asyncio

DISCORD_API = "https://discord.com/api/v10"


@dataclass
class DiscordMessage:
    id: str
    author_id: str
    author_bot: bool
    content: str
    attachments: list
    embeds: list
    reactions: list


class DiscordE2EClient:
    """Lightweight Discord REST client for e2e test interactions."""

    def __init__(self, bot_token: str, webhook_url: str, channel_id: str):
        self.bot_token = bot_token
        self.webhook_url = webhook_url
        self.channel_id = channel_id
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bot {self.bot_token}"},
            )
        return self._session

    async def send_webhook_message(self, content: str, *, wait: bool = True) -> dict:
        """Send a message via the webhook (appears as a 'user' message for the bot)."""
        session = await self._get_session()
        url = f"{self.webhook_url}?wait=true" if wait else self.webhook_url
        async with session.post(url, json={"content": content}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_channel_messages(
        self, *, after: str | None = None, limit: int = 20
    ) -> list[DiscordMessage]:
        """Fetch recent messages from the e2e channel."""
        session = await self._get_session()
        params: dict = {"limit": limit}
        if after:
            params["after"] = after
        url = f"{DISCORD_API}/channels/{self.channel_id}/messages"
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            raw = await resp.json()
            return [
                DiscordMessage(
                    id=m["id"],
                    author_id=m["author"]["id"],
                    author_bot=m["author"].get("bot", False),
                    content=m.get("content", ""),
                    attachments=m.get("attachments", []),
                    embeds=m.get("embeds", []),
                    reactions=m.get("reactions", []),
                )
                for m in raw
            ]

    async def get_message(self, message_id: str) -> DiscordMessage:
        """Fetch a single message by ID (so we can inspect reactions on it)."""
        session = await self._get_session()
        url = f"{DISCORD_API}/channels/{self.channel_id}/messages/{message_id}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            m = await resp.json()
            return DiscordMessage(
                id=m["id"],
                author_id=m["author"]["id"],
                author_bot=m["author"].get("bot", False),
                content=m.get("content", ""),
                attachments=m.get("attachments", []),
                embeds=m.get("embeds", []),
                reactions=m.get("reactions", []),
            )

    async def wait_for_reaction(
        self,
        message_id: str,
        *,
        timeout: float = 30,
        poll_interval: float = 1.5,
    ) -> list:
        """Poll a specific message until it has at least one reaction (or timeout)."""
        elapsed = 0.0
        while elapsed < timeout:
            try:
                msg = await self.get_message(message_id)
            except aiohttp.ClientResponseError:
                # Webhook messages can be deleted by the bot on success; treat as no reaction.
                return []
            if msg.reactions:
                return msg.reactions
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return []

    async def wait_for_bot_response(
        self,
        after_message_id: str,
        *,
        timeout: float = 180,
        poll_interval: float = 1.5,
    ) -> DiscordMessage | None:
        """Poll the channel until a bot message appears after the given message ID."""
        elapsed = 0.0
        while elapsed < timeout:
            messages = await self.get_channel_messages(after=after_message_id)
            bot_msgs = [m for m in messages if m.author_bot]
            if bot_msgs:
                return bot_msgs[0]
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set -- skipping e2e tests")
    return val


def _run_info() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sha = os.environ.get("GITHUB_SHA", "local")[:7]
    pr = os.environ.get("GITHUB_PR_NUMBER", os.environ.get("GITHUB_REF", "manual"))
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    return f"PR: {pr} | SHA: {sha} | Run: {run_id} | {ts}"


def _send_webhook_sync(webhook_url: str, content: str):
    """Send a webhook message synchronously (for session hooks)."""
    try:
        subprocess.run(
            ["curl", "-s", "-X", "POST", webhook_url,
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"content": content})],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass


def pytest_sessionstart(session):
    webhook_url = os.environ.get("DISCORD_E2E_WEBHOOK_URL")
    if webhook_url:
        info = _run_info()
        _send_webhook_sync(
            webhook_url,
            f"```\n{'=' * 60}\n  TEST START  {info}\n{'=' * 60}\n```",
        )


def pytest_sessionfinish(session, exitstatus):
    webhook_url = os.environ.get("DISCORD_E2E_WEBHOOK_URL")
    if webhook_url:
        info = _run_info()
        status = "PASSED" if exitstatus == 0 else "FAILED"
        _send_webhook_sync(
            webhook_url,
            f"```\n{'=' * 60}\n  TEST END [{status}]  {info}\n{'=' * 60}\n```",
        )


@pytest_asyncio.fixture
async def discord():
    client = DiscordE2EClient(
        bot_token=_require_env("DISCORD_E2E_BOT_TOKEN"),
        webhook_url=_require_env("DISCORD_E2E_WEBHOOK_URL"),
        channel_id=_require_env("DISCORD_E2E_CHANNEL_ID"),
    )
    yield client
    await client.close()
