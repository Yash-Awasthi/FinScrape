"""Fail on a known vulnerability, unless the exception has not expired (plan M2.4).

    python -m scripts.audit                 # pip-audit + npm audit
    python -m scripts.audit --pip-only
    python -m scripts.audit --strict        # also fail on an expired allowlist entry

Two behaviours matter here and both are the point of the file:

* a **new** advisory fails the run, so the fix lands before the deploy does;
* an **allowlist entry has an expiry**, so a tolerated advisory is a scheduled decision,
  not a comment nobody revisits. `--strict` turns "this exception is past its date" into a
  failure, and CI runs it that way: the allowlist cannot quietly become permanent.

Format of `security-audit-allowlist.json`:

    {"entries": [
      {"id": "GHSA-xxxx", "package": "lxml", "reason": "no fixed release on 3.14",
       "owner": "@yash", "expires": "2026-12-31"}
    ]}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "security-audit-allowlist.json"
WEB = ROOT / "web"


@dataclass
class Advisory:
    source: str
    package: str
    identifier: str
    version: str
    fix: str

    def label(self) -> str:
        return f"{self.source}: {self.package} {self.version} {self.identifier}"


def load_allowlist(path: Path = ALLOWLIST) -> list[dict]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    for entry in entries:
        for field in ("id", "package", "reason", "owner", "expires"):
            assert field in entry, f"allowlist entry missing {field!r}: {entry}"
        date.fromisoformat(
            entry["expires"]
        )  # a bad date must not read as "never expires"
    return entries


def expired(entries: list[dict], today: date | None = None) -> list[dict]:
    today = today or datetime.now(UTC).date()
    return [e for e in entries if date.fromisoformat(e["expires"]) < today]


def _allows(advisory: Advisory, entries: list[dict]) -> bool:
    for entry in entries:
        if entry["package"].lower() != advisory.package.lower():
            continue
        if entry["id"] == advisory.identifier or entry["id"] == "*":
            return True
    return False


# ------------------------------------------------------------------------------ pip-audit


def pip_advisories() -> list[Advisory]:
    """`pip-audit` over the exported lock file. Missing tool is a failure, not a skip."""
    uvx = shutil.which("uvx")
    if not uvx:
        raise SystemExit("uvx not found: pip-audit runs through it")
    out = ROOT / "dist" / "pip-audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    requirements = out.parent / "audit-requirements.txt"
    export = subprocess.run(
        [
            shutil.which("uv") or "uv",
            "export",
            "--format",
            "requirements-txt",
            "--no-dev",
            "--no-hashes",
            "--group",
            "server",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if export.returncode != 0:
        raise SystemExit(f"uv export failed:\n{export.stdout}\n{export.stderr}")
    try:
        result = subprocess.run(
            [
                uvx,
                "pip-audit",
                "--requirement",
                str(requirements),
                "--format",
                "json",
                "--output",
                str(out),
                "--progress-spinner",
                "off",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        requirements.unlink(missing_ok=True)
    if result.returncode not in (0, 1):
        raise SystemExit(f"pip-audit failed to run:\n{result.stdout}\n{result.stderr}")
    document = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else []
    advisories = []
    for entry in document.get(
        "dependencies", document if isinstance(document, list) else []
    ):
        for vuln in entry.get("vulns", []):
            advisories.append(
                Advisory(
                    source="pip-audit",
                    package=entry.get("name", "?"),
                    identifier=vuln.get("id", "?"),
                    version=entry.get("version", "?"),
                    fix=", ".join(vuln.get("fix_versions", [])) or "none",
                )
            )
    return advisories


# ----------------------------------------------------------------------------- npm audit


def npm_advisories() -> list[Advisory]:
    if not (WEB / "package-lock.json").is_file():
        return []
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found: `npm audit --omit=dev` is part of the gate")
    result = subprocess.run(
        [npm, "audit", "--omit=dev", "--json"],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(f"npm audit failed to run:\n{result.stdout}\n{result.stderr}")
    try:
        document = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []
    advisories = []
    for name, vuln in (document.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if not isinstance(via, dict):
                continue  # a string `via` is a parent package, reported on its own line
            advisories.append(
                Advisory(
                    source="npm-audit",
                    package=name,
                    identifier=str(via.get("url") or via.get("source") or "advisory"),
                    version=vuln.get("range", "?"),
                    fix=", ".join(vuln.get("fixAvailable", {}).get("name", "")),
                )
            )
    return advisories


def run(advisories: list[Advisory], entries: list[dict], strict: bool) -> int:
    allowed = [a for a in advisories if _allows(a, entries)]
    unallowed = [a for a in advisories if not _allows(a, entries)]
    for advisory in allowed:
        print(f"  allowlisted  {advisory.label()}")
    for advisory in unallowed:
        print(f"  VULNERABLE   {advisory.label()}  (fix: {advisory.fix})")
    stale = expired(entries)
    for entry in stale:
        print(
            f"  EXPIRED      {entry['id']} ({entry['package']}) — expired "
            f"{entry['expires']}, owner {entry['owner']}"
        )
    if unallowed:
        print(
            f"audit: FAIL — {len(unallowed)} unallowlisted advisor{'y' if len(unallowed) == 1 else 'ies'}"
        )
        return 1
    if stale and strict:
        print(
            f"audit: FAIL — {len(stale)} expired allowlist entr{'y' if len(stale) == 1 else 'ies'}"
        )
        return 1
    print(
        f"audit: {len(advisories)} advisor{'y' if len(advisories) == 1 else 'ies'}, "
        f"{len(allowed)} allowlisted, {len(stale)} expired"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pip-only", action="store_true", help="skip the npm half")
    parser.add_argument("--npm-only", action="store_true", help="skip the pip half")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail when an allowlist entry is expired",
    )
    parser.add_argument("--allowlist", default=str(ALLOWLIST), help="allowlist path")
    args = parser.parse_args(argv)

    entries = load_allowlist(Path(args.allowlist))
    advisories: list[Advisory] = []
    if not args.npm_only:
        advisories += pip_advisories()
    if not args.pip_only:
        advisories += npm_advisories()
    return run(advisories, entries, args.strict)


if __name__ == "__main__":
    sys.exit(main())
