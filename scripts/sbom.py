"""Write a CycloneDX SBOM for the versions this repo actually ships (plan M2.4).

    python -m scripts.sbom              # dist/sbom.cdx.json
    python -m scripts.sbom --check      # generate and validate, same thing

The SBOM describes the *lock file*, not the current interpreter: `uv export` turns
`uv.lock` into a requirements file and CycloneDX reads that. (`cyclonedx-py environment`
describes the interpreter it runs in — under uvx that is CycloneDX's own dependencies, 32
packages and no pandas.)

A release attaches the file (`.github/workflows/release.yml`), which is what makes "which
lxml shipped on 12 March" answerable without a rebuild.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "dist" / "sbom.cdx.json"
# The generator ships in a different distribution than the command it installs.
GENERATOR = "cyclonedx-bom"


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv not found: the SBOM is generated from the lock file")
    return uv


def _generator() -> list[str]:
    uvx = shutil.which("uvx")
    if uvx:
        return [uvx, "--from", GENERATOR, "cyclonedx-py"]
    local = shutil.which("cyclonedx-py")
    if local:
        return [local]
    raise SystemExit(
        "cyclonedx-py not found: install it (`uv tool install cyclonedx-bom`) or uvx"
    )


def generate(
    out: Path = DEFAULT_OUT, groups: tuple[str, ...] = ("server", "dev")
) -> dict:
    """Export the locked requirements, then let CycloneDX read that file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    requirements = out.parent / "requirements-export.txt"
    export = [
        _uv(),
        "export",
        "--format",
        "requirements-txt",
        "--no-dev",
        "--no-hashes",
    ]
    for group in groups:
        export += ["--group", group]
    export += ["--output-file", str(requirements)]
    exported = subprocess.run(
        export, cwd=ROOT, capture_output=True, text=True, check=False
    )
    if exported.returncode != 0:
        raise SystemExit(f"uv export failed:\n{exported.stdout}\n{exported.stderr}")
    try:
        cmd = [
            *_generator(),
            "requirements",
            str(requirements),
            "--output-format",
            "json",
            "--output-file",
            str(out),
        ]
        result = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise SystemExit(
                f"SBOM generation failed:\n{result.stdout}\n{result.stderr}"
            )
    finally:
        requirements.unlink(missing_ok=True)
    document = json.loads(out.read_text(encoding="utf-8"))
    _validate(document)
    return document


def _validate(document: dict) -> None:
    """A file that is not a CycloneDX BOM is worse than no file: CI would ship it."""
    assert document.get("bomFormat") == "CycloneDX", "not a CycloneDX document"
    assert document.get("specVersion"), "no specVersion"
    components = document.get("components") or []
    assert components, "the SBOM lists no components"
    names = {c.get("name") for c in components}
    # The packages whose version would explain a bad extraction or a bad price.
    for required in ("lxml", "pandas", "yfinance", "fastapi"):
        assert required in names, f"{required} missing from the SBOM"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="where to write the BOM"
    )
    parser.add_argument("--check", action="store_true", help="generate and validate")
    args = parser.parse_args(argv)

    document = generate(Path(args.out))
    target = Path(args.out)
    count = len(document["components"])
    shown = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
    print(f"sbom: {count} components -> {shown}")
    if args.check and not target.is_file():
        print("sbom: FAIL — nothing was written")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
