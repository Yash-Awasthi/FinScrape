"""
Absorb feature code from the inspiration repos into finscrape/absorbed/.

Copies ONLY the core feature code (packages / source subtrees) of each
reference repo into finscrape/absorbed/<domain>/<repo>/ — no .git, no
docs/tests/CI/build junk, no nested pyproject.toml. Wiring into the real
finscrape modules happens later; this only places the code.

Usage:
    python scripts/absorb_features.py [--dry-run]
"""

from __future__ import annotations

import fnmatch
import shutil
import sys
from pathlib import Path

SRC = Path(r"C:\Users\yasha\PROJECTS\inspiration\fin-scrape")
DST = Path(__file__).resolve().parents[1] / "finscrape" / "absorbed"

DOMAINS = [
    "scraping", "market_data", "gdelt", "social", "nlp", "agents",
    "trading", "quant", "geo", "security", "llm", "infra", "misc",
]

# Directories never worth carrying over, at any depth.
SKIP_DIR_NAMES = {
    ".git", ".github", ".gitlab", ".idea", ".vscode", ".vs", "__pycache__",
    ".venv", "venv", "env", "node_modules", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".tox", ".ipynb_checkpoints", ".eggs", "dist", "build",
    "*.egg-info", ".next", ".turbo", ".vercel", "coverage", ".nyc_output",
}

# File patterns never worth carrying over, at any depth.
SKIP_FILE_PATTERNS = [
    "pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "poetry.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "tsconfig.json", "turbo.json", "biome.json", "eslint.config.*",
    "postcss.config.*", "tailwind.config.*", "next.config.*",
    "vite.config.*", "vitest.*", "playwright.config.*", "wrangler.*",
    "drizzle.config.*", "Dockerfile*", "docker-compose*", ".dockerignore",
    "Makefile", "Justfile", "tox.ini", ".pre-commit-config.yaml",
    ".flake8", ".coveragerc", ".gitignore", ".gitattributes", ".env",
    "LICENSE*", "LICENCE*", "NOTICE", "CONTRIBUTING*", "CODE_OF_*",
    "CHANGELOG*", "SECURITY.md", "CLA.md", "CNAME", "MANIFEST.in",
    "README*", "*.cfg", "appveyor.yml", "azure-pipelines.yml",
    "codecov.yml", "coverage.runsettings", "*.sln", "*.csproj",
    "Directory.Build.props", "Directory.Packages.props", "mkdocs.yml",
    "_config.yml", "_includes", "*.iml",
]

