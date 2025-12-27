"""
Discord file upload functionality (async)
"""
import os
import json
import aiohttp
import aiofiles
from typing import Optional, Any

from thumbot.utils.logger import get_logger
from thumbot.utils.metrics import track_discord_upload
from thumbot.downloader.exceptions import UploadError

logger = get_logger("upload")

DISCORD_API_BASE = "https://discord.com/api/v10"


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
