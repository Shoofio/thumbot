"""
Discord file upload functionality (async)
Supports both direct API uploads and webhook-based impersonation
"""
import os
import json
import aiohttp
import aiofiles
from dataclasses import dataclass
from typing import Optional, Any

import discord

from thumbot.utils.logger import get_logger
from thumbot.utils.metrics import track_discord_upload
from thumbot.utils.webhook import get_or_create_webhook, send_via_webhook
from thumbot.downloader.exceptions import UploadError

logger = get_logger("upload")

DISCORD_API_BASE = "https://discord.com/api/v10"


@dataclass
class AuthorContext:
    """Author information for webhook impersonation"""
    username: str
    avatar_url: str
    suffix: str = " (ThumbBot)"
    
    @property
    def display_name(self) -> str:
        """Username with suffix for webhook display"""
        return f"{self.username}{self.suffix}"


def embed_to_dict(embed: Any) -> Optional[dict]:
    """Convert discord.Embed to dict for API payload"""
    if embed is None:
        logger.debug("No embed provided")
        return None
    # discord.Embed has a to_dict() method
    if hasattr(embed, "to_dict"):
        result = embed.to_dict()
        logger.debug(f"Embed dict: {result}")
        return result
    logger.debug(f"Embed has no to_dict: {type(embed)}")
    return None


async def upload_to_discord(
    channel_id: str, 
    file_path: str, 
    token: str,
    content: str = "",
    embed: Any = None
) -> Optional[dict]:
    """
    Upload a single file to Discord (async)
    
    Args:
        channel_id: Discord channel ID
        file_path: Path to the file to upload
        token: Discord bot token
        content: Optional message content
        embed: Optional discord.Embed object
    
    Returns:
        Response JSON or None on failure
    """
    upload_url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    filename = os.path.basename(file_path)
    
    headers = {"Authorization": f"Bot {token}"}
    
    try:
        # Read file asynchronously
        async with aiofiles.open(file_path, "rb") as f:
            file_data = await f.read()
        
        # Build payload
        payload: dict = {
            "content": content,
            "attachments": [{"id": 0, "filename": filename}]
        }
        
        # Add embed if provided
        embed_dict = embed_to_dict(embed)
        if embed_dict:
            payload["embeds"] = [embed_dict]
        
        # Prepare multipart form data
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        form.add_field(
            "files[0]",
            file_data,
            filename=filename,
            content_type="application/octet-stream"
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, headers=headers, data=form) as response:
                response.raise_for_status()
                track_discord_upload("success")
                return await response.json()
            
    except aiohttp.ClientError as e:
        logger.error(f"Failed to upload file: {e}")
        track_discord_upload("error")
        raise UploadError(f"Discord upload failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error uploading file: {e}")
        track_discord_upload("error")
        raise UploadError(f"Discord upload failed: {e}")


async def upload_multiple_to_discord(
    channel_id: str, 
    file_paths: list[str], 
    token: str,
    content: str = "",
    embed: Any = None
) -> Optional[dict]:
    """
    Upload multiple files to Discord in a single message (max 10 files, async)
    
    Args:
        channel_id: Discord channel ID
        file_paths: List of file paths to upload
        token: Discord bot token
        content: Optional message content
        embed: Optional discord.Embed object
    
    Returns:
        Response JSON or None on failure
    """
    if not file_paths:
        return None
    
    upload_url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    
    # Discord allows max 10 attachments per message
    if len(file_paths) > 10:
        logger.warning(f"Discord limit: Uploading 10/{len(file_paths)} files")
        file_paths = file_paths[:10]
    
    headers = {"Authorization": f"Bot {token}"}
    
    try:
        # Read all files asynchronously
        files_data = []
        for file_path in file_paths:
            async with aiofiles.open(file_path, "rb") as f:
                files_data.append((os.path.basename(file_path), await f.read()))
        
        # Build attachments list
        attachments = [
            {"id": i, "filename": filename}
            for i, (filename, _) in enumerate(files_data)
        ]
        
        # Build payload
        payload: dict = {
            "content": content,
            "attachments": attachments
        }
        
        # Add embed if provided
        embed_dict = embed_to_dict(embed)
        if embed_dict:
            payload["embeds"] = [embed_dict]
        
        # Prepare multipart form data
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        
        for i, (filename, data) in enumerate(files_data):
            form.add_field(
                f"files[{i}]",
                data,
                filename=filename,
                content_type="application/octet-stream"
            )
        
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, headers=headers, data=form) as response:
                response.raise_for_status()
                track_discord_upload("success")
                return await response.json()
        
    except aiohttp.ClientError as e:
        logger.error(f"Failed to upload multiple files: {e}")
        track_discord_upload("error")
        raise UploadError(f"Discord multi-upload failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error uploading files: {e}")
        track_discord_upload("error")
        raise UploadError(f"Discord multi-upload failed: {e}")


async def upload_via_webhook(
    channel: discord.abc.GuildChannel,
    file_paths: list[str],
    author: AuthorContext,
    embed: Any = None,
    content: str = "",
) -> Optional[discord.Message]:
    """
    Upload files via webhook, impersonating the original author.
    Falls back to regular channel.send() if webhooks unavailable.
    
    Args:
        channel: Discord channel object
        file_paths: List of file paths to upload
        author: Author context for impersonation
        embed: Optional discord.Embed
        content: Optional message content
    
    Returns:
        The sent message, or None on failure
    """
    if not file_paths:
        return None
    
    # Limit to 10 files per Discord's limit
    if len(file_paths) > 10:
        logger.warning(f"Discord limit: Uploading 10/{len(file_paths)} files")
        file_paths = file_paths[:10]
    
    # Create discord.File objects
    files = []
    for path in file_paths:
        try:
            files.append(discord.File(path))
        except Exception as e:
            logger.error(f"Failed to create File from {path}: {e}")
    
    if not files:
        track_discord_upload("error")
        raise UploadError("No valid files to upload")
    
    try:
        # Try webhook first
        webhook = await get_or_create_webhook(channel)
        
        if webhook:
            logger.debug(f"Uploading via webhook as '{author.display_name}'")
            message = await send_via_webhook(
                webhook=webhook,
                username=author.display_name,
                avatar_url=author.avatar_url,
                files=files,
                embed=embed,
                content=content,
            )
            
            if message:
                track_discord_upload("success")
                logger.info(f"Uploaded {len(file_paths)} file(s) via webhook")
                return message
            else:
                logger.warning("Webhook send failed, falling back to regular send")
        
        # Fallback: regular channel.send (for threads or permission issues)
        logger.debug("Using fallback channel.send()")
        
        # Need to recreate files since they were consumed
        files = [discord.File(path) for path in file_paths]
        
        message = await channel.send(
            content=content,
            files=files,
            embed=embed,
        )
        track_discord_upload("success")
        logger.info(f"Uploaded {len(file_paths)} file(s) via channel.send()")
        return message
        
    except discord.Forbidden as e:
        logger.error(f"No permission to send in channel: {e}")
        track_discord_upload("error")
        raise UploadError(f"No permission to send: {e}")
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP error: {e}")
        track_discord_upload("error")
        raise UploadError(f"Discord error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error uploading: {e}")
        track_discord_upload("error")
        raise UploadError(f"Upload failed: {e}")