# Repos that stay in inspiration/ + reference/ only, with the reason.
SKIP_REPOS: dict[str, str] = {
    # pip-installable dependencies already wired via pyproject.toml
    "yfinance": "already a pip dependency in pyproject.toml",
    "feedparser": "already a pip dependency in pyproject.toml",
    "spacy": "already a pip dependency in pyproject.toml",
    "curl_cffi": "already a pip dependency (curl-cffi) in pyproject.toml",
    "browserforge": "already a pip dependency in pyproject.toml",
    "lxml": "already a pip dependency in pyproject.toml",
    "asyncpg": "already a pip dependency in pyproject.toml",
    "apscheduler": "already a pip dependency in pyproject.toml",
    "rapidfuzz": "pip-installable utility; vendor only if wiring needs it",
    "dedupe": "pip-installable utility; vendor only if wiring needs it",
    "praw": "pip-installable Reddit client",
    "python-telegram-bot": "pip-installable Telegram client",
    "broadcaster": "pip-installable WebSocket broadcast lib",
    "fastapi_websocket_pubsub": "pip-installable pub/sub lib",
    "pybreaker": "pip-installable circuit breaker",
    "circuitbreaker": "pip-installable circuit breaker",
    "client_python": "pip-installable Prometheus client (already via server deps)",
    "purgatory": "pip-installable rate-limiter utility",
    "openai-python": "pip-installable SDK",
    "scrapling": "already vendored at finscrape/engine/scrapling",
    # platforms / operational infra — wire via pip/npm/docker, never in-tree
    "airbyte": "data platform; wire via docker/pip, not in-tree",
    "airflow": "orchestration platform; wire via pip, not in-tree",
    "dbt-core": "transform platform; wire via pip, not in-tree",
    "meltano": "ELT platform; wire via pip, not in-tree",
    "dify": "LLM app platform; wire via docker, not in-tree",
    "ollama": "Go LLM server; wire via binary/docker",
    "scrapy": "scraping framework; wire via pip, not in-tree",
    "playwright": "browser automation monorepo; wire via pip/npm (patchright dep)",
    "seleniumbase": "browser testing framework; wire via pip",
    "SeleniumBase": "browser testing framework; wire via pip",
    "yt-dlp": "media downloader; wire via pip",
    "qlib": "quant platform (Microsoft); too large, wire via pip if needed",
    "nautilus_trader": "trading platform with Rust core; wire via pip",
    "curl-impersonate": "native C tool; covered by curl-cffi dependency",
    "freqtrade": "trading bot platform; wire via pip, not in-tree",
    "octobot": "trading bot platform; wire via pip, not in-tree",
    "zipline": "legacy quant platform; wire via pip if needed",
    # npm libraries — web/ already consumes these via package.json
    "ai": "npm SDK (vercel/ai); wire via npm",
    "globe.gl": "npm library; web/ already depends on it",
    "react-globe.gl": "npm library; web/ already depends on it",
    "three-globe": "npm library; web/ already depends on it",
    "three-js": "npm library; wire via npm",
    "react-router": "npm library; wire via npm",
    # knowledge-only repos (no code feature to absorb)
    "awesome-ai-in-finance": "curated list — knowledge source only",
    "awesome-financial-nlp": "curated list — knowledge source only",
    "awesome-llm-judges": "curated list — knowledge source only",
    "awesome-trading-agents": "curated list — knowledge source only",
    "awesome-web-scraping": "curated list — knowledge source only",
    "EventExtractionPapers": "paper index — knowledge source only",
    "event-extraction-paper": "paper index — knowledge source only",
    "cameo-codebook": "codebook data — knowledge source only",
    "anti-detect-browser-tools-tech-comparison": "comparison write-up only",
    "AI-Geopol-Projects": "prompt/project collection — knowledge source only",
    # different stack
    "equibles": "C#/.NET stack — no Python/JS feature to absorb",
    "council": "Swift/Xcode iOS app — different stack",
    "finance-query": "Rust stack — no Python/JS feature to absorb",
    "openmarket": "Rust stack — no Python/JS feature to absorb",
    "powertools-lambda-python": "AWS pip library — wire via pip if needed",
    # docs / knowledge only
    "prompt-injection-defenses": "README-only repo — knowledge source",
    "tickertick-api": "skill/docs-only repo — knowledge source",
}

