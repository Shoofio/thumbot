"""
ThumbBot - Discord bot for video downloading via Cobalt
"""
import asyncio
import os
import signal
import sys

# Load .env file before importing config
from dotenv import load_dotenv
load_dotenv()

from thumbot.config import config
from thumbot.bot import create_bot, MessageHandler
from thumbot.utils.logger import get_logger, setup_logger
from thumbot.utils.metrics import start_metrics_server
from thumbot.utils.tracing import init_tracing

logger = get_logger("main")


def print_startup_banner():
    """Print startup configuration"""
    print("=" * 60)
    print("  THUMBBOT - Video Downloader Bot")
    print("=" * 60)
    print(f"  Cobalt URL:         {config.cobalt_url}")
    print(f"  Preferred Quality:  {config.preferred_quality.value}")
    print(f"  Log Level:          {config.log_level}")
    print(f"  Picker Behavior:    {config.picker_behavior.value}")
    print(f"  Max File Size:      {config.max_file_size_mb}MB")
    print(f"  Temp Directory:     {config.temp_dir}")
    print(f"  Auto Cleanup:       {config.auto_cleanup}")
    print(f"  Concurrent DLs:     {config.max_concurrent_downloads}")
    print(f"  Download Timeout:   {config.download_timeout}s")
    print(f"  Providers File:     {config.providers_file}")
    
    # Tracing
    otel_status = config.otel_endpoint if config.otel_endpoint else "disabled"
    print(f"  OTEL Endpoint:      {otel_status}")
    
    # Show token preview
    token = config.discord_token
    token_preview = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
    print(f"  Discord Token:      {token_preview}")
    print("=" * 60)


async def main():
    """Main entry point"""
    
    # Setup logging
    setup_logger(config.log_level)
    
    # Print startup info
    print_startup_banner()
    
    # Initialize tracing
    init_tracing(
        service_name="thumbot",
        otel_endpoint=config.otel_endpoint,
        enabled=config.otel_enabled
    )
    
    # Start metrics server
    metrics_port = int(os.getenv("METRICS_PORT", "8002"))
    start_metrics_server(metrics_port)
    logger.info(f"Metrics available at http://localhost:{metrics_port}/metrics")
    
    # Create bot and handler
    bot = create_bot()
    handler = MessageHandler(config)
    
    @bot.event
    async def on_ready():
        logger.success(f"Bot logged in as {bot.user}")
        logger.info(f"Connected to {len(bot.guilds)} guild(s)")
        for guild in bot.guilds:
            logger.info(f"  - {guild.name} ({guild.member_count} members)")
        
        # Start download workers
        await handler.start_workers()
    
    @bot.event
    async def on_message(message):
        await handler.handle_message(message)
    
    @bot.event
    async def on_guild_join(guild):
        logger.info(f"Joined guild: {guild.name}")
    
    @bot.event
    async def on_guild_remove(guild):
        logger.info(f"Left guild: {guild.name}")
    
    # Graceful shutdown
    async def shutdown():
        logger.info("Shutting down...")
        await handler.stop_workers()
        await bot.close()
    
    # Signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run the bot
    try:
        logger.info("Connecting to Discord...")
        await bot.start(config.discord_token)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)
    finally:
        if not bot.is_closed():
            await handler.stop_workers()
            await bot.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
