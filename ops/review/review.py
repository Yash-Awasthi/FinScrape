"""One review per quarter: dependencies, licences and model quality.

The age check makes a skipped quarter fail CI instead of passing silently.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import re
import sys
import tomllib
from pathlib import Path

START = "<!-- review:start -->"
END = "<!-- review:end -->"

# A licence line containing any of these needs a human keep/replace decision.
REVIEW_RE = re.compile(
    r"(?<![A-Za-z])(?:AGPL|LGPL|GPL|MPL|EPL|CDDL|SSPL)(?:v?\d+(?:\.\d+)?)?(?![A-Za-z])",
    re.IGNORECASE,
)

FAMILIES = (
    ("AGPL", "agpl"),
    ("LGPL", "lgpl"),
    ("GPL", "gpl"),
    ("MPL", "mpl"),
    ("EPL", "epl"),
    ("CDDL", "cddl"),
    ("SSPL", "sspl"),
    ("Apache-2.0", "apache"),
    ("MIT", "mit"),
    ("BSD", "bsd"),
    ("ISC", "isc"),
    ("PSF", "python software foundation"),
    ("PSF", "psf"),
    ("Unlicense", "unlicense"),
    ("Zlib", "zlib"),
    ("Artistic", "artistic"),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_locked_packages(root: Path) -> list[dict[str, str]]:
    data = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    return [
        {"name": str(p.get("name", "")), "version": str(p.get("version", ""))}
        for p in data.get("package", [])
        if p.get("name")
    ]


def licence_of(name: str) -> str:
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    licence = (meta.get("License") or "").strip()
    if licence and licence.upper() != "UNKNOWN":
        return licence
    classifiers = [
        c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    return "unknown"


def compact(licence: str) -> str:
    """One line, so a full licence text does not flood the table."""
    first = licence.strip().splitlines()[0].strip() if licence.strip() else ""
    collapsed = re.sub(r"\s+", " ", first)
    return collapsed if len(collapsed) <= 120 else collapsed[:117] + "..."


def family_of(licence: str) -> str:
    if licence in {"not-installed", "unknown"}:
        return licence
    name = compact(licence).lower()
    for family, needle in FAMILIES:
        if needle in name:
            return family
    return "custom-text"


def scan_licences(packages: list[dict[str, str]]) -> dict:
    families: dict[str, int] = {}
    needs_review: list[dict[str, str]] = []
    for package in packages:
        licence = licence_of(package["name"])
        family = family_of(licence)
        families[family] = families.get(family, 0) + 1
        if licence == "unknown" or REVIEW_RE.search(compact(licence)):
            needs_review.append({**package, "licence": compact(licence)})
    ordered = dict(sorted(families.items(), key=lambda kv: (-kv[1], kv[0])))
    return {
        "families": ordered,
        "needs_review": sorted(needs_review, key=lambda p: p["name"]),
    }


def markdown_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def parse_eval_rows(text: str) -> dict[str, dict[str, str]]:
    newest: dict[str, dict[str, str]] = {}
    in_table = False
    for cells in markdown_rows(text):
        if len(cells) >= 3 and cells[:3] == ["Model", "Prompt", "Date"]:
            in_table = True
            continue
        if not in_table or len(cells) < 3 or not cells[0]:
            continue
        model, prompt, date = cells[0], cells[1], cells[2]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        current = newest.get(model)
        if current is None or date > current["date"]:
            newest[model] = {
                "prompt": prompt,
                "date": date,
                "sector_accuracy": cells[3] if len(cells) > 3 else "",
                "json_validity": cells[4] if len(cells) > 4 else "",
                "verdict_agreement": cells[5] if len(cells) > 5 else "",
            }
    return dict(sorted(newest.items()))


def parse_deploy_models(text: str) -> list[str]:
    models: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower() == "## choosing the model"
            continue
        if not in_section:
            continue
        match = re.match(r"\|\s*`([^`]+)`", line)
        if match and match.group(1) not in models:
            models.append(match.group(1))
    return models


def build_report(root: Path) -> dict:
    packages = read_locked_packages(root)
    licences = scan_licences(packages)
    eval_rows = parse_eval_rows((root / "docs" / "EVAL.md").read_text(encoding="utf-8"))
    configured = parse_deploy_models((root / "docs" / "DEPLOY.md").read_text(encoding="utf-8"))
    missing = [m for m in configured if m not in eval_rows]
    return {
        "generated": dt.date.today().isoformat(),
        "locked_packages": len(packages),
        "licence_families": licences["families"],
        "needs_review": licences["needs_review"],
        "models": eval_rows,
        "configured_models": configured,
        "models_without_eval": missing,
    }


def model_summary(rows: dict[str, dict[str, str]], sep: str = "<br>") -> str:
    if not rows:
        return "none"
    return sep.join(
        f"{name}: {row['sector_accuracy']} sector, {row['json_validity']} JSON, {row['date']}"
        for name, row in rows.items()
    )


def needs_review_summary(items: list[dict[str, str]], sep: str = "<br>") -> str:
    if not items:
        return "none"
    return sep.join(f"{p['name']} ({p['licence']})" for p in items)


def families_summary(families: dict[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in families.items())


def build_block(report: dict, reviewed: str) -> str:
    families = report["licence_families"]
    missing = ", ".join(report["models_without_eval"]) or "none"
    lines = [
        f"Reviewed: {reviewed}",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Locked packages | {report['locked_packages']} |",
        f"| Licence families | {families_summary(families)} |",
        f"| Packages needing review | {needs_review_summary(report['needs_review'])} |",
        f"| Newest eval row per model | {model_summary(report['models'])} |",
        f"| Configured models with no eval row | {missing} |",
    ]
    return "\n".join(lines)


def extract_block(text: str) -> str:
    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < 0 or end <= start:
        raise ValueError(f"markers {START} / {END} not found")
    return text[start + len(START) : end]


def body_of(block: str) -> list[str]:
    lines = [line.rstrip() for line in block.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[0].startswith("Reviewed:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def reviewed_date(block: str) -> dt.date | None:
    for line in block.splitlines():
        if line.strip():
            match = re.fullmatch(r"Reviewed:\s*(\d{4}-\d{2}-\d{2})", line.strip())
            return dt.date.fromisoformat(match.group(1)) if match else None
    return None


def write_block(doc: Path, block: str) -> None:
    text = doc.read_text(encoding="utf-8")
    extract_block(text)
    start = text.index(START) + len(START)
    end = text.index(END)
    doc.write_text(
        text[:start] + "\n" + block + "\n" + text[end:], encoding="utf-8", newline="\n"
    )


# Rows derived from the installed environment (licence metadata) differ by platform and
# by resolution, so the drift check compares only what the repository itself produces.
SNAPSHOT_PREFIXES = ("| Licence families |", "| Packages needing review |")


def comparable(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.startswith(SNAPSHOT_PREFIXES)]


def check(doc: Path, report: dict, max_age_days: int) -> int:
    text = doc.read_text(encoding="utf-8")
    try:
        block = extract_block(text)
    except ValueError as exc:
        print(f"review: {doc}: {exc}", file=sys.stderr)
        return 1
    expected = build_block(report, report["generated"])
    if comparable(body_of(block)) != comparable(body_of(expected)):
        print(
            "review: the block is stale; run: python ops/review/review.py --write",
            file=sys.stderr,
        )
        return 1
    reviewed = reviewed_date(block)
    if reviewed is None:
        print("review: no valid 'Reviewed: YYYY-MM-DD' line", file=sys.stderr)
        return 1
    age = (dt.date.today() - reviewed).days
    if max_age_days >= 0 and age > max_age_days:
        print(
            f"review: the review date {reviewed} is {age} days old, over the {max_age_days}"
            " day limit; run: python ops/review/review.py --write",
            file=sys.stderr,
        )
        return 1
    return 0


def print_summary(report: dict) -> None:
    print(f"locked packages: {report['locked_packages']}")
    print(f"licence families: {families_summary(report['licence_families'])}")
    print(f"needs review: {needs_review_summary(report['needs_review'], '; ')}")
    print(f"models: {model_summary(report['models'], '; ')}")
    print(
        f"configured models with no eval row: "
        f"{', '.join(report['models_without_eval']) or 'none'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=repo_root())
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print the full report as JSON")
    mode.add_argument("--write", action="store_true", help="rewrite the REVIEW.md block")
    mode.add_argument("--check", action="store_true", help="fail when stale or overdue")
    parser.add_argument("--doc", type=Path, default=None, help="doc checked by --check")
    parser.add_argument("--max-age-days", type=int, default=100)
    args = parser.parse_args(argv)

    root = args.repo.resolve()
    report = build_report(root)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if args.write:
        doc = args.doc or root / "docs" / "REVIEW.md"
        write_block(doc, build_block(report, report["generated"]))
        print(f"review: wrote {doc}")
        return 0
    if args.check:
        doc = args.doc or root / "docs" / "REVIEW.md"
        return check(doc, report, args.max_age_days)
    print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
