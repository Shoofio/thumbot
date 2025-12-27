"""
Discord embed builder for video posts
"""
from urllib.parse import urlparse
from typing import Optional

import discord


# Platform colors
PLATFORM_COLORS = {
    "reddit": 0xFF4500,      # Reddit orange
    "instagram": 0xE1306C,   # Instagram pink
    "facebook": 0x1877F2,    # Facebook blue
    "fb.watch": 0x1877F2,    # Facebook blue
    "twitter.com": 0x1DA1F2, # Twitter blue
    "x.com": 0x1DA1F2,       # Twitter blue (same for X)
}

DEFAULT_COLOR = 0x5865F2  # Discord blurple


def get_platform_color(url: str) -> int:
    """Get embed color based on URL platform"""
    url_lower = url.lower()
    for platform, color in PLATFORM_COLORS.items():
        if platform in url_lower:
            return color
    return DEFAULT_COLOR


def create_video_embed(
    username: str,
    avatar_url: str,
    original_url: str,
    user_id: str,
    user_text: Optional[str] = None
) -> discord.Embed:
    """
    Create a Discord embed for a video post
    
    Args:
        username: Display name of the user who posted
        avatar_url: URL to user's avatar
        original_url: Original video URL
        user_id: Discord user ID for profile link
        user_text: User's text with 🔗 link already formatted in position
    
    Returns:
        discord.Embed ready to send
    """
    # Get platform-specific color
    color = get_platform_color(original_url)
    
    # Create embed with just color (no title)
    embed = discord.Embed(color=color)
    
    # Set author with avatar
    embed.set_author(
        name=username,
        icon_url=avatar_url
    )
    
    # Description is the user's text with 🔗 link already formatted
    if user_text:
        embed.description = user_text
    
    # Field with clickable mention for who posted
    # embed.add_field(name="Posted by", value=f"<@{user_id}>", inline=True)
    
    return embed