# Domain for each absorbed repo.
DOMAIN: dict[str, str] = {
    # scraping
    "crawl4ai": "scraping", "newspaper": "scraping", "trafilatura": "scraping",
    "readability": "scraping", "fastfeedparser": "scraping", "pyscrappy": "scraping",
    "abrasio-sdk": "scraping",
    # market data
    "edgartools": "market_data", "sec-edgar-downloader": "market_data",
    "sec-edgar-mcp": "market_data", "pycoingecko": "market_data",
    "coingecko_py": "market_data", "reliefweb-python": "market_data",
    "financemcp": "market_data",
    "opennews-mcp": "market_data",
    "maverick-mcp": "market_data", "manifold": "market_data",
    "openinvest": "market_data",
    "clearmarket": "market_data", "unified-marco-markets": "market_data",
    # gdelt
    "py-gdelt": "gdelt", "gdeltpyr": "gdelt", "gdelt-doc-api": "gdelt",
    "gdelt-data-pipeline": "gdelt", "gdelt-events-data-eng-project": "gdelt",
    "gdelt-pulse": "gdelt", "gdelt_distributed_architecture": "gdelt",
    "gdeltdataacquisition": "gdelt",
    # social
    "fintwit-bot": "social", "redditstocksdiscordbot": "social",
    "stocktwits-sentiment": "social", "mslive_public": "social",
    # nlp
    "fingpt": "nlp", "finrobot": "nlp", "deepear": "nlp",
    "FinNews-Sentiment-Stock-Correlation-Analysis": "nlp", "NLP_Fnews": "nlp",
    "Stock-News-Analysis-with-BERT": "nlp",
    "sentiment-analysis-in-event-driven-stock-price-movement-prediction": "nlp",
    "stock-market-news-sentiment-analysis-and-summarization": "nlp",
    # agents / councils
    "trading-agents": "agents", "tradingagents-ashare": "agents",
    "tradingagents-astock": "agents", "tradingagents-mcpmode": "agents",
    "ai-hedge-fund": "agents", "ai-trader": "agents",
    "ai-colosseum-debate": "agents", "ai-investment-advisor": "agents",
    "ai-investment-goatlens": "agents", "autogen-financial-analysis": "agents",
    "financial-analysis--multi-agent-open-source-llm": "agents",
    "berkshire-agent-council": "agents", "claude-council": "agents",
    "claude-equity-research": "agents",
    "debatrix": "agents", "deepfund": "agents", "contesttrade": "agents",
    "cryptoagents": "agents", "llm-deliberate": "agents",
    "multi-agent-debates-langgraph": "agents", "multi-agent-investment": "agents",
    "multi-agent-trading-system": "agents", "multi-agents-debate": "agents",
    "multi_agent_llm_debater": "agents", "geopol-forecast-council": "agents",
    "magi": "agents", "romancer": "agents", "helm-agents": "agents",
    "valuecell": "agents", "verdict": "llm",
    # trading
    "QuantDinger": "trading", "Real-Time-Financial-Analysis-Trading-System": "trading",
    "ai-auto-trader-ahh": "trading", "ai-kline": "trading",
    "alpacatradingagent": "trading", "fenixai_tradingbot": "trading",
    "intelligent-trading-bot": "trading", "invest-alert-bot": "trading",
    "layeredmemorytrader": "trading", "live-trade-bench": "trading",
    "llm_trading_sim": "trading", "lumibot": "trading",
    "orallexa-ai-trading-agent": "trading", "pantheon-trades": "trading",
    "mats": "trading", "hodget": "trading", "pixiu": "trading",
    # quant
    "backtesting.py": "quant", "backtrader": "quant", "alphalens": "quant",
    "empyrical": "quant", "pyfolio": "quant", "quantstats": "quant",
    "pyportfolioopt": "quant", "riskfolio-lib": "quant", "ta": "quant",
    "ta-lib-python": "quant", "pandas-ta-classic": "quant", "talipp": "quant",
    "properscoring": "quant", "reliability-diagrams": "quant",
    "ml-calibration": "quant", "calibration-framework": "quant",
    "python-financial-technical-indicators-pandas": "quant",
    "machine-learning-for-trading": "quant", "artha-analytics": "quant",
    # geo / geopolitical
    "geopolrisk-py": "geo", "geopolitics-ml": "geo", "gpr-zero": "geo",
    "gpr-equity-observatory": "geo", "india-geopolitical-risk-monitor": "geo",
    "real-time-geopolitical-instability-prediction": "geo",
    "war-probability-osint": "geo", "realpolitik": "geo", "crisismap": "geo",
    "tensionr": "geo", "terra-watch": "geo", "trendradar": "geo",
    "scenario-lab": "geo", "global-affairs-simulation-platform": "geo",
    "global-news-intel-platform": "geo", "hermes-geopolitical-market-sim": "geo",
    "moneyfeel-macro-risk-index": "geo", "macropulse": "geo",
    "canairy": "geo", "sentinel": "geo", "situation-monitor": "geo",
    "watchboard": "geo", "worldview-intelligence": "geo",
    "world-intel-mcp": "geo", "world-monitor": "geo", "worldmonitor": "geo",
    "newsglobe": "geo", "news-globe": "geo", "GeoPulseWebApp": "geo",
    "anteroom-oracle": "geo",
    "argus-intel": "geo", "argus-system": "geo", "fusion-center": "geo",
    "taiwan-situation": "geo", "supplychain": "geo", "libcomcat": "geo",
    "mahoraga": "geo", "OracleX": "market_data",
    "homerun": "misc", "neuberg": "misc", "aird": "misc",
    "company_name_to_ticker": "market_data", "georisk-ai": "geo",
    # security
    "advocate": "security", "rebuff": "security", "bipia": "security",
    "open-prompt-injection": "security",
    "pantheon-ssrf-guard": "security", "safeurl-python": "security",
    # llm
    "evals": "llm", "prometheus-eval": "llm", "snowglobe": "llm",
    "finance-skills": "llm",
}

