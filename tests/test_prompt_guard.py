"""Hallucination guard over the gold set: a verdict may not name an unsupported symbol.

200 fixtures: ids 1..200 of the frozen gold set. Each subject is resolved by the merged
entity index, then one pool symbol that neither the index nor the text supports is
appended. The guard must flag exactly that symbol and nothing else.
"""

import json
import re
import warnings
from pathlib import Path

import pytest

from finscrape.analysis.prompt_guard import assert_grounded, ungrounded_tickers
from finscrape.extract.entity_index import resolve

GOLD = Path(__file__).with_name("gold") / "sector_set.jsonl"
CASES = [
    row
    for row in (
        json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines()
    )
    if 1 <= row["id"] <= 200
]
# Real-looking symbols that are not in the text. The first one equal to no resolved
# symbol and no word in the subject is injected.
POOL = ("HON", "ZZZ", "QQQ", "SPY", "IWM", "GLD", "TLT", "XLF", "XLE", "ARKK")

GAZA = (
    "Israeli fire kills three including child in Gaza. Israeli fire killed three "
    "Palestinians including a child in the Gaza Strip, medics said."
)


def test_200_fixtures_flag_only_the_injected_hallucination():
    checked = kept = 0
    skipped = []
    for row in CASES:
        subject = row["subject"]
        grounded = resolve(subject)
        bogus = next(
            (
                s
                for s in POOL
                if s not in grounded
                and not re.search(rf"\b{re.escape(s.lower())}\b", subject.lower())
            ),
            None,
        )
        if bogus is None:
            skipped.append(row["id"])
            continue
        verdict = grounded + [bogus]
        assert ungrounded_tickers(verdict, subject) == [bogus], row["id"]
        with pytest.raises(ValueError) as excinfo:
            assert_grounded(verdict, subject)
        assert bogus in str(excinfo.value), row["id"]
        checked += 1
        kept += len(grounded)

    summary = (
        f"prompt guard over {checked} fixtures: {kept} kept tickers, "
        f"{checked} injected hallucinations caught, {len(skipped)} skipped"
    )
    print(summary)
    warnings.warn(summary, stacklevel=1)
    assert len(CASES) == 200, f"expected ids 1..200, loaded {len(CASES)}"
    assert not skipped, f"no pool symbol qualified for ids {skipped}"
    assert checked == 200, summary


@pytest.mark.parametrize(
    "text",
    [
        "$TSLA rallied",
        "TSLA rallied",
        "Tesla (TSLA) rallied",
        "shares of tesla rose",
    ],
)
def test_text_only_grounding_keeps_tsla(text):
    assert ungrounded_tickers(["TSLA"], text) == []


@pytest.mark.parametrize(
    "text",
    [
        "analyst raised price target on the stock",
        "all the analysts now expect a rally",
        "the arm wrestlers competed",
    ],
)
def test_english_prose_grounds_no_symbol(text):
    assert ungrounded_tickers(["TGT", "ALL", "NOW", "ARM"], text) == [
        "TGT",
        "ALL",
        "NOW",
        "ARM",
    ]


def test_uppercase_stopwords_do_not_ground():
    text = "ALL analysts NOW expect a rally"
    assert ungrounded_tickers(["ALL", "NOW"], text) == ["ALL", "NOW"]


def test_entity_named_only_outside_the_text_is_rejected():
    entities = [{"name": "NVIDIA Corporation", "ticker": "NVDA"}]
    text = "Advanced Micro Devices beat estimates on data-center demand."
    assert ungrounded_tickers(["NVDA"], text, entities) == ["NVDA"]


def test_nvda_on_gaza_is_flagged():
    assert ungrounded_tickers(["NVDA"], GAZA) == ["NVDA"]


def test_arm_from_arm_wrestlers_is_flagged():
    assert ungrounded_tickers(["ARM"], "The arm wrestlers competed in the gym.") == [
        "ARM"
    ]


def test_assert_grounded_returns_deduped_grounded_list():
    assert assert_grounded(["TSLA", "TSLA"], "TSLA rallied") == ["TSLA"]


def test_assert_grounded_raises_naming_every_offender():
    with pytest.raises(ValueError) as excinfo:
        assert_grounded(["TSLA", "NVDA", "ZZZ"], "TSLA rallied")
    message = str(excinfo.value)
    assert "NVDA" in message
    assert "ZZZ" in message
    assert "TSLA" not in message


def test_order_is_deterministic_and_deduplicated():
    assert ungrounded_tickers(["ZZZ", "NVDA", "ZZZ"], "TSLA rallied") == ["ZZZ", "NVDA"]
