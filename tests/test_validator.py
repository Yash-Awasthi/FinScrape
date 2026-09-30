"""Tests for finscrape.analysis.validator heuristic scoring."""

import pytest

from finscrape.analysis.validator import (
    calculate_heuristic_score,
    check_divergence,
    clean_tickers,
    fuse_confidence,
    apply_source_credibility,
    apply_recency_decay,
)


# ---------------------------------------------------------------------------
# calculate_heuristic_score
# ---------------------------------------------------------------------------

class TestCalculateHeuristicScore:
    def test_strongly_positive_text(self):
        text = "Company reported record revenue and surged to all-time high"
        sentiment, impact = calculate_heuristic_score(text, "earnings")
        assert sentiment == "positive"
        assert 0.0 <= impact <= 1.0

    def test_strongly_negative_text(self):
        text = "The firm filed for bankruptcy after the fraud scandal collapsed its stock"
        sentiment, impact = calculate_heuristic_score(text, "bankrupt")
        assert sentiment == "negative"
        assert 0.0 <= impact <= 1.0

    def test_neutral_text(self):
        text = "The company held its regular meeting on Tuesday afternoon"
        sentiment, impact = calculate_heuristic_score(text, "other")
        assert sentiment == "neutral"
        assert 0.0 <= impact <= 1.0

    def test_impact_bounded_zero_to_one(self):
        for event_type in ["earnings", "bankrupt", "other", "merger_acquisition"]:
            _, impact = calculate_heuristic_score("some random text", event_type)
            assert 0.0 <= impact <= 1.0

    def test_dollar_billion_boosts_impact(self):
        base_text = "The company announced a deal"
        _, impact_no_dollar = calculate_heuristic_score(base_text, "merger_acquisition")
        _, impact_with_dollar = calculate_heuristic_score(
            base_text + " worth $50 billion", "merger_acquisition"
        )
        assert impact_with_dollar > impact_no_dollar

    def test_dollar_million_boosts_impact(self):
        base_text = "The company announced a deal"
        _, impact_no_dollar = calculate_heuristic_score(base_text, "merger_acquisition")
        _, impact_with_dollar = calculate_heuristic_score(
            base_text + " worth $200 million", "merger_acquisition"
        )
        assert impact_with_dollar > impact_no_dollar

    def test_magnitude_words_boost_impact(self):
        plain = "The company released results"
        boosted = "The company released massive unprecedented historic results"
        _, impact_plain = calculate_heuristic_score(plain, "earnings")
        _, impact_boosted = calculate_heuristic_score(boosted, "earnings")
        assert impact_boosted > impact_plain

    def test_unknown_event_type_uses_default(self):
        sentiment, impact = calculate_heuristic_score("neutral text", "nonexistent_type")
        assert 0.0 <= impact <= 1.0


# ---------------------------------------------------------------------------
# calculate_heuristic_score — zero boost must return base_impact exactly
# ---------------------------------------------------------------------------

class TestZeroBoostGivesBackBaseImpact:
    @pytest.mark.parametrize(
        "event_type, plain_text, expected_impact",
        [
            ("other", "The company held its quarterly meeting on schedule", 0.30),
            ("merger_acquisition", "The company announced a deal", 0.90),
        ],
    )
    def test_zero_boost_matches_base_impact(self, event_type, plain_text, expected_impact):
        _, impact = calculate_heuristic_score(plain_text, event_type)
        assert impact == pytest.approx(expected_impact, abs=0.005)

    def test_boosted_impact_matches_expected(self):
        text = "The deal is valued at $50 billion"
        _, impact = calculate_heuristic_score(text, "other")
        assert impact == pytest.approx(0.38, abs=0.005)

    def test_boost_rises_monotonically(self):
        base_text = "The company announced results"
        _, impact_none = calculate_heuristic_score(base_text, "other")
        _, impact_low = calculate_heuristic_score(base_text + " worth $5 million", "other")
        _, impact_medium = calculate_heuristic_score(base_text + " worth $100 million", "other")
        _, impact_high = calculate_heuristic_score(base_text + " worth $50 billion", "other")
        assert impact_none < impact_low < impact_medium < impact_high

    def test_impact_always_between_zero_and_one(self):
        for event_type, text in [
            ("bankrupt", "The firm filed for bankruptcy worth $50 billion massive historic"),
            ("other", "Nothing happened"),
            ("merger_acquisition", "Deal worth $50 billion, biggest ever, unprecedented"),
        ]:
            _, impact = calculate_heuristic_score(text, event_type)
            assert 0.0 < impact < 1.0


# ---------------------------------------------------------------------------
# check_divergence
# ---------------------------------------------------------------------------