# Repos whose feature is a specific source subtree (app repos etc.).
SUBTREES: dict[str, list[str]] = {
    "trading-agents": ["tradingagents"],
    "ai-hedge-fund": ["hedge_fund"],
    "edgartools": ["edgar"],
    "ta-lib-python": ["talib"],
    "riskfolio-lib": ["riskfolio"],
    "pycoingecko": ["pycoingecko"],
    "sec-edgar-downloader": ["sec_edgar_downloader"],
    "fingpt": ["fingpt", "cloud_test_fingpt.py"],
    "finrobot": ["FinNLP", "configs", "agent_builder_demo.py"],
    "deepear": ["src", "skills", "config"],
    "snowglobe": ["src", "config"],
    "finance-skills": ["plugins", "opencli-plugins"],
    "helm-agents": ["apps"],
    "hodget": ["apps", "packages"],
    "homerun": ["backend", "tools", "gui.py", "extract_md.py"],
    "neuberg": ["client", "server"],
    "artha-analytics": ["backend", "frontend"],
    "openinvest": ["connectors", "__init__.py"],
    "unified-marco-markets": ["backend", "main.py"],
    "clearmarket": ["api", "align_spreads.py", "apply_claim_sigs.py",
                    "apply_exchange_notices.py", "build_resolution_log.py",
                    "canon_extract.py", "canon-registry.json"],
    "magi": ["magi_core", "magi-cli.py", "config.sample.yaml"],
    "romancer": ["romancer", "casebasedreasoner"],
    "supplychain": ["src"],
    "mahoraga": ["src", "dashboard", "migrations", "scripts"],
    "gpr-zero": ["src", "scripts", "data_analysis", "main.py"],
    "OracleX": ["backend", "mcp-server", "agent-skill"],
    "worldmonitor": ["api", "convex"],
    "world-monitor": ["api", "convex", "data"],
    "newsglobe": ["app", "components", "lib"],
    "GeoPulseWebApp": ["app.py", "src", "data"],
    # fixes from first-pass review
    "ai-auto-trader-ahh": ["client", "server"],
    "ai-investment-advisor": [],
    "ai-trader": ["service", "skills"],
    "aird": [],
    "argus-system": ["argus system"],
    "claude-council": ["council-workflow.js", "SKILL.md"],
    "claude-equity-research": ["commands", "config", "scripts"],
    "company_name_to_ticker": ["company_name_to_ticker.py", "company_tickers.json",
                               "company_tickers_exchange.json"],
    "crisismap": [],
    "deepfund": ["src"],
    "financemcp": [],
    "FinNews-Sentiment-Stock-Correlation-Analysis": ["notebooks"],
    "fintwit-bot": [],
    "gdelt-data-pipeline": ["DBT", "airflow_new"],
    "gdelt-events-data-eng-project": ["mage-code", "mage-gdelt"],
    "gdeltdataacquisition": ["src"],
    "gdeltpyr": ["gdelt", "utils"],
    "geopolitics-ml": [],
    "hermes-geopolitical-market-sim": ["dustyfoot"],
    "intelligent-trading-bot": [],
    "llm_trading_sim": ["src", "scripts"],
    "macropulse": ["src", "config"],
    "mats": [],
    "maverick-mcp": [],
    "multi-agent-trading-system": ["code.ipynb"],
    "multi_agent_llm_debater": ["prompts", "MultiLLM Debate.ipynb",
                                "OLLAMA EDA, Test Scripts.ipynb"],
    "NLP_Fnews": [],
    "news-globe": ["index.html"],
    "pandas-ta-classic": ["pandas_ta_classic"],
    "pantheon-trades": [],
    "pixiu": ["notebooks", "requirements.txt"],
    "prometheus-eval": ["eval", "libs"],
    "pyportfolioopt": ["pypfopt"],
    "QuantDinger": [],
    "readability": ["Readability.js", "Readability-readerable.js", "JSDOMParser.js"],
    "Real-Time-Financial-Analysis-Trading-System": [],
    "real-time-geopolitical-instability-prediction": ["src", "model"],
    "realpolitik": [],
    "rebuff": ["python-sdk", "server"],
    "scenario-lab": ["adapters"],
    "stock-market-news-sentiment-analysis-and-summarization":
        ["NLP_Full_Code_Notebook.ipynb", "stock_news.csv", "PROJECT_DESCRIPTION.md"],
    "terra-watch": ["index.html", "cesium", "assets"],
    "valuecell": ["python", "frontend"],
    "watchboard": ["src", "trackers", "public", "worker", "tools"],
}


