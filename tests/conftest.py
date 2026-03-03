import os

# Must be set before any thumbot imports (config.py runs Config.from_env() at module level)
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock

from thumbot.config import Config, VideoQuality, PickerBehavior
from thumbot.downloader.download import VideoDownloader


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def config(tmp_dir):
    return Config(
        discord_token="test-token",
        cobalt_url="http://cobalt-test:9000",
        preferred_quality=VideoQuality.MAX,
        picker_behavior=PickerBehavior.ALL,
        max_file_size_mb=8.0,
        temp_dir=tmp_dir,
        auto_cleanup=True,
        max_concurrent_downloads=2,
        download_timeout=10,
        otel_endpoint="",
        otel_enabled=False,
    )


@pytest.fixture
def mock_cobalt():
    cobalt = MagicMock()
    cobalt.download_video = AsyncMock()
    cobalt.get_file_size = AsyncMock(return_value=0)
    cobalt.process_response = MagicMock()
    cobalt.close = AsyncMock()
    return cobalt


@pytest.fixture
def downloader(config, mock_cobalt):
    dl = VideoDownloader(config)
    dl.cobalt = mock_cobalt
    return dl
