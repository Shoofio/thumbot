"""
Cobalt API client for video downloads (async) with quality fallback
"""
import aiohttp
import time
from typing import Any, Optional

from thumbot.config import VideoQuality
from thumbot.utils.logger import get_logger
from thumbot.utils.metrics import track_cobalt_request
from thumbot.downloader.exceptions import CobaltError

logger = get_logger("cobalt")


class CobaltClient:
    """Async client for interacting with Cobalt API with quality fallback"""
    
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/') + '/'
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': 'ThumbBot/2.0'
                }
            )
        return self._session
    
    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def download_video(
        self,
        url: str,
        quality: Optional[VideoQuality] = None
    ) -> dict[str, Any]:
        """Request video download from Cobalt API."""
        payload = {"url": url}

        # Add quality parameter if specified
        if quality and quality != VideoQuality.MAX:
            payload["videoQuality"] = quality.value

        session = await self._get_session()
        start_time = time.time()

        try:
            async with session.post(self.base_url, json=payload) as response:
                response_time = time.time() - start_time

                if response.status == 400:
                    body = await response.json() or {}
                    error_code = body.get("error", {}).get("code", "unknown") if isinstance(body.get("error"), dict) else body.get("error", "unknown")
                    track_cobalt_request("quality_unavailable", response_time)
                    raise CobaltError(f"{error_code}")

                response.raise_for_status()
                result = await response.json()

                if result.get("status") == "error":
                    error_code = result.get("error", {}).get("code", "unknown") if isinstance(result.get("error"), dict) else result.get("error", "unknown")
                    track_cobalt_request("error", response_time)
                    raise CobaltError(f"{error_code}")

                track_cobalt_request("success", response_time)
                quality_str = quality.value if quality else "max"
                logger.debug(f"Cobalt response: {result.get('status')} @ {quality_str}")
                return result

        except aiohttp.ClientError as e:
            track_cobalt_request("error", time.time() - start_time)
            raise CobaltError(f"Cobalt request failed: {e}")
    
    async def get_file_size(self, download_url: str) -> int:
        """
        Get file size from download URL using HEAD request
        
        Args:
            download_url: Direct download URL
        
        Returns:
            File size in bytes, or 0 if unknown
        """
        try:
            session = await self._get_session()
            async with session.head(download_url, allow_redirects=True) as response:
                content_length = response.headers.get('content-length')
                if content_length:
                    return int(content_length)
                return 0
        except Exception as e:
            logger.debug(f"Could not get file size: {e}")
            return 0
    
    def process_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """
        Process Cobalt API response and extract download information
        
        Returns:
            Dict with processed download information:
            - type: "single" or "picker"
            - url: Direct download URL (for single)
            - items: List of download items (for picker)
            - filename: Optional filename
        """
        status = response.get("status")
        
        if status in ("redirect", "tunnel"):
            # Single video file
            return {
                "type": "single",
                "url": response.get("url"),
                "filename": response.get("filename"),
            }
        
        elif status == "picker":
            # Multiple files (like Twitter threads, Instagram carousels)
            picker_items = response.get("picker", [])
            return {
                "type": "picker",
                "items": [
                    {"url": item.get("url"), "thumb": item.get("thumb")}
                    for item in picker_items
                ],
            }
        
        elif status == "error":
            error_info = response.get("error", {})
            raise CobaltError(f"Cobalt processing error: {error_info}")
        
        else:
            logger.warning(f"Unknown Cobalt response status: {status}")
            return response