class TestCheckDivergence:
    def test_same_sentiment_no_divergence(self):
        assert check_divergence("positive", "positive") is False

    def test_opposite_sentiment_diverges(self):
        assert check_divergence("positive", "negative") is True

    def test_ai_neutral_no_divergence(self):
        assert check_divergence("neutral", "negative") is False

    def test_heuristic_neutral_no_divergence(self):
        assert check_divergence("positive", "neutral") is False

    def test_both_neutral_no_divergence(self):
        assert check_divergence("neutral", "neutral") is False

    def test_negative_vs_positive_diverges(self):
        assert check_divergence("negative", "positive") is True


# ---------------------------------------------------------------------------
# clean_tickers
# ---------------------------------------------------------------------------

class TestCleanTickers:
    def test_removes_stopwords(self):
        tickers = ["AAPL", "A", "THE", "TSLA", "IS"]
        cleaned = clean_tickers(tickers)
        assert "AAPL" in cleaned
        assert "TSLA" in cleaned
        assert "A" not in cleaned
        assert "THE" not in cleaned
        assert "IS" not in cleaned

    def test_keeps_valid_tickers(self):
        tickers = ["AAPL", "GOOG", "MSFT"]
        assert clean_tickers(tickers) == ["AAPL", "GOOG", "MSFT"]

    def test_empty_list(self):
        assert clean_tickers([]) == []

    def test_drops_llm_placeholders_for_unlisted_entities(self):
        tickers = ["N/A", "NONE", "—", "", "null", "RELIANCE.NS", "BRK-B", "LMT"]
        assert clean_tickers(tickers) == ["RELIANCE.NS", "BRK-B", "LMT"]

    def test_scenario_exposure_skips_placeholder_entity_tickers(self):
        from finscrape.scenarios import _tickers_of

        event = {
            "tickers": ["LMT", "N/A"],
            "affected_entities": [{"name": "Milrem", "ticker": "—"}, {"name": "GD", "ticker": "gd"}],
        }
        assert _tickers_of(event) == ["LMT", "GD"]

    def test_case_insensitive(self):
        # clean_tickers uppercases before checking stopwords
        tickers = ["aapl", "a", "tsla"]
        cleaned = clean_tickers(tickers)
        assert "aapl" in cleaned
        assert "tsla" in cleaned
        assert "a" not in cleaned

    def test_removes_financial_abbreviations(self):
        tickers = ["AAPL", "EPS", "IPO", "SEC", "GOOG"]
        cleaned = clean_tickers(tickers)
        assert "AAPL" in cleaned
        assert "GOOG" in cleaned
        assert "EPS" not in cleaned
        assert "IPO" not in cleaned
        assert "SEC" not in cleaned


# ---------------------------------------------------------------------------
# fuse_confidence
# ---------------------------------------------------------------------------

class TestFuseConfidence:
    def test_divergence_penalty_costs_full_015(self):
        # Multipliers apply first, so the additive -0.15 lands on the
        # already-multiplied value instead of being shrunk by it.
        no_divergence = fuse_confidence(0.9, "cnbc", 24, divergence=False, breaking=False)
        with_divergence = fuse_confidence(0.9, "cnbc", 24, divergence=True, breaking=False)
        assert round(no_divergence - with_divergence, 2) == 0.15

    def test_breaking_boost_survives_intact(self):
        no_breaking = fuse_confidence(0.5, "cnbc", 0, divergence=False, breaking=False)
        with_breaking = fuse_confidence(0.5, "cnbc", 0, divergence=False, breaking=True)
        assert round(with_breaking - no_breaking, 2) == 0.10

    def test_result_clamped_to_zero_one_on_high_end(self):
        result = fuse_confidence(1.0, "bloomberg", 0, divergence=False, breaking=True)
        assert result == 1.0

    def test_result_clamped_to_zero_one_on_low_end(self):
        result = fuse_confidence(0.0, "cnbc", 24, divergence=True, breaking=False)
        assert result == 0.0

    def test_result_always_in_bounds(self):
        for base in [0.0, 0.3, 0.5, 0.8, 1.0]:
            for divergence in [True, False]:
                for breaking in [True, False]:
                    result = fuse_confidence(base, "cnbc", 12, divergence, breaking)
                    assert 0.0 <= result <= 1.0

    def test_unknown_age_still_uses_085_multiplier(self):
        result = fuse_confidence(0.6, "cnbc", None, divergence=False, breaking=False)
        expected = apply_recency_decay(apply_source_credibility(0.6, "cnbc"), None)
        assert result == expected

    def test_reuses_source_credibility_and_recency_decay(self):
        # No divergence/breaking means fuse_confidence is exactly the
        # composition of the two existing adjustment functions.
        base, source, age = 0.7, "reuters", 6
        expected = apply_recency_decay(apply_source_credibility(base, source), age)
        result = fuse_confidence(base, source, age, divergence=False, breaking=False)
        assert result == expected
