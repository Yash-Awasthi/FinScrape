"""Tests for sentiment_analyzer.py — financial sentiment analysis."""


from finscrape.services.sentiment_analyzer import (
    Sentiment,
    SentimentAnalyzer,
    SentimentResult,
)


class TestAnalyzeText:
    def test_bullish_text(self):
        result = SentimentAnalyzer.analyze_text("Revenue surged 50% beating all estimates with exceptional growth")
        assert result.score > 0
        assert result.sentiment in (Sentiment.BULLISH, Sentiment.VERY_BULLISH, Sentiment.NEUTRAL)

    def test_bearish_text(self):
        result = SentimentAnalyzer.analyze_text("Company crashes after bankruptcy filing and massive losses")
        assert result.score < 0
        assert result.sentiment in (Sentiment.BEARISH, Sentiment.VERY_BEARISH)

    def test_neutral_text(self):
        result = SentimentAnalyzer.analyze_text("The market opened today")
        assert abs(result.score) < 0.5

    def test_negation(self):
        result = SentimentAnalyzer.analyze_text("The company is not strong and will not rise")
        assert result.score < 0

    def test_intensifier(self):
        result = SentimentAnalyzer.analyze_text("extremely strong earnings beat")
        assert result.score > 0

    def test_empty_text(self):
        result = SentimentAnalyzer.analyze_text("")
        assert result.sentiment == Sentiment.NEUTRAL

    def test_financial_context_boost(self):
        result = SentimentAnalyzer.analyze_text("revenue earnings profit growth surge")
        assert result.score > 0.2

    def test_word_count(self):
        result = SentimentAnalyzer.analyze_text("Revenue surged beating estimates")
        assert result.word_count == 4

    def test_positive_words_extracted(self):
        result = SentimentAnalyzer.analyze_text("Revenue surged and profits grew")
        assert len(result.positive_words) > 0

    def test_negative_words_extracted(self):
        result = SentimentAnalyzer.analyze_text("Company losses declined and crashed")
        assert len(result.negative_words) > 0


class TestAnalyzeHeadline:
    def test_positive_headline(self):
        result = SentimentAnalyzer.analyze_headline("Stock surges to record high on earnings beat")
        assert result.score > 0

    def test_negative_headline(self):
        result = SentimentAnalyzer.analyze_headline("Stock crashes plunges to record low")
        assert result.score < 0


class TestSentimentTrend:
    def test_uptrend(self):
        results = [
            SentimentResult(text="test", sentiment=Sentiment.BULLISH, score=0.2 + i * 0.1,
                          confidence=0.8, positive_words=[], negative_words=[], word_count=10)
            for i in range(10)
        ]
        trend = SentimentAnalyzer.calculate_sentiment_trend(results, "week1")
        assert trend.avg_score > 0

    def test_empty_trend(self):
        trend = SentimentAnalyzer.calculate_sentiment_trend([], "empty")
        assert trend.avg_score == 0.0
        assert trend.volatility == 0.0


class TestExtractKeywords:
    def test_extracts_keywords(self):
        keywords = SentimentAnalyzer.extract_sentiment_keywords(
            "Revenue surged with strong growth and profits rising"
        )
        assert len(keywords) > 0
        assert keywords[0][1] >= 1
