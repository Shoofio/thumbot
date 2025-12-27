"""
Discord message handlers with async task queue
"""
import re
import asyncio
from typing import Optional
from dataclasses import dataclass

import discord

from thumbot.config import Config, load_providers
from thumbot.downloader import VideoDownloader
from thumbot.bot.embed import create_video_embed
from thumbot.utils.logger import get_logger
from thumbot.utils.metrics import track_message, track_link_detection

logger = get_logger("handlers")

# URL regex patterns
URL_PATTERN = re.compile(r'(https?://[^\s\)]+)', re.IGNORECASE)
# Markdown link pattern: [name](url)
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', re.IGNORECASE)


@dataclass
class DownloadTask:
    """Represents a download task in the queue"""
    url: str
    channel_id: str
    provider: str
    # User context for embed
    username: str
    avatar_url: str
    user_id: str
    user_text: Optional[str] = None  # Text with 🔗 link already formatted in position
    original_message: Optional[discord.Message] = None  # For deletion after success


class MessageHandler:
    """Handles Discord messages and manages download task queue"""
    
    def __init__(self, config: Config):
        self.config = config
        self.providers = load_providers(config)
        self.downloader = VideoDownloader(config)
        
        # Task queue for download jobs
        self._task_queue: asyncio.Queue[DownloadTask] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        
        logger.info(f"Loaded {len(self.providers)} providers")
        logger.info(f"Max concurrent downloads: {config.max_concurrent_downloads}")
    
    async def start_workers(self):
        """Start the download worker tasks"""
        if self._running:
            return
        
        self._running = True
        num_workers = self.config.max_concurrent_downloads
        
        for i in range(num_workers):
            worker = asyncio.create_task(self._download_worker(i))
            self._workers.append(worker)
        
        logger.info(f"Started {num_workers} download worker(s)")
    
    async def stop_workers(self):
        """Stop all worker tasks gracefully"""
        self._running = False
        
        # Cancel all workers
        for worker in self._workers:
            worker.cancel()
        
        # Wait for workers to finish
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        
        # Close downloader sessions
        await self.downloader.close()
        
        logger.info("Download workers stopped")
    
    async def _download_worker(self, worker_id: int):
        """Worker coroutine that processes download tasks from the queue"""
        logger.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Wait for a task with timeout (allows checking _running flag)
                try:
                    task = await asyncio.wait_for(
                        self._task_queue.get(), 
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                logger.debug(f"Worker {worker_id} processing: {task.url}")
                
                try:
                    # Create embed for this task
                    embed = create_video_embed(
                        username=task.username,
                        avatar_url=task.avatar_url,
                        original_url=task.url,
                        user_id=task.user_id,
                        user_text=task.user_text
                    )
                    
                    success = await self.downloader.process_url(
                        url=task.url,
                        channel_id=task.channel_id,
                        embed=embed
                    )
                    
                    if success:
                        logger.debug(f"Worker {worker_id} completed: {task.provider}")
                        
                        # Delete original message only after successful upload
                        if task.original_message:
                            try:
                                await task.original_message.delete()
                                logger.debug(f"Deleted original message from {task.username}")
                            except discord.Forbidden:
                                logger.warning(f"No permission to delete message in channel {task.channel_id}")
                            except discord.NotFound:
                                logger.debug("Original message already deleted")
                            except Exception as e:
                                logger.error(f"Failed to delete original message: {e}")
                    else:
                        logger.warning(f"Worker {worker_id} failed: {task.provider}")
                        
                except Exception as e:
                    logger.error(f"Worker {worker_id} error processing {task.url}: {e}")
                
                finally:
                    self._task_queue.task_done()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} unexpected error: {e}")
        
        logger.debug(f"Worker {worker_id} stopped")
    
    async def handle_message(self, message: discord.Message):
        """
        Handle incoming Discord message
        
        Args:
            message: Discord message object
        """
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Extract URL from message
        url = self._extract_url(message.content)
        has_link = url is not None
        
        # Track metrics
        track_message(has_link)
        
        if not url:
            return
        
        # Check if URL matches a supported provider
        provider, supported = self._check_provider(url)
        track_link_detection(provider, supported)
        
        if not supported:
            logger.debug(f"Unsupported provider: {provider}")
            return
        
        logger.info(f"Queueing {provider} link from {message.author}")
        
        # Extract user text with 🔗 link in position
        user_text = self._extract_user_text(message.content, url)
        
        # Add task to queue (non-blocking)
        task = DownloadTask(
            url=url,
            channel_id=str(message.channel.id),
            provider=provider,
            username=message.author.display_name,
            avatar_url=str(message.author.display_avatar.url),
            user_id=str(message.author.id),
            user_text=user_text,
            original_message=message  # Keep reference for deletion after success
        )
        await self._task_queue.put(task)
        
        queue_size = self._task_queue.qsize()
        if queue_size > 0:
            logger.debug(f"Queue size: {queue_size}")
    
    def _extract_url(self, content: str) -> Optional[str]:
        """Extract first URL from message content (handles both raw and markdown links)"""
        # First check for markdown link format [name](url)
        md_match = MARKDOWN_LINK_PATTERN.search(content)
        if md_match:
            return md_match.group(2)  # Return the URL part
        
        # Fall back to raw URL
        match = URL_PATTERN.search(content)
        return match.group(0) if match else None
    
    def _extract_user_text(self, content: str, url: str) -> Optional[str]:
        """Extract user's text, formatting depends on markdown vs raw URL"""
        text = content
        
        # Check for markdown link [name](url)
        md_match = MARKDOWN_LINK_PATTERN.search(content)
        if md_match:
            # Markdown link: replace with 🔗 name, add raw URL at bottom
            link_name = md_match.group(1)
            text = text.replace(md_match.group(0), f"🔗 {link_name}")
            
            # Clean up the text
            lines = [line.strip() for line in text.split('\n')]
            lines = [line for line in lines if line]
            text = '\n'.join(lines)
            
            # Add raw URL at bottom
            text = f"{text}\n\n{url}" if text else url
        else:
            # Raw URL: keep as-is, no changes
            lines = [line.strip() for line in text.split('\n')]
            lines = [line for line in lines if line]
            text = '\n'.join(lines)
        
        return text if text else None
    
    def _check_provider(self, url: str) -> tuple[str, bool]:
        """
        Check if URL matches a supported provider
        
        Returns:
            Tuple of (provider_name, is_supported)
        """
        for provider in self.providers:
            if provider in url:
                return provider, True
        
        # Try to extract domain as provider name
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain, False
        except Exception:
            return "unknown", False
    
    @property
    def queue_size(self) -> int:
        """Get current queue size"""
        return self._task_queue.qsize()
