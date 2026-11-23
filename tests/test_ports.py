"""The compose file never publishes a port another stack owns (plan M3.5)."""

from __future__ import annotations

from scripts.check_ports import RESERVED, check, host_ports

COMPOSE = """
services:
  db:
    ports:
      - "127.0.0.1:${WORLDFIN_PG_HOST_PORT:-5433}:5432"
  api:
    ports:
      - "${WORLDFIN_API_HOST_PORT:-8010}:8000"
  web:
    ports:
      - "8080:80"
  cache:
    ports:
      - "${WORLDFIN_REDIS_HOST_PORT:-6380}:6379"
"""


def test_the_shipped_compose_is_clean() -> None:
    from pathlib import Path

    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert check(text) == []
    assert sorted(host_ports(text)) == [5433, 6380, 8010, 8080]


def test_a_reserved_port_fails_even_when_it_is_a_default() -> None:
    problems = check('    - "${API_PORT:-8000}:8000"')
    assert any("8000" in p and "Nexus API" in p for p in problems)


def test_a_reserved_port_fails_in_the_long_form() -> None:
    problems = check("    ports:\n      published: 5432\n")
    assert any("5432" in p for p in problems)


def test_a_duplicate_is_reported() -> None:
    problems = check('    - "8010:8000"\n    - "8010:8001"')
    assert any("more than once" in p for p in problems)


def test_the_parser_does_not_claim_to_see_ports_it_did_not() -> None:
    # A compose rewrite that moves to `expose:` or a different syntax must not pass
    # silently: "no ports found" is a failure, not a clean run.
    assert host_ports("services:\n  api:\n    expose: [8000]\n") == []
    assert check("services:\n  api:\n    expose: [8000]\n") != []


def test_the_reserved_set_matches_the_plan() -> None:
    assert RESERVED == {
        8000: "Nexus API",
        5432: "Nexus Postgres",
        6379: "Nexus Redis",
        3000: "Nexus UI",
        4173: "Nexus preview",
    }
