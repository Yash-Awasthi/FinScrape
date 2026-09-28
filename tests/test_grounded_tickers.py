"""LLM tickers only survive when the article backs them (stored events 20 and 66)."""

from finscrape.analysis.validator import grounded_tickers

GAZA = (
    "Israeli fire kills three including child in Gaza. Israeli fire killed three "
    "Palestinians including a child in the Gaza Strip, medics said."
)
GAZA_ENTITIES = [
    {"name": "Taiwan Semiconductor Manufacturing Co.", "ticker": "TSL"},
    {"name": "NVIDIA Corporation", "ticker": "NVDA"},
    {"name": "Advanced Micro Devices, Inc.", "ticker": "AMD"},
]
GAZA_FROM_TEXT = ["BA", "GD", "LMT", "NOC", "RTX", "XOM"]


def test_gaza_story_drops_chip_tickers():
    llm = ["RTX", "LMT", "TSL", "XOM", "NVDA", "AMD"]
    assert grounded_tickers(llm, GAZA_ENTITIES, GAZA_FROM_TEXT, GAZA) == [
        "RTX",
        "LMT",
        "XOM",
    ]


def test_meloni_story_drops_tech_tickers():
    text = "Italy's Meloni government achieves political stability as bond spreads narrow."
    llm = ["LMT", "NOC", "INTC", "GOOGL", "XOM", "MSFT", "RTX"]
    from_text = ["CVX", "LMT", "NOC", "RTX", "XOM"]
    assert grounded_tickers(llm, [], from_text, text) == ["LMT", "NOC", "XOM", "RTX"]


def test_company_named_in_text_keeps_its_ticker():
    text = "Advanced Micro Devices beat estimates on data-center demand."
    assert grounded_tickers(["AMD"], GAZA_ENTITIES, [], text) == ["AMD"]


def test_sector_keywords_come_from_the_headline_and_lede_only():
    from finscrape.entity_map import lede_tickers

    body = "Italian bond spreads narrowed. " * 20 + "Markets were hit by the U.S.-Iran war."
    assert lede_tickers("Italy's Meloni government achieves political stability", body) == []
    assert "XOM" in lede_tickers("Iran closes Strait of Hormuz", body)
