"""Supply-chain gates (plan M2.4).

What is pinned, where an update comes from, and what a tolerated advisory costs:

* a beta parser on the extraction path is not acceptable when a stable one exists;
* the data libraries carry compatibility ceilings, so a major bump arrives as a reviewed
  PR instead of a rebuild;
* every dependency update has one route (Dependabot) and patches merge themselves only
  when CI is green;
* base images are pinned by digest, and a release carries an SBOM of the lock file;
* an unallowlisted advisory fails the audit, and an expired allowlist entry fails it too.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import audit, sbom

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
AUTO_MERGE = ROOT / ".github" / "workflows" / "dependabot-auto-merge.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
ALLOWLIST = ROOT / "security-audit-allowlist.json"


def _dependencies() -> dict[str, str]:
    """The `[project].dependencies` specifiers, name → requirement string."""
    text = PYPROJECT.read_text(encoding="utf-8")
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    out = {}
    for line in block.splitlines():
        match = re.search(r'"([A-Za-z0-9_.-]+)\s*([^"]*)"', line)
        if match:
            out[match.group(1)] = match.group(2).strip()
    return out


# ------------------------------------------------------------------------------- pinning


def test_the_xml_parser_is_on_a_stable_release():
    """A beta parser on the extraction path changes parse behaviour without a changelog."""
    requirement = _dependencies()["lxml"]
    assert not re.search(r"(a|b|rc)\d", requirement), (
        f"lxml is a pre-release: {requirement}"
    )
    assert re.match(r">=\d", requirement), requirement


def test_the_data_libraries_carry_compatibility_ceilings():
    deps = _dependencies()
    for name in ("yfinance", "pandas", "scipy", "spacy"):
        assert "<" in deps[name], f"{name} has no upper bound: {deps[name]}"


def _dockerfiles() -> list[Path]:
    return [
        ROOT / "Dockerfile.api",
        ROOT / "Dockerfile.worker",
        ROOT / "web" / "Dockerfile",
    ]


def test_every_base_image_is_pinned_by_digest():
    problems = []
    for path in _dockerfiles():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("FROM "):
                continue
            image = line.split()[1]
            if image.startswith("ghcr.io/astral-sh/uv"):  # a build tool, version-tagged
                continue
            if "@sha256:" not in image:
                problems.append(f"{path.name}: {image} is not pinned by digest")
    assert not problems, "\n".join(problems)


# ----------------------------------------------------------------------------- updates


def test_one_route_for_every_dependency_update():
    text = DEPENDABOT.read_text(encoding="utf-8")
    for ecosystem in ("uv", "pip", "npm", "github-actions", "docker"):
        assert f'package-ecosystem: "{ecosystem}"' in text, ecosystem
    assert "multi-ecosystem-group: python" in text, (
        "the python ecosystems must group into one PR"
    )
    assert text.count('interval: "weekly"') >= 3
    assert "applies-to: version-updates" in text


def test_only_patch_updates_auto_merge():
    text = AUTO_MERGE.read_text(encoding="utf-8")
    assert "dependabot/fetch-metadata@" in text
    assert "gh pr merge --auto --squash" in text
    # The condition is the whole control: a minor bump must not merge itself.
    assert "steps.meta.outputs.update-type == 'version-update:semver-patch'" in text


def test_a_release_carries_an_sbom():
    text = RELEASE.read_text(encoding="utf-8")
    assert "scripts.sbom" in text and "dist/sbom.cdx.json" in text
    assert "fail_on_unmatched_files: true" in text, (
        "a missing SBOM must fail the release"
    )
    assert "scripts.audit" in text


# -------------------------------------------------------------------------------- SBOM


def _bom(*names: str) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [{"name": name} for name in names],
    }


def test_the_sbom_validator_accepts_a_real_shaped_document():
    sbom._validate(_bom("lxml", "pandas", "yfinance", "fastapi", "spacy"))


@pytest.mark.parametrize(
    "document,message",
    [
        ({"bomFormat": "SPDX", "components": []}, "not a CycloneDX document"),
        (_bom(), "lists no components"),
        (_bom("lxml", "fastapi"), "pandas missing"),
    ],
)
def test_the_sbom_validator_refuses_a_hollow_file(document, message):
    with pytest.raises(AssertionError, match=message):
        sbom._validate(document)


# ------------------------------------------------------------------------------- audit


def _advisory(package="lxml", identifier="GHSA-1"):
    return audit.Advisory(
        source="pip-audit",
        package=package,
        identifier=identifier,
        version="6.0.2",
        fix="6.0.3",
    )


def test_the_committed_allowlist_is_empty_and_valid():
    entries = audit.load_allowlist(ALLOWLIST)
    assert entries == [], (
        "a tolerated advisory needs an owner and an expiry; none is justified yet"
    )


def test_an_unallowlisted_advisory_fails_the_audit(capsys):
    assert audit.run([_advisory()], [], strict=False) == 1
    assert "VULNERABLE" in capsys.readouterr().out


def test_an_allowlisted_advisory_passes_until_it_expires(capsys):
    entry = {
        "id": "GHSA-1",
        "package": "lxml",
        "reason": "no fixed release on 3.14",
        "owner": "@yash",
        "expires": (date.today() + timedelta(days=30)).isoformat(),
    }
    assert audit.run([_advisory()], [entry], strict=True) == 0
    assert "allowlisted" in capsys.readouterr().out

    stale = {**entry, "expires": (date.today() - timedelta(days=1)).isoformat()}
    assert audit.run([_advisory()], [stale], strict=True) == 1
    assert "EXPIRED" in capsys.readouterr().out


def test_an_entry_only_covers_its_own_package_and_identifier():
    entry = {
        "id": "GHSA-1",
        "package": "lxml",
        "reason": "x",
        "owner": "@yash",
        "expires": "2099-01-01",
    }
    assert audit._allows(_advisory(identifier="GHSA-1"), [entry])
    assert not audit._allows(_advisory(identifier="GHSA-2"), [entry])
    assert not audit._allows(_advisory(package="pandas"), [entry])


def test_a_bad_expiry_date_is_refused_not_read_as_never(tmp_path):
    bad = tmp_path / "allow.json"
    bad.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "X",
                        "package": "lxml",
                        "reason": "r",
                        "owner": "@y",
                        "expires": "soon",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        audit.load_allowlist(bad)


def test_an_entry_without_an_owner_or_expiry_is_refused(tmp_path):
    bad = tmp_path / "allow.json"
    bad.write_text(
        json.dumps({"entries": [{"id": "X", "package": "lxml", "reason": "r"}]}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="owner"):
        audit.load_allowlist(bad)
