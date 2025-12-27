"""
Configuration for ThumbBot - Environment variables only
"""

import os
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

import yaml


class PickerBehavior(Enum):
    """How to handle multiple files (picker responses from Cobalt)"""
    FIRST = "first"
    LAST = "last"
    ALL = "all"


class VideoQuality(Enum):
    """Video quality options - ordered from highest to lowest"""
    MAX = "max"
    UHD_4K = "4k"
    QHD_1440P = "1440p"
    FHD_1080P = "1080p"
    HD_720P = "720p"
    SD_480P = "480p"
    LOW_360P = "360p"
    MOBILE_240P = "240p"
    MIN_144P = "144p"
    
    @classmethod
    def get_fallback_chain(cls, starting_quality: "VideoQuality") -> list["VideoQuality"]:
        """Get ordered list of qualities to try, starting from the given quality"""
        all_qualities = list(cls)
        try:
            start_index = all_qualities.index(starting_quality)
            return all_qualities[start_index:]
        except ValueError:
            return all_qualities


@dataclass
class Config:
    """ThumbBot configuration - all values from environment variables"""
    
    # Required
    discord_token: str
    
    # Cobalt settings
    cobalt_url: str = "http://thumbbot-cobalt:9000"
    preferred_quality: VideoQuality = VideoQuality.MAX
    
    # File handling
    picker_behavior: PickerBehavior = PickerBehavior.ALL
    max_file_size_mb: float = 8.0
    temp_dir: str = "./temp_videos"
    auto_cleanup: bool = True
    
    # Async/concurrency settings
    max_concurrent_downloads: int = 10
    download_timeout: int = 120  # seconds
    
    # Logging
    log_level: str = "INFO"
    
    # Tracing
    otel_endpoint: str = ""  # e.g., "http://jaeger:4317" - empty = disabled
    otel_enabled: bool = True
    
    # Providers file path
    providers_file: str = "providers.yaml"
    
    @property
    def max_file_size_bytes(self) -> int:
        """Convert MB to bytes"""
        return int(self.max_file_size_mb * 1024 * 1024)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        
        picker = os.getenv("PICKER_BEHAVIOR", "all").lower()
        try:
            picker_behavior = PickerBehavior(picker)
        except ValueError:
            picker_behavior = PickerBehavior.ALL
        
        quality = os.getenv("PREFERRED_QUALITY", "max").lower()
        try:
            preferred_quality = VideoQuality(quality)
        except ValueError:
            preferred_quality = VideoQuality.MAX
        
        return cls(
            discord_token=token,
            cobalt_url=os.getenv("COBALT_URL", "http://thumbbot-cobalt:9000"),
            preferred_quality=preferred_quality,
            picker_behavior=picker_behavior,
            max_file_size_mb=float(os.getenv("MAX_FILE_SIZE_MB", "8.0")),
            temp_dir=os.getenv("TEMP_DIR", "./temp_videos"),
            auto_cleanup=os.getenv("AUTO_CLEANUP", "true").lower() == "true",
            max_concurrent_downloads=int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "10")),
            download_timeout=int(os.getenv("DOWNLOAD_TIMEOUT", "120")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            otel_endpoint=os.getenv("OTEL_ENDPOINT", ""),
            otel_enabled=os.getenv("OTEL_ENABLED", "true").lower() == "true",
            providers_file=os.getenv("PROVIDERS_FILE", "providers.yaml"),
        )


def load_providers(config: Config) -> list[str]:
    """Load provider patterns from YAML file"""
    providers_path = Path(config.providers_file)
    
    if not providers_path.exists():
        # Fallback to default providers
        return [
            "reddit",
            "instagram.com/reel",
            "instagram.com/p",
            "facebook.com/watch",
            "facebook.com/reel",
            "facebook.com/share/v",
            "facebook.com/share/r",
            "fb.watch",
        ]
    
    with open(providers_path, "r") as f:
        data = yaml.safe_load(f)
    
    return data.get("providers", [])


# Global config instance - initialized on import
config = Config.from_env()

