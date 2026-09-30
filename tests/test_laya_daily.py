import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "laya_train"))

import daily


def test_templated_alerts_are_skipped():
    assert daily.TEMPLATED.search("Bitcoin Cash (BCH) surged +9.8% in 24h")
    assert daily.TEMPLATED.search("bitcoin cash bch dropped 98 in 24h")
    assert daily.TEMPLATED.search("M 4.5 earthquake - 38 km E of Nobeoka, Japan")
    assert not daily.TEMPLATED.search("Oil surged 5% after Hormuz closure")


def test_parse_label():
    assert daily.parse_label("energy,positive") == ("energy", "positive")
    assert daily.parse_label(" Other , Neutral ") == ("other", "neutral")
    assert daily.parse_label("energy") == ("energy", "")
    assert daily.parse_label("oil,up") == ("", "")


def test_balanced_recall_does_not_reward_always_neutral():
    truth = ["neutral"] * 8 + ["positive", "negative"]
    always_neutral = [(t, "neutral") for t in truth]
    assert round(daily.balanced_recall(always_neutral), 3) == 0.333
    assert daily.balanced_recall([(t, t) for t in truth]) == 1.0
    assert daily.balanced_recall([]) == 0.0
