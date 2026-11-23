"""Fail before `docker compose up` if a published host port is already spoken for.

The Nexus stack on this workstation owns 8000, 5432, 6379, 3000 and 4173 (plan
Appendix D). FinScrape's compose defaults stay off them (8010 API, 5433 Postgres, 6380
Redis, 8080 web), but every port is overridable through `.env`, which is exactly how a
collision comes back. Parsing the compose file is cheaper and more exact than trying to
bind and reading the OS error.

    python -m scripts.check_ports              # check docker-compose.yml
    python -m scripts.check_ports --file ...   # check another file
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Ports the Nexus Docker stack owns. Never publish FinScrape on these.
RESERVED = {
    8000: "Nexus API",
    5432: "Nexus Postgres",
    6379: "Nexus Redis",
    3000: "Nexus UI",
    4173: "Nexus preview",
}

# `- "8010:8000"`, `- "127.0.0.1:${WORLDFIN_PG_HOST_PORT:-5433}:5432"`,
# and the long form `published: 8010` / `- 8010:8000` (unquoted) all appear in the wild.
_SHORT = re.compile(
    r"""^\s*-\s*["']?
        (?:[0-9a-zA-Z_.*]*:)?              # optional bind address
        (?:\$\{[A-Z_0-9]+:-)?              # optional ${VAR:- prefix
        (\d{2,5})                          # host port
        \}?
        :(\d{2,5})                         # container port
        (?:/[a-z]+)?["']?\s*$""",
    re.VERBOSE,
)
_PUBLISHED = re.compile(r"^\s*published:\s*[\"']?(\d{2,5})", re.MULTILINE)


def host_ports(text: str) -> list[int]:
    ports: list[int] = []
    for line in text.splitlines():
        match = _SHORT.match(line)
        if match:
            ports.append(int(match.group(1)))
    ports.extend(int(value) for value in _PUBLISHED.findall(text))
    return ports


def check(text: str, reserved: dict[int, str] = RESERVED) -> list[str]:
    problems: list[str] = []
    ports = host_ports(text)
    if not ports:
        problems.append(
            "no published host ports found; the parser has drifted from the file"
        )
    for port in sorted(set(ports)):
        if port in reserved:
            problems.append(f"host port {port} is reserved for {reserved[port]}")
    duplicates = {p for p in ports if ports.count(p) > 1}
    for port in sorted(duplicates):
        problems.append(f"host port {port} is published more than once")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="docker-compose.yml")
    args = parser.parse_args(argv)
    path = Path(args.file)
    problems = check(path.read_text(encoding="utf-8"))
    if problems:
        print(f"ports-check: {path} would collide")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"ports-check: {path} publishes no reserved port ({len(host_ports(path.read_text(encoding='utf-8')))} checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
