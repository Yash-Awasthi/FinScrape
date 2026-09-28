"""
FinScrape command line — the pieces that need no database.

Usage:
    python main.py trading NVDA                    # multi-agent trading analysis
    python main.py quotes --exchange NSE --symbols RELIANCE TCS
    python main.py devtools list                   # bring-your-own API keys

Ingestion, alerts, portfolio and digests run on Postgres through the API
(`python -m server.main`) and the worker (`python -m worker.main`).
"""

import argparse
import logging
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "app.log")),
    ],
)


def handle_quotes(args):
    """Realtime quotes across every tracked exchange."""
    from finscrape.exchanges import get_global_quotes

    wanted = [(args.exchange.upper(), s) for s in args.symbols]
    quotes = get_global_quotes(wanted)
    if not quotes:
        print("No quotes returned (check exchange code / symbol / network).")
        return
    print(f"\n{'='*60}\n  Global Quotes ({', '.join(q.get('source', '?') for q in quotes.values())})\n{'='*60}")
    for symbol, q in quotes.items():
        price = q.get("price")
        change = q.get("change_pct")
        if price is None:
            print(f"  {symbol:<16} unavailable")
            continue
        arrow = "▲" if (change or 0) > 0 else "▼" if (change or 0) < 0 else "·"
        change_str = f"{change:+.2f}%" if change is not None else "  —"
        print(f"  {symbol:<16} {price:>12} {arrow} {change_str}  [{q.get('source', '?')}]")


def handle_devtools(args):
    """Developer mode: manage API keys for external tools by class."""
    from finscrape import devmode

    cmd = getattr(args, "devtools_cmd", "list") or "list"

    if cmd == "list":
        status = devmode.status()
        print(f"Developer mode: {status['mode'].upper()}   (config: {status['path']})")
        for cls, info in status["classes"].items():
            active = f" → ACTIVE: {info['active']}" if info["active"] else ""
            print(f"\n  {cls}  ({info['label']}){active}")
            print(f"    fields:    {', '.join(info['fields'])}")
            print(f"    providers: {', '.join(info['providers']) or '—'}")
        if status["mode"] != "dev":
            print("\n  Mode is OFF — run `main.py devtools on` to activate dev providers.")
    elif cmd == "on":
        devmode.set_mode("dev")
        print("Developer mode ON — active providers now override env config.")
    elif cmd == "off":
        devmode.set_mode("off")
        print("Developer mode OFF — all dev providers inert.")
    elif cmd == "path":
        print(devmode.config_path())
    elif cmd == "set":
        fields = {}
        for item in args.field:
            if "=" not in item:
                print(f"  [SKIP] malformed --field (need key=value): {item}")
                continue
            key, _, value = item.partition("=")
            fields[key.strip()] = value.strip()
        if not fields:
            print("No --field values given. Example: --field api_key=fc-123")
            return
        result = devmode.set_provider(args.tool_class, args.provider, fields,
                                      activate=not args.no_activate)
        print(f"Saved {result['tool_class']}/{result['provider']} "
              f"(active: {result['active'] or '—'}) with fields: {', '.join(result['fields'])}")
    elif cmd == "test":
        active = devmode.get_active(args.tool_class)
        if not active:
            print(f"No active provider for '{args.tool_class}' "
                  f"(dev mode off, or none set — see `main.py devtools list`)")
            return
        print(f"{args.tool_class} → {active['provider']}: {active['fields']}")


def handle_trading(args):
    """Handle multi-agent trading analysis."""
    from finscrape.trading.pipeline import run_analysis

    print(f"\n{'='*60}")
    print(f"  Multi-Agent Trading Analysis: {args.ticker.upper()}")
    print(f"  Analysts: {', '.join(args.analysts)}")
    print(f"  Debate rounds: {args.debate_rounds} | Risk rounds: {args.risk_rounds}")
    print(f"{'='*60}\n")

    result = run_analysis(
        ticker=args.ticker.upper(),
        trade_date=args.date,
        debate_rounds=args.debate_rounds,
        risk_rounds=args.risk_rounds,
        selected_analysts=tuple(args.analysts),
        save_reports=not args.no_save,
    )

    print(f"{'='*60}")
    print(f"  {result['ticker']} — {result['trade_date']}")
    print(f"  Signal: {result['signal']}")
    print(f"  Duration: {result['duration_seconds']}s")
    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")
    print(f"{'='*60}\n")

    print("--- Final Decision ---")
    print(result["decision"][:2000])
    print()

    if result["errors"]:
        print("--- Errors ---")
        for e in result["errors"]:
            print(f"  {e}")


