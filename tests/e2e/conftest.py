"""
E2E test fixtures and Discord API helpers.

Requires env vars:
  DISCORD_E2E_BOT_TOKEN   - bot token for reading channel messages
  DISCORD_E2E_WEBHOOK_URL - webhook URL for sending test messages
  DISCORD_E2E_CHANNEL_ID  - channel ID where the bot listens
"""

import os
import asyncio
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


class DiscordE2EClient:
    """Lightweight Discord REST client for e2e test interactions."""

    def __init__(self, bot_token: str, webhook_url: str, channel_id: str):
        self.bot_token = bot_token
        self.webhook_url = webhook_url
        self.channel_id = channel_id
        self._session: aiohttp.ClientSession | None = None
        self._messages_to_cleanup: list[str] = []

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bot {self.bot_token}"},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def send_webhook_message(self, content: str, *, wait: bool = True) -> dict:
        """Send a message via the webhook (appears as a 'user' message for the bot)."""
        session = await self._get_session()
        url = f"{self.webhook_url}?wait=true" if wait else self.webhook_url
        async with session.post(url, json={"content": content}) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._messages_to_cleanup.append(data["id"])
            return data

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
                )
                for m in raw
            ]

    async def wait_for_bot_response(
        self,
        after_message_id: str,
        *,
        timeout: float = 180,
        poll_interval: float = 3,
    ) -> DiscordMessage | None:
        """Poll the channel until a bot message appears after the given message ID."""
        elapsed = 0.0
        while elapsed < timeout:
            messages = await self.get_channel_messages(after=after_message_id)
            bot_msgs = [m for m in messages if m.author_bot]
            if bot_msgs:
                for m in bot_msgs:
                    self._messages_to_cleanup.append(m.id)
                return bot_msgs[0]
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        return None

    async def delete_message(self, message_id: str) -> None:
        session = await self._get_session()
        url = f"{DISCORD_API}/channels/{self.channel_id}/messages/{message_id}"
        async with session.delete(url) as resp:
            if resp.status not in (200, 204, 404):
                resp.raise_for_status()

    async def cleanup(self) -> None:
        """Delete all messages created during the test run."""
        for msg_id in self._messages_to_cleanup:
            try:
                await self.delete_message(msg_id)
                await asyncio.sleep(0.5)
            except Exception:
                pass
        self._messages_to_cleanup.clear()

    async def close(self) -> None:
        await self.cleanup()
        if self._session and not self._session.closed:
            await self._session.close()


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set -- skipping e2e tests")
    return val


@pytest_asyncio.fixture
async def discord() -> DiscordE2EClient:
    client = DiscordE2EClient(
        bot_token=_require_env("DISCORD_E2E_BOT_TOKEN"),
        webhook_url=_require_env("DISCORD_E2E_WEBHOOK_URL"),
        channel_id=_require_env("DISCORD_E2E_CHANNEL_ID"),
    )
    yield client
    await client.close()
