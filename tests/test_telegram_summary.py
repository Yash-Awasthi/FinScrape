"""The daily Telegram summary counts verdicts and lists the strongest calls first."""

from worker.telegram_summary import MAX_CHARS, summary_text


def test_summary_counts_verdicts_and_orders_calls_by_strength():
    events = [
        {
            "verdict": "OBSERVE",
            "signal_score": 0,
            "confidence": 0.5,
            "tickers": [],
            "subject": "x",
        },
        {
            "verdict": "INVEST",
            "signal_score": 3,
            "confidence": 0.6,
            "tickers": ["XOM"],
            "subject": "oil_up",
        },
        {
            "verdict": "PULL_OUT",
            "signal_score": -4,
            "confidence": 0.7,
            "tickers": ["LMT"],
            "subject": "strike",
        },
    ]
    text = summary_text(events)
    assert "3 events" in text and "INVEST 1" in text and r"PULL\_OUT 1" in text
    assert text.index("strike") < text.index(r"oil\_up")


def test_summary_handles_a_quiet_day_and_stays_under_the_limit():
    assert "No new signals" in summary_text([])
    flood = [
        {
            "verdict": "INVEST",
            "signal_score": 5,
            "confidence": 1,
            "tickers": ["A"],
            "subject": "y" * 900,
        }
    ] * 20
    assert len(summary_text(flood)) <= MAX_CHARS
