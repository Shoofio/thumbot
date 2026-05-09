"""
Video download and processing logic (async) with quality fallback and compression
"""
import os
import aiohttp
import aiofiles
from urllib.parse import urlparse
from typing import Optional

from thumbot.config import Config, PickerBehavior, VideoQuality
from thumbot.utils.logger import get_logger
from thumbot.utils.metrics import MetricsContext
from thumbot.utils.tracing import trace_span, add_span_attributes, add_span_event
from thumbot.downloader.cobalt import CobaltClient
from thumbot.downloader.upload import upload_to_discord, upload_multiple_to_discord
from thumbot.downloader.compress import compress_video
from thumbot.downloader.exceptions import FileTooLargeError, CobaltError, DownloadError

logger = get_logger("download")


# Cobalt error codes where retrying at lower qualities won't help.
# Bail immediately and surface the real reason instead of letting fallback
# masking errors win.
TERMINAL_COBALT_CODES = {
    "error.api.fetch.empty",
    "error.api.fetch.fail",
    "error.api.content.post.private",
    "error.api.content.post.unavailable",
    "error.api.content.video.unavailable",
    "error.api.link.unsupported",
    "error.api.link.invalid",
    "error.api.service.disabled",
}


class VideoDownloader:
    """Handles video downloads via Cobalt and uploads to Discord (async)"""
    
    def __init__(self, config: Config):
        self.config = config
        self.cobalt = CobaltClient(config.cobalt_url, timeout=config.download_timeout)
        self._http_session: Optional[aiohttp.ClientSession] = None
        
        # Ensure temp directory exists
        os.makedirs(config.temp_dir, exist_ok=True)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session for downloads"""
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.download_timeout)
            self._http_session = aiohttp.ClientSession(
                timeout=timeout,
                headers={'User-Agent': 'ThumbBot/2.0'}
            )
        return self._http_session
    
    async def close(self):
        """Close all sessions"""
        await self.cobalt.close()
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    async def _resolve_facebook_share_url(self, url: str) -> str:
        """Resolve Facebook share URLs by following redirects to get the actual content URL."""
        if "facebook.com/share/" not in url:
            return url

        try:
            logger.debug(f"Resolving Facebook share URL: {url}")
            session = await self._get_session()
            async with session.get(url, allow_redirects=True) as response:
                resolved = str(response.url)
                if resolved != url:
                    logger.info(f"Resolved Facebook share URL: {url} -> {resolved}")
                return resolved
        except Exception as e:
            logger.warning(f"Failed to resolve Facebook share URL, using original: {e}")
            return url

    async def process_url(self, url: str, channel_id: str, embed=None) -> bool:
        """
        Process a video URL - download via Cobalt and upload to Discord.

        Returns True if uploaded, False on any failure.
        """
        file_paths = []

        async with trace_span("process_url", {"url": url, "channel_id": channel_id}) as span:
            try:
                logger.info(f"Processing video request: {url}")

                # Resolve Facebook share URLs to actual content URLs
                original_url = url
                url = await self._resolve_facebook_share_url(url)
                if url != original_url:
                    add_span_attributes(resolved_url=url)

                # Get video with quality fallback
                with MetricsContext("download"):
                    result = await self._download_with_quality_fallback(url)

                    if result["type"] == "single":
                        file_paths = [result["file_path"]]
                    elif result["type"] == "picker":
                        file_paths = result["file_paths"]
                    else:
                        raise CobaltError(f"Unknown result type: {result.get('type')}")

                span.set_attribute("file_count", len(file_paths))

                # Upload to Discord
                if file_paths:
                    await self._upload_files(channel_id, file_paths, embed)
                    logger.success(f"Uploaded {len(file_paths)} file(s) to Discord")
                    span.add_event("upload_complete", {"files": len(file_paths)})

                return True

            except FileTooLargeError as e:
                logger.error(f"File too large (compression failed): {e}")
                span.set_attribute("error.type", "file_too_large")
                return False

            except CobaltError as e:
                logger.error(f"Cobalt error: {e}")
                span.set_attribute("error.type", "cobalt_error")
                return False

            except DownloadError as e:
                logger.error(f"Download error: {e}")
                span.set_attribute("error.type", "download_error")
                return False

            except Exception as e:
                logger.error(f"Unexpected error processing {url}: {e}")
                span.set_attribute("error.type", "unexpected")
                return False
                
            finally:
                # Cleanup downloaded files
                if self.config.auto_cleanup:
                    await self._cleanup_files(file_paths)
    
    async def _download_with_quality_fallback(self, url: str) -> dict:
        """
        Download video with automatic quality fallback and compression if needed
        
        Args:
            url: Video URL to download
        
        Returns:
            Dict with type and file path(s)
        """
        async with trace_span("quality_fallback", {"url": url}) as span:
            max_size = self.config.max_file_size_bytes
            max_size_mb = self.config.max_file_size_mb
            quality_chain = VideoQuality.get_fallback_chain(self.config.preferred_quality)
            
            span.set_attribute("max_size_mb", max_size_mb)
            span.set_attribute("starting_quality", self.config.preferred_quality.value)
            
            # Track the best download URL we find (for compression fallback)
            best_download_url = None
            best_filename = None
            smallest_size = float('inf')
            last_cobalt_error = None
            
            for quality in quality_chain:
                try:
                    logger.debug(f"Trying quality: {quality.value}")
                    span.add_event("try_quality", {"quality": quality.value})
                    
                    # Get video info from Cobalt at this quality
                    cobalt_response = await self.cobalt.download_video(url, quality)
                    processed = self.cobalt.process_response(cobalt_response)
                    
                    if processed["type"] == "single":
                        download_url = processed["url"]
                        file_size = await self.cobalt.get_file_size(download_url)
                        
                        # Track the smallest file we've seen (for compression fallback)
                        if file_size > 0 and file_size < smallest_size:
                            smallest_size = file_size
                            best_download_url = download_url
                            best_filename = processed.get("filename")
                        
                        if file_size > 0 and file_size >= max_size:
                            size_mb = file_size / (1024 * 1024)
                            logger.info(f"Quality {quality.value}: {size_mb:.1f}MB > {max_size_mb:.1f}MB limit, trying lower")
                            continue  # Try next quality
                        
                        # Size is OK or unknown, proceed with download
                        if file_size > 0:
                            logger.info(f"Quality {quality.value}: {file_size / (1024*1024):.1f}MB - OK")
                        else:
                            logger.info(f"Quality {quality.value}: size unknown, attempting download")
                        
                        file_path = await self._download_file(
                            download_url,
                            processed.get("filename")
                        )
                        
                        # Verify actual file size after download
                        actual_size = os.path.getsize(file_path)
                        if actual_size >= max_size:
                            # File ended up too big - save for compression
                            if actual_size < smallest_size:
                                smallest_size = actual_size
                                best_download_url = download_url
                                best_filename = processed.get("filename")
                            os.remove(file_path)
                            logger.info(f"Downloaded file too large ({actual_size / (1024*1024):.1f}MB), trying lower quality")
                            continue
                        
                        span.set_attribute("final_quality", quality.value)
                        span.set_attribute("file_size_mb", actual_size / (1024 * 1024))
                        return {"type": "single", "file_path": file_path}
                    
                    elif processed["type"] == "picker":
                        # For picker, download files that fit
                        file_paths = await self._handle_picker_with_size_check(
                            processed["items"],
                            quality
                        )
                        if file_paths:
                            span.set_attribute("picker_files", len(file_paths))
                            return {"type": "picker", "file_paths": file_paths}
                        # If no files fit, continue to compression
                    
                except CobaltError as e:
                    # Some Cobalt errors won't get better at lower qualities
                    # (post is gone / blocked / unsupported). Bail immediately
                    # so the real first error wins instead of being masked by
                    # the Nth fallback attempt.
                    if str(e) in TERMINAL_COBALT_CODES:
                        raise
                    last_cobalt_error = e
                    logger.debug(f"Quality {quality.value} failed: {e}")
                    continue
            
            # All quality levels exhausted - try compression as last resort
            if best_download_url:
                logger.info(f"All qualities too large, attempting compression...")
                span.add_event("compression_fallback")
                compressed_path = await self._download_and_compress(
                    best_download_url, 
                    best_filename,
                    max_size_mb
                )
                if compressed_path:
                    span.set_attribute("compressed", True)
                    return {"type": "single", "file_path": compressed_path}
                raise FileTooLargeError(
                    f"File exceeds {max_size_mb:.1f}MB limit and compression failed"
                )
            
            # No download URL was ever obtained -- Cobalt couldn't fetch the content
            if last_cobalt_error:
                raise last_cobalt_error
            raise CobaltError("All quality levels failed with no usable response")
    
    async def _download_and_compress(
        self, 
        download_url: str, 
        filename: Optional[str],
        target_size_mb: float
    ) -> Optional[str]:
        """
        Download a file and compress it to fit within size limit
        
        Returns:
            Path to compressed file, or None if failed
        """
        async with trace_span("download_and_compress", {"target_size_mb": target_size_mb}) as span:
            original_path = None
            compressed_path = None
            
            try:
                # Download the original file
                original_path = await self._download_file(download_url, filename)
                original_size = os.path.getsize(original_path)
                span.set_attribute("original_size_mb", original_size / (1024 * 1024))
                logger.info(f"Downloaded {original_size / (1024*1024):.1f}MB, compressing to {target_size_mb:.1f}MB...")
                
                # Compress with some headroom (95% of limit)
                compressed_path = await compress_video(
                    original_path,
                    target_size_mb * 0.95
                )
                
                if compressed_path and os.path.exists(compressed_path):
                    # Verify compressed size
                    compressed_size = os.path.getsize(compressed_path)
                    span.set_attribute("compressed_size_mb", compressed_size / (1024 * 1024))
                    
                    if compressed_size < self.config.max_file_size_bytes:
                        logger.success(f"Compressed: {original_size / (1024*1024):.1f}MB -> {compressed_size / (1024*1024):.1f}MB")
                        span.set_attribute("compression_success", True)
                        # Clean up original, return compressed
                        if original_path and os.path.exists(original_path):
                            os.remove(original_path)
                        return compressed_path
                    else:
                        logger.warning(f"Compressed file still too large: {compressed_size / (1024*1024):.1f}MB")
                        span.set_attribute("compression_success", False)
                
                return None
                
            except Exception as e:
                logger.error(f"Compression failed: {e}")
                span.set_attribute("error", str(e))
                return None
                
            finally:
                # Clean up on failure
                if compressed_path is None:
                    if original_path and os.path.exists(original_path):
                        os.remove(original_path)
    
    async def _handle_picker_with_size_check(
        self, 
        items: list[dict],
        quality: VideoQuality
    ) -> list[str]:
        """Handle picker items with size checking and compression"""
        if not items:
            raise CobaltError("No files in picker response")
        
        behavior = self.config.picker_behavior
        max_size = self.config.max_file_size_bytes
        max_size_mb = self.config.max_file_size_mb
        
        if behavior == PickerBehavior.FIRST:
            items_to_download = [items[0]]
        elif behavior == PickerBehavior.LAST:
            items_to_download = [items[-1]]
        else:  # ALL
            items_to_download = items
        
        downloaded_files = []
        for i, item in enumerate(items_to_download, 1):
            try:
                download_url = item["url"]
                
                # Check size
                file_size = await self.cobalt.get_file_size(download_url)
                
                # Generate filename
                parsed_url = urlparse(download_url)
                original_filename = os.path.basename(parsed_url.path)
                
                if original_filename and '.' in original_filename:
                    filename = original_filename
                else:
                    ext = os.path.splitext(parsed_url.path)[1] or '.mp4'
                    filename = f"media_{i}{ext}"
                
                # If size is known and too big, try compression
                if file_size > 0 and file_size >= max_size:
                    logger.info(f"Picker item {i}: {file_size / (1024*1024):.1f}MB, compressing...")
                    compressed_path = await self._download_and_compress(
                        download_url,
                        filename,
                        max_size_mb
                    )
                    if compressed_path:
                        downloaded_files.append(compressed_path)
                    else:
                        logger.warning(f"Picker item {i} too large and compression failed, skipping")
                    continue
                
                # Size OK or unknown - download normally
                file_path = await self._download_file(download_url, filename)
                
                # Verify size
                actual_size = os.path.getsize(file_path)
                if actual_size >= max_size:
                    # Try compression
                    logger.info(f"Picker item {i}: {actual_size / (1024*1024):.1f}MB, compressing...")
                    compressed_path = await compress_video(file_path, max_size_mb * 0.95)
                    os.remove(file_path)  # Remove original
                    
                    if compressed_path and os.path.exists(compressed_path):
                        downloaded_files.append(compressed_path)
                    else:
                        logger.warning(f"Picker item {i} compression failed, skipping")
                    continue
                
                downloaded_files.append(file_path)
                
            except Exception as e:
                logger.warning(f"Failed to download picker item {i}: {e}")
                continue
        
        return downloaded_files
    
    async def _download_file(self, video_url: str, filename: Optional[str] = None) -> str:
        """
        Download a video file from URL (async)
        
        Returns:
            Path to the downloaded file
        """
        async with trace_span("download_file") as span:
            if not filename:
                parsed_url = urlparse(video_url)
                filename = os.path.basename(parsed_url.path) or "video"
                if '.' not in filename:
                    filename += '.mp4'
            
            # Sanitize filename
            filename = "".join(
                c for c in filename 
                if c.isalnum() or c in (' ', '-', '_', '.')
            ).rstrip()
            
            file_path = os.path.join(self.config.temp_dir, filename)
            span.set_attribute("filename", filename)
            
            try:
                logger.debug(f"Downloading: {video_url}")
                
                session = await self._get_session()
                async with session.get(video_url) as response:
                    response.raise_for_status()
                    
                    # Stream to file asynchronously
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                
                # Record final size
                final_size = os.path.getsize(file_path)
                span.set_attribute("file_size_bytes", final_size)
                
                logger.debug(f"Downloaded to: {file_path}")
                return file_path
                
            except aiohttp.ClientError as e:
                # Clean up partial file
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise DownloadError(f"Failed to download {video_url}: {e}")
    
    async def _upload_files(self, channel_id: str, file_paths: list[str], embed=None):
        """Upload files to Discord with embed"""
        async with trace_span("discord_upload", {"channel_id": channel_id, "file_count": len(file_paths)}):
            if len(file_paths) == 1:
                await upload_to_discord(
                    channel_id, 
                    file_paths[0], 
                    self.config.discord_token,
                    embed=embed
                )
            else:
                await upload_multiple_to_discord(
                    channel_id, 
                    file_paths, 
                    self.config.discord_token,
                    embed=embed
                )
    
    async def _cleanup_files(self, file_paths: list[str]):
        """Remove downloaded files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Cleaned up: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup {file_path}: {e}")
