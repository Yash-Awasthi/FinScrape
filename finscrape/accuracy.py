"""
Accuracy metrics shared by the backtest (server.accuracy): confidence calibration
and equity-curve risk metrics over scored verdicts.
"""

from __future__ import annotations

import math
from typing import Any


def calibration(rows: list[dict]) -> dict[str, Any]:
    """Brier score + calibration buckets for confidence vs. actual correctness.

    rows: dicts with 'confidence' (0..1) and 'correct' (bool). Rows missing
    either key are skipped.
    """
    scored = [r for r in rows if r.get("confidence") is not None and r.get("correct") is not None]
    buckets = {"0-.25": 0, ".25-.5": 0, ".5-.75": 0, ".75-1": 0}
    if not scored:
        return {"brier": None, "buckets": buckets}

    brier = sum((r["confidence"] - (1.0 if r["correct"] else 0.0)) ** 2 for r in scored) / len(scored)
    for r in scored:
        conf = r["confidence"]
        if conf < 0.25:
            buckets["0-.25"] += 1
        elif conf < 0.5:
            buckets[".25-.5"] += 1
        elif conf < 0.75:
            buckets[".5-.75"] += 1
        else:
            buckets[".75-1"] += 1

    return {"brier": round(brier, 4), "buckets": buckets}


def equity_metrics(returns: list[float]) -> dict:
    """Sharpe / Sortino / max drawdown for a per-period returns series.

    Prefers the absorbed empyrical library (finscrape/absorbed/quant/empyrical,
    wired from the inspiration quant repos) when pandas is importable; falls
    back to the same formulas in pure python so callers never hard-depend on it.
    """
    clean = [float(r) for r in returns if r is not None]
    if not clean:
        return {"sharpe_ratio": 0.0, "sortino_ratio": 0.0, "max_drawdown": 0.0, "engine": "none"}

    try:
        import pandas as pd

        from finscrape.absorbed.quant.empyrical.empyrical import (
            max_drawdown as _emp_max_drawdown,
        )
        from finscrape.absorbed.quant.empyrical.empyrical import (
            sharpe_ratio as _emp_sharpe,
        )
        from finscrape.absorbed.quant.empyrical.empyrical import (
            sortino_ratio as _emp_sortino,
        )

        series = pd.Series(clean, dtype="float64")
        sharpe = float(_emp_sharpe(series))
        sortino = float(_emp_sortino(series))
        max_drawdown = float(_emp_max_drawdown(series))
        engine = "empyrical"
    except Exception:  # noqa: BLE001 — pandas/empyrical missing or failed: keep working
        engine = "builtin"
        mean = sum(clean) / len(clean)
        std = (sum((r - mean) ** 2 for r in clean) / len(clean)) ** 0.5
        downside = [min(0.0, r) for r in clean]
        downside_std = (sum(d ** 2 for d in downside) / len(clean)) ** 0.5
        sharpe = mean / std if std > 0 else 0.0
        sortino = mean / downside_std if downside_std > 0 else 0.0
        cum, peak, max_drawdown = 1.0, 1.0, 0.0
        for r in clean:
            cum *= 1.0 + r
            peak = max(peak, cum)
            if peak > 0:
                max_drawdown = min(max_drawdown, cum / peak - 1.0)

    def _f(value: float) -> float:
        # NaN/inf (zero-variance series) must not reach JSON responses
        return round(float(value), 4) if math.isfinite(value) else 0.0

    return {
        "sharpe_ratio": _f(sharpe),
        "sortino_ratio": _f(sortino),
        "max_drawdown": _f(max_drawdown),
        "engine": engine,
    }
