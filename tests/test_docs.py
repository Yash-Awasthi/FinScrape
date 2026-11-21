"""Every relative link in the docs points at a file that exists.

The cost badge and the DEPLOY pointer both send a reader to `docs/COST.md`; a doc that
moves without its links being updated is a dead end in the UI of the repository.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def relative_links(text: str) -> list[str]:
    links = []
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        links.append(target.split("#", 1)[0])
    return [link for link in links if link]


def test_every_relative_doc_link_resolves():
    missing = []
    for doc in DOCS:
        for link in relative_links(doc.read_text(encoding="utf-8")):
            if not (doc.parent / link).exists():
                missing.append(f"{doc.relative_to(ROOT)} → {link}")
    assert not missing, "broken doc links: " + ", ".join(missing)


def test_the_cost_badge_points_at_the_cost_page():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/COST.md" in readme
    cost = ROOT / "docs" / "COST.md"
    assert cost.is_file()
    # A cost page that does not state a ceiling is decoration, not a statement of limits.
    text = cost.read_text(encoding="utf-8")
    for ceiling in ("500 MB", "$7", "$25", "15 min"):
        assert ceiling in text, ceiling


def test_the_ruff_baseline_matches_the_tree():
    # The baseline is a ratchet: fixing or adding lint debt means regenerating it with
    # `make ruff-baseline` in the same commit, so the file never describes a past tree.
    from scripts import ruff_baseline

    assert ruff_baseline.generate(write=False) == []


def test_the_baseline_names_the_rule_groups_and_directories():
    text = (ROOT / "docs" / "RUFF-BASELINE.md").read_text(encoding="utf-8")
    assert "| Count | Code | Rule | Autofix |" in text
    assert "## By directory" in text
    assert "finscrape/absorbed/" in text


def test_ruff_accepts_the_whole_tree():
    # The gate itself: lint debt is frozen per file in ruff-baseline.toml, so `ruff check .`
    # must pass. A new violation anywhere — or a deleted allowlist line with debt left
    # behind — turns this red.
    import shutil
    import subprocess
    import sys

    ruff = shutil.which("ruff") or sys.executable
    cmd = (
        [ruff, "check", "."]
        if shutil.which("ruff")
        else [sys.executable, "-m", "ruff", "check", "."]
    )
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout[-3000:]


def _ruff_concise(select: str) -> list[str]:
    """Concise output for one code, measured with the frozen allowlist switched off."""
    import shutil
    import subprocess
    import sys

    ruff = (
        [shutil.which("ruff")]
        if shutil.which("ruff")
        else [sys.executable, "-m", "ruff"]
    )
    cmd = [
        *ruff,
        "check",
        ".",
        "--select",
        select,
        "--config",
        "lint.per-file-ignores={}",
        "--output-format",
        "concise",
    ]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    return [
        line for line in done.stdout.splitlines() if ": " in line and ".py:" in line
    ]


def test_f811_only_fires_on_overloads():
    # F811 is allowlisted as a false positive in scripts/ruff_baseline.py, where every hit is
    # an @overload stub. This keeps that claim honest: a genuine redefinition — the kind that
    # silently shadows an earlier function — is not preceded by @overload and fails here.
    import re as _re

    offenders = []
    for line in _ruff_concise("F811"):
        match = _re.match(r"(.+?):(\d+):", line)
        assert match, line
        path, lineno = match.group(1), int(match.group(2))
        source = (ROOT / path).read_text(encoding="utf-8").splitlines()
        window = [row.strip() for row in source[max(0, lineno - 6) : lineno]]
        has_overload = any(row.startswith("@overload") for row in window)
        follows_stub = any(row.endswith("...") for row in window)
        if not (has_overload or follows_stub):
            offenders.append(line)
    assert not offenders, "F811 is no longer only overload stubs:\n" + "\n".join(
        offenders
    )


def test_the_runbook_quotes_the_live_retention_defaults():
    # plan M1.5: the documented window IS the job's window. Moving a default in
    # server/settings.py without the RUNBOOK turns this red.
    from server.settings import Settings

    s = Settings(_env_file=None)
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    section = runbook.split("## 7. Database retention", 1)[1].split("\n## ", 1)[0]
    assert f"(default {s.retention_days})" in section
    assert f"(default {s.event_retention_days})" in section
    assert f"default {int(s.db_max_mb)}" in section


def test_the_eval_gate_is_documented_where_a_model_is_switched():
    # plan M2.1: the 5-point rule lives in DEPLOY.md next to `make llm`, and the run
    # history lives in EVAL.md. A reader must not have to know about CI to obey it.
    deploy = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    assert "docs/EVAL.md" in deploy
    assert "5 points of sector accuracy" in deploy
    assert "scripts/eval_model" in deploy
    ev = (ROOT / "docs" / "EVAL.md").read_text(encoding="utf-8")
    assert "5 points" in ev and "tests/gold/" in ev
