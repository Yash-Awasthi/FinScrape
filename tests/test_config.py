"""Tests for finscrape.config.Config loading and defaults."""

import os
import pytest
from finscrape.config import Config


class TestConfigDefaults:
    def test_from_env_returns_config(self):
        cfg = Config.from_env()
        assert isinstance(cfg, Config)

    def test_default_ai_model(self):
        cfg = Config.from_env()
        assert cfg.ai_model == "auto"

    def test_default_temperature(self):
        cfg = Config.from_env()
        assert cfg.ai_temperature == 0.1

    def test_default_max_tokens(self):
        cfg = Config.from_env()
        assert cfg.ai_max_tokens == 3000

    def test_default_max_articles(self):
        cfg = Config.from_env()
        assert cfg.max_articles_per_source == 30

    def test_default_max_age_hours(self):
        cfg = Config.from_env()
        # Default is the "2hr news window" (see config.py); env can widen it.
        assert cfg.max_article_age_hours == 2.0

    def test_default_invest_threshold(self):
        cfg = Config.from_env()
        assert cfg.invest_threshold == 3

    def test_default_dedup_similarity(self):
        cfg = Config.from_env()
        assert cfg.dedup_similarity == 0.85


class TestConfigFieldTypes:
    def test_float_fields(self):
        cfg = Config.from_env()
        assert isinstance(cfg.ai_temperature, float)
        assert isinstance(cfg.max_article_age_hours, float)
        assert isinstance(cfg.dedup_similarity, float)
        assert isinstance(cfg.dedup_ticker_overlap, float)
        assert isinstance(cfg.divergence_penalty, float)

    def test_int_fields(self):
        cfg = Config.from_env()
        assert isinstance(cfg.ai_max_tokens, int)
        assert isinstance(cfg.ai_timeout, int)
        assert isinstance(cfg.max_articles_per_source, int)
        assert isinstance(cfg.max_paragraphs, int)
        assert isinstance(cfg.max_words, int)
        assert isinstance(cfg.min_text_length, int)
        assert isinstance(cfg.invest_threshold, int)
        assert isinstance(cfg.observe_threshold, int)
        assert isinstance(cfg.cautious_threshold, int)

    def test_str_fields(self):
        cfg = Config.from_env()
        assert isinstance(cfg.openrouter_api_key, str)
        assert isinstance(cfg.ai_model, str)
        assert isinstance(cfg.data_dir, str)
        assert isinstance(cfg.rss_feeds, str)


class TestConfigEnvOverrides:
    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_MODEL", "gpt-4o")
        cfg = Config.from_env()
        assert cfg.ai_model == "gpt-4o"

    def test_temperature_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_AI_TEMP", "0.7")
        cfg = Config.from_env()
        assert cfg.ai_temperature == 0.7

    def test_max_articles_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_MAX_ARTICLES", "25")
        cfg = Config.from_env()
        assert cfg.max_articles_per_source == 25

    def test_invest_threshold_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_INVEST_THRESHOLD", "5")
        cfg = Config.from_env()
        assert cfg.invest_threshold == 5

    def test_data_dir_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_DATA_DIR", "/tmp/test-data")
        cfg = Config.from_env()
        assert cfg.data_dir == "/tmp/test-data"

    def test_dedup_similarity_override(self, monkeypatch):
        monkeypatch.setenv("FINSCRAPE_DEDUP_SIMILARITY", "0.95")
        cfg = Config.from_env()
        assert cfg.dedup_similarity == 0.95