def norm(name: str) -> str:
    return (name.lower().replace("-", "_").replace(".", "_")
            .removesuffix("_py"))


def make_ignore(dst_root: Path):
    """Build a shutil.ignore_patterns-style filter."""

    def ignore(directory: str, entries: list[str]) -> list[str]:
        skipped = []
        for entry in entries:
            if entry in SKIP_DIR_NAMES:
                skipped.append(entry)
                continue
            if any(fnmatch.fnmatch(entry, pat) for pat in SKIP_DIR_NAMES):
                skipped.append(entry)
                continue
            if any(fnmatch.fnmatch(entry, pat) for pat in SKIP_FILE_PATTERNS):
                skipped.append(entry)
                continue
        return skipped

    return ignore


def _force_remove(func, path, exc):
    """shutil.rmtree onexc handler: clear the read-only bit git leaves on pack files."""
    import os
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def copy_subset(src_dir: Path, dst_dir: Path, only: set[str] | None = None) -> tuple[int, int]:
    """Copy src_dir into dst_dir applying junk filters.

    If `only` is given, copy just those top-level entries (files or dirs).
    Returns (files_copied, bytes_copied).
    """
    files = 0
    nbytes = 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    ignore = make_ignore(dst_dir)
    entries = only if only else [e.name for e in src_dir.iterdir()]
    for entry in entries:
        if entry in SKIP_DIR_NAMES:
            continue
        if any(fnmatch.fnmatch(entry, pat) for pat in SKIP_DIR_NAMES):
            continue
        if any(fnmatch.fnmatch(entry, pat) for pat in SKIP_FILE_PATTERNS):
            continue
        s = src_dir / entry
        if not s.exists():
            continue
        d = dst_dir / entry
        if s.is_dir():
            if d.exists():
                shutil.rmtree(d, onexc=_force_remove)
            shutil.copytree(s, d, ignore=ignore, dirs_exist_ok=True,
                            ignore_dangling_symlinks=True)
            for p in d.rglob("*"):
                if p.is_file():
                    files += 1
                    nbytes += p.stat().st_size
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            files += 1
            nbytes += s.stat().st_size
    return files, nbytes


