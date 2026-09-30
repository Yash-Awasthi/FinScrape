import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import llm


def test_only_given_flags_change():
    args = argparse.Namespace(model="deepseek-v4.1-flash:free", url=None, key="k", fallback=None)
    assert llm.settings(args) == {
        "FINSCRAPE_MODEL": "deepseek-v4.1-flash:free",
        "OPENAI_API_KEY": "k",
    }
