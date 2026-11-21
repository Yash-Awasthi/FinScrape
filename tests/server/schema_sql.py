"""What the migration SQL says the schema is, and what the code says it writes.

Two readers, both stdlib-only:

* `created_columns()` — table → columns, from `server/migrations/*.sql`
  (`CREATE TABLE`, `ALTER TABLE … ADD COLUMN`, `CREATE UNIQUE INDEX … (col)` is ignored).
* `insert_targets()` — (table, columns) pairs, from the `INSERT INTO t (a, b)` statements in
  `server/` and `worker/`, including ones built with an f-string column list.

`drift()` compares them. A migration that renames or drops a column the code still writes
is exactly the failure that only shows up in production, so it is checked here while it is
still a diff.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "server" / "migrations"
CODE_DIRS = (ROOT / "server", ROOT / "worker")

# Columns every app may write without the migration naming them.
_IGNORED_COLUMNS = {"id", "created_at", "updated_at"}

_CREATE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_ALTER = re.compile(
    r"alter\s+table\s+(?:if\s+exists\s+)?([a-z_][a-z0-9_]*)\s+add\s+column\s+"
    r"(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
_DROP_TABLE = re.compile(
    r"drop\s+table\s+(?:if\s+exists\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_DROP = re.compile(
    r"alter\s+table\s+([a-z_][a-z0-9_]*)\s+drop\s+column\s+(?:if\s+exists\s+)?([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
# A column definition is `name type …`; constraint clauses start with a keyword.
_CONSTRAINT = re.compile(
    r"^\s*(primary|foreign|unique|check|constraint|exclude|like)\b", re.IGNORECASE
)
_COLUMN_NAME = re.compile(r"^\s*\"?([a-z_][a-z0-9_]*)\"?\s+\S", re.IGNORECASE)

_INSERT = re.compile(r"insert\s+into\s+([a-z_][a-z0-9_]*)\s*\(([^)]*)\)", re.IGNORECASE)


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def created_columns(migrations: Path = MIGRATIONS) -> dict[str, list[str]]:
    """table → columns created across the whole series, in file order."""
    tables: dict[str, list[str]] = {}
    for path in sorted(migrations.glob("[0-9]*.sql")):
        sql = _strip_comments(path.read_text(encoding="utf-8"))
        for match in _CREATE.finditer(sql):
            table = match.group(1).lower()
            body = match.group(2)
            columns = tables.setdefault(table, [])
            for line in _split_top_level(body):
                if _CONSTRAINT.match(line):
                    continue
                name = _COLUMN_NAME.match(line)
                if name:
                    column = name.group(1).lower()
                    if column not in columns:
                        columns.append(column)
        for match in _ALTER.finditer(sql):
            table, column = match.group(1).lower(), match.group(2).lower()
            columns = tables.setdefault(table, [])
            if column not in columns:
                columns.append(column)
        for match in _DROP.finditer(sql):
            table, column = match.group(1).lower(), match.group(2).lower()
            if table in tables and column in tables[table]:
                tables[table].remove(column)
        # A table added and later dropped is not part of the schema that ships.
        for match in _DROP_TABLE.finditer(sql):
            tables.pop(match.group(1).lower(), None)
    return tables


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas that are not inside parentheses."""
    parts, depth, current = [], 0, []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part for part in parts if part.strip()]


def insert_targets(
    dirs: tuple[Path, ...] = CODE_DIRS,
) -> list[tuple[str, list[str], str]]:
    """(table, columns, where) for every literal INSERT in the server and worker code."""
    out = []
    for directory in dirs:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _INSERT.finditer(text):
                columns = [
                    token.strip().strip('"').lower()
                    for token in match.group(2).split(",")
                    if token.strip() and not token.strip().startswith(("{", "f", "'"))
                ]
                if not columns or any("{" in column for column in columns):
                    continue
                out.append(
                    (match.group(1).lower(), columns, str(path.relative_to(ROOT)))
                )
    return out


def drift(tables: dict[str, list[str]] | None = None) -> list[str]:
    """Insert targets whose table or columns the migrations do not create."""
    tables = tables if tables is not None else created_columns()
    problems = []
    for table, columns, where in insert_targets():
        if table not in tables:
            problems.append(
                f"{where}: INSERT INTO {table} — no migration creates that table"
            )
            continue
        known = tables[table]
        for column in columns:
            if column in _IGNORED_COLUMNS or column in known:
                continue
            problems.append(
                f"{where}: INSERT INTO {table} writes column {column!r}, "
                f"which no migration creates (have: {', '.join(known)})"
            )
    return problems