def detect_subtrees(repo: Path) -> list[str] | None:
    """Auto-detect the feature subtree(s) of a repo.

    Returns a list of top-level entries to copy, [] for a full root copy,
    or None when detection fails (needs review).
    """
    # src/ layout: copy the package(s) inside src/
    src = repo / "src"
    if src.is_dir():
        spkgs = [d for d in src.iterdir()
                 if d.is_dir() and ((d / "__init__.py").exists() or (d / "__init__.pyx").exists())]
        if len(spkgs) == 1:
            return [f"src/{spkgs[0].name}"]
        matches = [d for d in spkgs if norm(d.name) == norm(repo.name)]
        if matches:
            return [f"src/{matches[0].name}"]

    pkgs = [d for d in repo.iterdir()
            if d.is_dir() and not d.name.startswith(".") and (d / "__init__.py").exists()]
    if pkgs:
        matches = [d for d in pkgs if norm(d.name) == norm(repo.name)]
        if len(matches) == 1:
            return [matches[0].name]
        if len(pkgs) == 1:
            return [pkgs[0].name]
        if matches:
            return [m.name for m in matches]

    # App-ish repos: copy everything (junk-filtered).
    app_markers = ("main.py", "app.py", "manage.py", "run.py", "app", "backend")
    if any((repo / m).exists() for m in app_markers) or any(repo.glob("*.py")):
        return []
    return None


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not SRC.is_dir():
        print(f"source missing: {SRC}")
        return 1

    rows: list[tuple[str, str, str, int, str]] = []  # repo, domain, action, files, note
    review: list[str] = []

    repos = sorted(d for d in SRC.iterdir() if d.is_dir())
    for repo in repos:
        name = repo.name
        if name in SKIP_REPOS:
            rows.append((name, "-", f"SKIPPED: {SKIP_REPOS[name]}", 0, ""))
            continue
        domain = DOMAIN.get(name)
        if domain is None:
            review.append(name)
            rows.append((name, "?", "REVIEW: no domain mapping", 0, ""))
            continue

        explicit = SUBTREES.get(name)
        if explicit is not None:
            entries = explicit
            action = "subtrees"
        else:
            detected = detect_subtrees(repo)
            if detected is None:
                review.append(name)
                rows.append((name, domain, "REVIEW: auto-detect failed", 0, ""))
                continue
            entries = detected
            action = "package" if entries and not entries[0].startswith("src/") and len(entries) == 1 and (repo / entries[0]).is_dir() else ("src-layout" if entries and entries[0].startswith("src/") else "root")

        dest = DST / domain / name
        note = ""
        if dry:
            files = 0
        else:
            # wipe any stale dest from a previous run (junk filters may have
            # changed between runs — never trust what's already there)
            if dest.exists():
                shutil.rmtree(dest, onexc=_force_remove)
            only = set(entries) if action != "root" else None
            files, nbytes = copy_subset(repo, dest, only=only)
            if files == 0:
                review.append(name)
                rows.append((name, domain, "REVIEW: nothing copied", 0, ""))
                continue
            if nbytes > 200 * 1024 * 1024:
                note = f"large ({nbytes // (1024*1024)} MB)"
        rows.append((name, domain, action, files, note))

    # Package scaffolding so later wiring can import finscrape.absorbed.*
    if not dry:
        for base in [DST] + [DST / d for d in DOMAINS]:
            base.mkdir(parents=True, exist_ok=True)
            init = base / "__init__.py"
            if not init.exists():
                init.write_text("")

    # Report
    print(f"{'repo':<58} {'domain':<12} {'action':<12} files  note")
    print("-" * 110)
    for name, domain, action, files, note in rows:
        print(f"{name:<58} {domain:<12} {action:<12} {files:<6} {note}")
    print("-" * 110)
    copied = sum(r[3] for r in rows)
    print(f"repos: {len(repos)}  copied files: {copied}  review: {len(review)}")
    if review:
        print("NEEDS REVIEW:", ", ".join(review))

    if not dry:
        lines = [
            "# Absorbed Features",
            "",
            "Feature code extracted from the reference repos (inspiration/fin-scrape,",
            "mirrored in reference/). Code only — no git history, docs, tests or build",
            "config. Each repo lands in its domain; wiring into the real finscrape",
            "modules happens next.",
            "",
            "| Repo | Domain | Action | Files | Note |",
            "|---|---|---|---|---|",
        ]
        for name, domain, action, files, note in rows:
            lines.append(f"| {name} | {domain} | {action} | {files} | {note} |")
        (DST / "ABSORBED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {DST / 'ABSORBED.md'}")

    return 0 if not review else 2


if __name__ == "__main__":
    sys.exit(main())
