"""Sector contest (docs/LAYA_PLAN.md step 5), all on CPU.

    python -m scripts.backfill.sector_contest sample
    python -m scripts.backfill.sector_contest lora-other
    python -m scripts.backfill.sector_contest laya NAME MODEL_DIR [--part I/K]
    python -m scripts.backfill.sector_contest embed [--part I/K]
    python -m scripts.backfill.sector_contest score

Truth is the taxonomy sector of the one S&P 500 company a headline names. `sample` draws
fixed-seed uniform samples: test (single-company, 2025-10-01 on), none (no company, same
weeks) and fit (single-company, 2023-10-01 to 2025-09-30), plus the LoRA training cases.
`lora-other` adds fit-period no-company headlines as `other`, which train.py turns into a
flat target, so a LoRA also learns to stay unsure when no company is named.
Each entry feeds `laya.choose_sector` as `laya.classify` would; `score` prints the report.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/backfill")
OUT = DATA / "contest"
ROWS = OUT / "rows.parquet"
FIT_FROM, TEST_FROM = (
    pd.Timestamp("2023-10-01", tz="UTC"),
    pd.Timestamp("2025-10-01", tz="UTC"),
)
N_TEST, N_NONE, N_FIT, N_LORA, N_OTHER = 3000, 1000, 30000, 20000, 5000
SEED = 20261002
SECTORS = (
    "technology",
    "healthcare",
    "financials",
    "energy",
    "consumer",
    "industrials",
    "materials",
    "utilities",
    "real_estate",
    "communications",
)
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def sample() -> None:
    sector = pd.read_parquet(DATA / "universe.parquet").set_index("ticker")["sector"]
    one, none = [], []
    cols = ["event_id", "added_utc", "url", "title", "tickers", "n_companies"]
    for f in sorted((DATA / "events").glob("*.parquet")):
        d = pd.read_parquet(f, columns=cols)
        one.append(d[d["n_companies"] == 1])
        # 0.05% of every month keeps the no-company draw proportional to volume.
        z = d[
            (d["n_companies"] == 0)
            & (d["added_utc"] >= TEST_FROM)
            & (d["title"].str.len() > 0)
        ]
        none.append(z.sample(frac=0.0005, random_state=SEED))
    ev = pd.concat(one, ignore_index=True)
    ev["truth"] = ev["tickers"].str[0].map(sector)
    test = (
        ev[ev["added_utc"] >= TEST_FROM]
        .sample(N_TEST, random_state=SEED)
        .assign(split="test")
    )
    fit_pool = ev[(ev["added_utc"] >= FIT_FROM) & (ev["added_utc"] < TEST_FROM)]
    fit = fit_pool.sample(N_FIT, random_state=SEED).assign(split="fit")
    nc = (
        pd.concat(none).sample(N_NONE, random_state=SEED).assign(split="none", truth="")
    )
    rows = pd.concat([test, nc, fit], ignore_index=True)
    rows["ticker"] = rows["tickers"].str[0].fillna("")
    rows = rows.drop(columns=["tickers", "n_companies"])
    OUT.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(ROWS, index=False)
    cases = [
        {"subject": t, "sector": s}
        for t, s in zip(fit["title"][:N_LORA], fit["truth"][:N_LORA], strict=True)
    ]
    (OUT / "lora_fit.json").write_text(json.dumps({"cases": cases}), "utf-8")
    pools = (
        f"test pool {(ev['added_utc'] >= TEST_FROM).sum()}, fit pool {len(fit_pool)}"
    )
    print(
        f"{len(test)} test, {len(nc)} none, {len(fit)} fit, {len(cases)} LoRA cases ({pools})"
    )


def lora_other() -> None:
    cols = ["added_utc", "title", "n_companies"]
    pool = []
    for f in sorted((DATA / "events").glob("*.parquet")):
        d = pd.read_parquet(f, columns=cols)
        z = d[
            (d["n_companies"] == 0)
            & (d["added_utc"] >= FIT_FROM)
            & (d["added_utc"] < TEST_FROM)
            & (d["title"].str.len() > 0)
        ]
        pool.append(z.sample(frac=0.0004, random_state=SEED))
    titles = pd.concat(pool).sample(N_OTHER, random_state=SEED)["title"]
    cases = json.loads((OUT / "lora_fit.json").read_text("utf-8"))["cases"]
    cases += [{"subject": t, "sector": "other"} for t in titles]
    random.Random(SEED).shuffle(cases)
    (OUT / "lora_fit_other.json").write_text(json.dumps({"cases": cases}), "utf-8")
    print(f"{len(cases)} cases, {len(titles)} of them no-company as other")


def _part(rows: pd.DataFrame, part: str) -> tuple[pd.DataFrame, str]:
    i, k = (int(x) for x in part.split("/"))
    return rows.iloc[i::k], f"{i}of{k}"


def run_laya(name: str, model_dir: str, part: str) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["FINSCRAPE_LAYA_MODEL"] = model_dir
    import torch

    from finscrape.analysis import laya

    k = int(part.split("/")[1])
    torch.set_num_threads(max(1, (os.cpu_count() or 4) // k))
    rows, tag = _part(pd.read_parquet(ROWS).query("split != 'fit'"), part)
    predict = laya._load()
    if predict is None:
        sys.exit(f"Laya did not load from {model_dir}")
    question = {"sector": laya._QUESTIONS["sector"]}
    picks, t0 = [], time.time()
    for n, title in enumerate(rows["title"], 1):
        picks.append(laya._pick(predict(title, question)["answers"]["sector"]))
        if n % 200 == 0:
            print(f"{tag} {n}/{len(rows)} {n / (time.time() - t0):.2f}/s", flush=True)
    out = pd.DataFrame(picks, columns=["sector", "p"]).assign(
        event_id=rows["event_id"].to_numpy()
    )
    out.to_parquet(OUT / f"laya-{name}-{tag}.parquet", index=False)


def run_embed(part: str) -> None:
    rows, tag = _part(pd.read_parquet(ROWS), part)
    titles, vecs, t0 = rows["title"].tolist(), [], time.time()
    for s in range(0, len(titles), 32):
        # nomic-embed-text is trained with task prefixes; "classification: " fits this one.
        body = {
            "model": "nomic-embed-text",
            "input": [f"classification: {t}" for t in titles[s : s + 32]],
        }
        req = urllib.request.Request(
            f"{OLLAMA}/api/embed",
            json.dumps(body).encode(),
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            vecs.extend(json.load(r)["embeddings"])
        if s % 3200 == 0:
            print(
                f"{tag} {len(vecs)}/{len(titles)} {len(vecs) / (time.time() - t0):.1f}/s",
                flush=True,
            )
    np.savez(
        OUT / f"embed-{tag}.npz",
        event_id=rows["event_id"].to_numpy(),
        x=np.asarray(vecs, np.float32),
    )


def fit_softmax(x: np.ndarray, y: np.ndarray, l2: float) -> np.ndarray:
    """Multinomial logistic regression (weights with a bias row) by L-BFGS."""
    from scipy.optimize import minimize

    xb = np.hstack([x, np.ones((len(x), 1), x.dtype)]).astype(np.float64)
    k, onehot = int(y.max()) + 1, np.eye(int(y.max()) + 1)[y]

    def loss(w: np.ndarray) -> tuple[float, np.ndarray]:
        w = w.reshape(xb.shape[1], k)
        z = xb @ w
        z -= z.max(1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(1, keepdims=True)
        reg = l2 * (w[:-1] ** 2).sum() / 2
        grad = xb.T @ (p - onehot) / len(xb)
        grad[:-1] += l2 * w[:-1]
        return float(-np.log(p[onehot == 1] + 1e-12).mean() + reg), grad.ravel()

    res = minimize(
        loss,
        np.zeros(xb.shape[1] * k),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 500},
    )
    return res.x.reshape(xb.shape[1], k)


def softmax_predict(w: np.ndarray, x: np.ndarray) -> np.ndarray:
    z = np.hstack([x, np.ones((len(x), 1), x.dtype)]) @ w
    p = np.exp(z - z.max(1, keepdims=True))
    return p / p.sum(1, keepdims=True)


def embed_views(rows: pd.DataFrame) -> pd.DataFrame:
    parts = [np.load(f) for f in sorted(OUT.glob("embed-*.npz"))]
    x = pd.DataFrame(
        np.vstack([p["x"] for p in parts]),
        index=np.concatenate([p["event_id"] for p in parts]),
    )
    fit = rows[rows["split"] == "fit"].sort_values("added_utc")
    y = fit["truth"].map({s: i for i, s in enumerate(SECTORS)}).to_numpy()
    xf = x.loc[fit["event_id"]].to_numpy()
    # The L2 strength is chosen on the newest fifth of the fit split, never on test.
    cut = int(len(fit) * 0.8)
    best = max(
        (1e-4, 1e-3, 1e-2),
        key=lambda l2: (
            softmax_predict(fit_softmax(xf[:cut], y[:cut], l2), xf[cut:]).argmax(1)
            == y[cut:]
        ).mean(),
    )
    print(f"embeddings: l2 {best} chosen on the newest fifth of the fit split")
    other = rows[rows["split"] != "fit"]
    p = softmax_predict(fit_softmax(xf, y, best), x.loc[other["event_id"]].to_numpy())
    return pd.DataFrame(
        {
            "event_id": other["event_id"].to_numpy(),
            "sector": np.array(SECTORS)[p.argmax(1)],
            "p": p.max(1),
        }
    )


def no_model_inputs(rows: pd.DataFrame) -> pd.DataFrame:
    """Keyword sector and named-company tickers the pipeline would see on the headline, and
    the stored LLM sector when a live event carries the same URL."""
    from finscrape.analysis.nlp import FinancialNLP
    from finscrape.analysis.sp500 import headline_tickers
    from finscrape.entity_map import resolve_company_tickers

    nlp = FinancialNLP()
    live = (
        pd.read_parquet(OUT / "live_llm.parquet")
        .drop_duplicates("url")
        .set_index("url")["sector_impact"]
    )
    return rows.assign(
        keyword=[nlp.analyze(t, "").sector for t in rows["title"]],
        companies=[
            resolve_company_tickers(t) + headline_tickers(t) for t in rows["title"]
        ],
        llm=rows["url"].map(live).fillna(""),
    )


def chain(inputs: pd.DataFrame, view: pd.DataFrame | None) -> pd.Series:
    from finscrape.analysis.laya import LayaView, choose_sector

    v = view.set_index("event_id").loc[inputs["event_id"]] if view is not None else None
    return pd.Series(
        [
            choose_sector(
                r.llm,
                LayaView(v["sector"].iat[i], float(v["p"].iat[i]), "", 0.0)
                if v is not None
                else None,
                r.keyword,
                r.companies,
            )
            for i, r in enumerate(inputs.itertuples())
        ],
        index=inputs.index,
    )


def report(
    frame: pd.DataFrame, entries: list[str], margin: float = 5.0, min_n: int = 1000
) -> str:
    """Markdown report. `frame` has split, truth and one label column per entry; the first
    entry is the no-model baseline the keep rule measures against."""
    test, none = frame[frame["split"] == "test"], frame[frame["split"] == "none"]
    acc = {e: 100 * (test[e] == test["truth"]).mean() for e in entries}
    lines = [
        f"test n={len(test)}, no-company n={len(none)}",
        "",
        "| entry | test accuracy | no-company: other | picks a sector |",
        "|---|---|---|---|",
    ]
    for e in entries:
        other = 100 * (none[e] == "other").mean() if len(none) else float("nan")
        lines.append(f"| {e} | {acc[e]:.1f}% | {other:.1f}% | {100 - other:.1f}% |")
    lines += [
        "",
        "| sector | n | " + " | ".join(entries) + " |",
        "|---" * (len(entries) + 2) + "|",
    ]
    for s, g in test.groupby("truth"):
        lines.append(
            f"| {s} | {len(g)} | "
            + " | ".join(f"{100 * (g[e] == s).mean():.1f}" for e in entries)
            + " |"
        )
    base, rivals = entries[0], [e for e in entries[1:] if not e.endswith(" alone")]
    best = max(rivals, key=acc.__getitem__) if rivals else base
    lead = acc[best] - acc[base]
    kept = best != base and lead >= margin and len(test) >= min_n
    lines += [
        "",
        f"keep rule: best entry `{best}` leads `{base}` by {lead:+.1f} points; {'kept' if kept else 'not kept'}",
    ]
    return "\n".join(lines)


def by_familiarity(frame: pd.DataFrame, seen: pd.Series, entries: list[str]) -> str:
    """Test accuracy by how often the named company appears in the LoRA cases: a high
    score on familiar names is lookup, not reading the headline."""
    test = frame[frame["split"] == "test"]
    n = test["ticker"].map(seen).fillna(0)
    lines = [
        "| company in LoRA cases | n | " + " | ".join(entries) + " |",
        "|---" * (len(entries) + 2) + "|",
    ]
    for label, lo, hi in (
        ("never", 0, 0),
        ("1-9", 1, 9),
        ("10-99", 10, 99),
        ("100+", 100, np.inf),
    ):
        g = test[(n >= lo) & (n <= hi)]
        accs = " | ".join(f"{100 * (g[e] == g['truth']).mean():.1f}" for e in entries)
        lines.append(f"| {label} | {len(g)} | {accs} |")
    return "\n".join(lines)


def score() -> None:
    rows = pd.read_parquet(ROWS)
    inputs = no_model_inputs(rows[rows["split"] != "fit"])
    print(f"stored LLM sector matched on {(inputs['llm'] != '').sum()} rows")
    names = sorted({f.stem.rsplit("-", 1)[0] for f in OUT.glob("laya-*.parquet")})
    views = {
        n: pd.concat(pd.read_parquet(f) for f in OUT.glob(f"{n}-*.parquet"))
        for n in names
    }
    if any(OUT.glob("embed-*.npz")):
        views["embed-lr"] = embed_views(rows)
    frame = inputs.assign(**{"no-model": chain(inputs, None)})
    entries = ["no-model"]
    for name, view in views.items():
        alone = view.set_index("event_id").loc[inputs["event_id"], "sector"].to_numpy()
        frame[f"{name} alone"], frame[name] = alone, chain(inputs, view)
        entries += [name, f"{name} alone"]
    text = report(frame, entries)
    if "ticker" in rows:
        seen = rows[rows["split"] == "fit"]["ticker"][:N_LORA].value_counts()
        text += "\n\n" + by_familiarity(
            frame, seen, [e for e in entries if e != "no-model"]
        )
    (OUT / "report.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    args = sys.argv[1:]
    part = args[args.index("--part") + 1] if "--part" in args else "0/1"
    cmd = args[0] if args else ""
    if cmd == "sample":
        sample()
    elif cmd == "lora-other":
        lora_other()
    elif cmd == "laya":
        run_laya(args[1], args[2], part)
    elif cmd == "embed":
        run_embed(part)
    elif cmd == "score":
        score()
    else:
        sys.exit(__doc__)
