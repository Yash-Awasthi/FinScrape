"""Weekly digest: markdown + PDF built from the /api/accuracy track record.

Plan m4.3: the digest is written locally by the CLI; delivery is owned elsewhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

DISCLAIMER = (
    "Research and education only. Not financial advice. "
    "Past performance is not indicative of future results."
)

SECTIONS = (
    "Window",
    "Calls scored",
    "Hit rate",
    "By verdict",
    "Best call",
    "Worst call",
    "Disclaimer",
)

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 54
FONT_SIZE = 11
LEADING = 15
WRAP_WIDTH = 88


def _date(value: object) -> str:
    """Date part of an ISO timestamp; the raw string when it is not one."""
    text = str(value)
    return text[:10] if "T" in text else text


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _interval(track_record: dict) -> tuple[float, float] | None:
    ci = track_record.get("ci95")
    if (
        isinstance(ci, (list, tuple))
        and len(ci) == 2
        and all(isinstance(x, (int, float)) for x in ci)
    ):
        return float(ci[0]), float(ci[1])
    return None


def _hit_line(track_record: dict) -> str:
    scored = track_record.get("n", track_record.get("scored", 0)) or 0
    hits = track_record.get("hits", 0) or 0
    rate = track_record.get("hit_rate")
    if rate is None:
        rate = hits / scored if scored else 0.0
    line = f"Hit rate: {_pct(float(rate))} (n={scored}"
    ci = _interval(track_record)
    if ci is None:
        return line + "); interval not recorded"
    return line + f", 95% CI {_pct(ci[0])}-{_pct(ci[1])})"


def _by_verdict(track_record: dict) -> list[str]:
    rows = track_record.get("by_verdict") or {}
    if not isinstance(rows, dict) or not rows:
        return ["not recorded"]
    out = [
        "| Verdict | Hits | n | Hit rate |",
        "| --- | --- | --- | --- |",
    ]
    for verdict in sorted(rows):
        row = rows[verdict] or {}
        hits = row.get("hits", 0)
        total = row.get("total", row.get("n", 0))
        rate = row.get("hit_rate")
        if rate is None:
            rate = hits / total if total else 0.0
        cell = _pct(float(rate))
        if _interval(row) is not None:
            lo, hi = _interval(row) or (0.0, 0.0)
            cell += f" (95% CI {_pct(lo)}-{_pct(hi)})"
        out.append(f"| {verdict} | {hits} | {total} | {cell} |")
    return out


def _call(track_record: dict, key: str, label: str) -> str:
    call = track_record.get(key)
    if not isinstance(call, dict) or not call:
        return f"{label}: not recorded"
    parts = [str(call["subject"])] if call.get("subject") else []
    detail = ", ".join(str(call[k]) for k in ("verdict",) if call.get(k) is not None)
    if call.get("move") is not None:
        detail = (
            f"{detail}, {float(call['move']):+.1f}%"
            if detail
            else (f"{float(call['move']):+.1f}%")
        )
    if detail:
        parts.append(f"({detail})")
    if call.get("at"):
        parts.append(f"at {_date(call['at'])}")
    return f"{label}: " + " ".join(parts) if parts else f"{label}: not recorded"


def build_digest(track_record: dict) -> str:
    """Markdown digest: fixed section order, no claim without its sample."""
    record = track_record or {}
    window = record.get("window") or {}
    start = window.get("from")
    end = window.get("to")
    window_line = (
        f"From {_date(start)} to {_date(end)}" if start or end else "not recorded"
    )
    total = record.get("total", 0) or 0
    scored = record.get("scored", record.get("n", 0)) or 0

    lines = [
        "# Weekly digest",
        "",
        "## Window",
        "",
        window_line,
        "",
        "## Calls scored",
        "",
        f"Total calls: {total}; scored: {scored} (n={scored}).",
        "",
        "## Hit rate",
        "",
        _hit_line(record),
        "",
        "## By verdict",
        "",
        *_by_verdict(record),
        "",
        "## Best call",
        "",
        _call(record, "best", "Best call"),
        "",
        "## Worst call",
        "",
        _call(record, "worst", "Worst call"),
        "",
        "## Disclaimer",
        "",
        DISCLAIMER,
        "",
    ]
    return "\n".join(lines)


def _strip_markdown(md: str) -> list[str]:
    """Readable plain lines: heading marks and table pipes go, text stays."""
    out: list[str] = []
    for raw in md.splitlines():
        line = raw.strip()
        if set(line) <= set("|-: "):
            continue
        while line.startswith("#"):
            line = line[1:]
        line = line.strip().lstrip(">").strip()
        line = line.replace("|", " ")
        for mark in ("**", "__", "`"):
            line = line.replace(mark, "")
        line = " ".join(line.split())
        out.append(line)
    return out


def _wrap(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not line:
            out.append("")
            continue
        out.extend(
            textwrap.wrap(line, width=WRAP_WIDTH, break_long_words=True) or [line]
        )
    return out


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(lines: list[str]) -> bytes:
    top = PAGE_HEIGHT - MARGIN
    body = [f"BT /F1 {FONT_SIZE} Tf {LEADING} TL {MARGIN} {top} Td"]
    for line in lines:
        safe = _escape(line.encode("latin-1", "replace").decode("latin-1"))
        body.append(f"({safe}) Tj T*")
    body.append("ET")
    return ("\n".join(body) + "\n").encode("latin-1")


def _paginate(lines: list[str]) -> list[list[str]]:
    per_page = int((PAGE_HEIGHT - 2 * MARGIN) // LEADING) + 1
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[""]]


def markdown_to_pdf(md: str) -> bytes:
    """Minimal PDF 1.4, Helvetica, one uncompressed stream per page."""
    pages = _paginate(_wrap(_strip_markdown(md)))

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # pages tree, filled in once the page object numbers are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids: list[str] = []
    for index in range(len(pages)):
        page_no = 4 + 2 * index
        kids.append(f"{page_no} 0 R")
        stream = _content(pages[index])
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {page_no + 1} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream"
        )
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    ).encode("ascii")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF"
    ).encode("ascii")
    return bytes(out)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso_week(track_record: dict) -> str:
    window = track_record.get("window") or {}
    stamp = _parse_dt(window.get("to") if isinstance(window, dict) else None)
    year, week, _ = (stamp or datetime.now(UTC)).isocalendar()
    return f"{year}-W{week:02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the weekly digest (markdown + PDF) from a track record."
    )
    parser.add_argument("--fixture", required=True, help="track record JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    try:
        track_record = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"alerts_digest: cannot read fixture: {exc}", file=sys.stderr)
        return 2
    if not isinstance(track_record, dict):
        print(
            "alerts_digest: fixture must be a JSON object (the track record)",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = build_digest(track_record)
    stem = f"digest-{_iso_week(track_record)}"
    md_path = out_dir / f"{stem}.md"
    pdf_path = out_dir / f"{stem}.pdf"
    md_path.write_text(markdown, encoding="utf-8")
    pdf_path.write_bytes(markdown_to_pdf(markdown))
    print(md_path)
    print(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
