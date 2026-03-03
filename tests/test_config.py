"""Tests for config.py -- Config.from_env, VideoQuality.get_fallback_chain, load_providers."""
import os
os.environ.setdefault("DISCORD_TOKEN", "test-token-not-real")

import pytest
from unittest.mock import patch

from thumbot.config import Config, VideoQuality, PickerBehavior, load_providers


# ---- VideoQuality.get_fallback_chain ----

class TestGetFallbackChain:

    def test_max_returns_full_chain(self):
        chain = VideoQuality.get_fallback_chain(VideoQuality.MAX)
        assert chain[0] == VideoQuality.MAX
        assert len(chain) == 9

    def test_720p_starts_from_720(self):
        chain = VideoQuality.get_fallback_chain(VideoQuality.HD_720P)
        assert chain[0] == VideoQuality.HD_720P
        assert VideoQuality.FHD_1080P not in chain
        assert len(chain) == 5

    def test_144p_returns_single(self):
        chain = VideoQuality.get_fallback_chain(VideoQuality.MIN_144P)
        assert chain == [VideoQuality.MIN_144P]


# ---- Config.from_env ----

class TestConfigFromEnv:

    def test_missing_token_raises(self):
        env = {}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="DISCORD_TOKEN"):
                Config.from_env()

    def test_defaults_applied(self):
        env = {"DISCORD_TOKEN": "tok123"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.discord_token == "tok123"
        assert cfg.cobalt_url == "http://thumbbot-cobalt:9000"
        assert cfg.preferred_quality == VideoQuality.MAX
        assert cfg.picker_behavior == PickerBehavior.ALL
        assert cfg.max_file_size_mb == 8.0
        assert cfg.max_concurrent_downloads == 10

    def test_valid_picker_behavior_parsed(self):
        env = {"DISCORD_TOKEN": "t", "PICKER_BEHAVIOR": "first"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.picker_behavior == PickerBehavior.FIRST

    def test_invalid_picker_behavior_defaults(self):
        env = {"DISCORD_TOKEN": "t", "PICKER_BEHAVIOR": "garbage"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.picker_behavior == PickerBehavior.ALL

    def test_invalid_quality_defaults(self):
        env = {"DISCORD_TOKEN": "t", "PREFERRED_QUALITY": "8k_ultra"}
        with patch.dict(os.environ, env, clear=True):
            cfg = Config.from_env()
        assert cfg.preferred_quality == VideoQuality.MAX

    def test_max_file_size_bytes_property(self):
        cfg = Config(discord_token="t", max_file_size_mb=50.0)
        assert cfg.max_file_size_bytes == 50 * 1024 * 1024


# ---- load_providers ----

class TestLoadProviders:

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = Config(discord_token="t", providers_file=str(tmp_path / "missing.yaml"))
        providers = load_providers(cfg)
        assert "reddit" in providers
        assert "instagram.com/reel" in providers
        assert len(providers) == 8

    def test_yaml_file_loaded(self, tmp_path):
        yaml_file = tmp_path / "providers.yaml"
        yaml_file.write_text("providers:\n  - tiktok.com\n  - vine.co\n")
        cfg = Config(discord_token="t", providers_file=str(yaml_file))
        providers = load_providers(cfg)
        assert providers == ["tiktok.com", "vine.co"]

    def test_yaml_without_providers_key(self, tmp_path):
        yaml_file = tmp_path / "providers.yaml"
        yaml_file.write_text("other_key: true\n")
        cfg = Config(discord_token="t", providers_file=str(yaml_file))
        providers = load_providers(cfg)
        assert providers == []