def main():
    parser = argparse.ArgumentParser(description="FinScrape — Financial News Intelligence Engine")
    subparsers = parser.add_subparsers(dest="command")

    # --- Trading command ---
    trading_parser = subparsers.add_parser("trading", help="Multi-agent trading analysis")
    trading_parser.add_argument("ticker", help="Ticker symbol (e.g. NVDA, AAPL)")
    trading_parser.add_argument("--date", help="Analysis date (YYYY-MM-DD, default: today)")
    trading_parser.add_argument("--debate-rounds", type=int, default=1,
                                help="Bull/bear debate rounds (default: 1)")
    trading_parser.add_argument("--risk-rounds", type=int, default=1,
                                help="Risk team debate rounds (default: 1)")
    trading_parser.add_argument("--no-save", action="store_true",
                                help="Skip saving reports to disk")
    trading_parser.add_argument("--analysts", nargs="+",
                                default=["market", "sentiment", "news", "fundamentals"],
                                choices=["market", "sentiment", "news", "fundamentals"],
                                help="Which analysts to run (default: all)")

    # --- Quotes command (global, all exchanges) ---
    quotes_parser = subparsers.add_parser(
        "quotes", help="Realtime quotes across every tracked exchange (US, IN, CN, EU, ...)"
    )
    quotes_parser.add_argument("--exchange", default="",
                               help="Exchange code: NSE, BSE, SSE, SZSE, HKEX, TSE, LSE, XETRA, ... "
                                    "(empty = US/bare tickers; CN exchanges use keyless native APIs)")
    quotes_parser.add_argument("--symbols", nargs="+", required=True,
                               help="Bare tickers, e.g. --symbols RELIANCE TCS or --symbols 600519 000001")

    # --- Devtools command (developer mode: bring-your-own API keys) ---
    devtools_parser = subparsers.add_parser(
        "devtools",
        help="Developer mode: configure API keys for external tools (search, AI, scraping, ...)",
    )
    devtools_sub = devtools_parser.add_subparsers(dest="devtools_cmd")
    devtools_sub.add_parser("list", help="Show tool classes, their fields and providers")
    devtools_sub.add_parser("path", help="Print the dev-tools config file location")
    devtools_sub.add_parser("on", help="Turn developer mode ON")
    devtools_sub.add_parser("off", help="Turn developer mode OFF")
    devtools_set = devtools_sub.add_parser(
        "set", help="Set a provider under a tool class, e.g. "
        "devtools set news_fetch firecrawl --field api_key=fc-... ; "
        "unknown classes go to `custom`, unknown providers are created on the fly"
    )
    devtools_set.add_argument("tool_class", help="Tool class: ai, web_search, news_fetch, market_data, geo_intel, alerts, custom")
    devtools_set.add_argument("provider", help="Provider name (any name you like)")
    devtools_set.add_argument("--field", action="append", default=[],
                              help="field=value, repeatable (e.g. --field api_key=... --field model=qwen2.5:7b)")
    devtools_set.add_argument("--no-activate", action="store_true", help="Save without making this provider active")
    devtools_test = devtools_sub.add_parser("test", help="Show the active provider for a tool class")
    devtools_test.add_argument("tool_class", help="Tool class to inspect")

    args = parser.parse_args()

    # Developer mode: project active providers onto env before anything reads them.
    from finscrape.devmode import apply_to_env
    apply_to_env()

    if args.command == "trading":
        handle_trading(args)
    elif args.command == "quotes":
        handle_quotes(args)
    elif args.command == "devtools":
        handle_devtools(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
