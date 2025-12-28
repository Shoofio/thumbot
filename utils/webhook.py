"""
Discord webhook utilities for user impersonation
"""
import discord
from typing import Optional

from thumbot.utils.logger import get_logger

logger = get_logger("webhook")

# Cache webhooks per channel to avoid repeated API calls
_webhook_cache: dict[int, discord.Webhook] = {}

WEBHOOK_NAME = "ThumbBot"


async def get_or_create_webhook(
    channel: discord.abc.GuildChannel,
) -> Optional[discord.Webhook]:
    """
    Get or create a webhook for the channel.
    
    Args:
        channel: Discord channel (must be TextChannel, not Thread)
    
    Returns:
        Webhook object or None if not supported/no permission
    """
    # Webhooks only work in TextChannels, not Threads
    if not isinstance(channel, discord.TextChannel):
        logger.debug(f"Channel {channel.id} is not a TextChannel, webhooks not supported")
        return None
    
    # Check cache first
    if channel.id in _webhook_cache:
        webhook = _webhook_cache[channel.id]
        # Verify webhook still exists
        try:
            await webhook.fetch()
            return webhook
        except (discord.NotFound, discord.HTTPException):
            # Webhook was deleted, remove from cache
            del _webhook_cache[channel.id]
    
    try:
        # Get existing webhooks
        webhooks = await channel.webhooks()
        
        # Look for our webhook
        webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME)
        
        if webhook is None:
            # Create new webhook
            logger.info(f"Creating webhook in channel {channel.id}")
            webhook = await channel.create_webhook(name=WEBHOOK_NAME)
        
        # Cache it
        _webhook_cache[channel.id] = webhook
        return webhook
        
    except discord.Forbidden:
        logger.warning(f"No permission to manage webhooks in channel {channel.id}")
        return None
    except discord.HTTPException as e:
        logger.error(f"Failed to get/create webhook: {e}")
        return None


async def send_via_webhook(
    webhook: discord.Webhook,
    username: str,
    avatar_url: str,
    files: list[discord.File],
    embed: Optional[discord.Embed] = None,
    content: str = "",
) -> Optional[discord.Message]:
    """
    Send a message via webhook, impersonating a user.
    
    Args:
        webhook: Discord webhook to send through
        username: Display name to use (will have suffix appended)
        avatar_url: Avatar URL for the message
        files: List of discord.File objects to attach
        embed: Optional embed to include
        content: Optional text content
    
    Returns:
        The sent message, or None on failure
    """
    try:
        return await webhook.send(
            content=content,
            username=username,
            avatar_url=avatar_url,
            files=files,
            embeds=[embed] if embed else [],
            wait=True,  # Required to get the message object back
        )
    except discord.HTTPException as e:
        logger.error(f"Failed to send via webhook: {e}")
        return None


def clear_webhook_cache():
    """Clear the webhook cache (useful for cleanup)"""
    _webhook_cache.clear()

