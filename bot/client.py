"""
Discord bot client setup
"""
import discord
from discord.ext import commands

from thumbot.utils.logger import get_logger

logger = get_logger("bot")


def create_bot() -> commands.Bot:
    """Create and configure the Discord bot"""
    
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    
    bot = commands.Bot(
        command_prefix="!",  # Not really used, but required
        intents=intents,
        help_command=None,  # We don't need help command
    )
    
    return bot

