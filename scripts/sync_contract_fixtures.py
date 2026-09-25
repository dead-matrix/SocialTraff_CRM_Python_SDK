"""Copy CRM contract fixtures into the SDK, or check that the copy is current.

The source of truth is CRM ``tests/contract/*.json``. The SDK keeps a byte copy in
``tests/fixtures/contract/`` plus ``CRM_VERSION`` with the CRM commit it came from.

    # re-sync from a CRM checkout (prints what changed, writes CRM_VERSION)
    python scripts/sync_contract_fixtures.py --crm ../CRM

    # CI: exit 1 when the copy differs from the checkout (no files are written)
    python scripts/sync_contract_fixtures.py --crm ../CRM --check

``--crm`` defaults to ``$CRM_CHECKOUT``. After a re-sync run ``pytest``: a fixture the SDK
does not parse yet fails ``tests/test_contract_fixtures.py``. Line endings are compared as LF.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tests" / "fixtures" / "contract"
VERSION_FILE = TARGET / "CRM_VERSION"


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _crm_commit(crm: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(crm), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or len(commit) != 40:
        raise SystemExit(f"cannot read the CRM commit in {crm}: {result.stderr.strip()}")
    return commit


def _diff(source: Path) -> tuple[list[str], list[str], list[str]]:
    theirs = {path.name: path for path in source.glob("*.json")}
    ours = {path.name: path for path in TARGET.glob("*.json")}
    added = sorted(set(theirs) - set(ours))
    removed = sorted(set(ours) - set(theirs))
    changed = sorted(
        name
        for name in set(theirs) & set(ours)
        if _normalized(theirs[name]) != _normalized(ours[name])
    )
    return added, removed, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--crm", default=os.environ.get("CRM_CHECKOUT"), help="CRM checkout")
    parser.add_argument("--check", action="store_true", help="only compare, exit 1 on drift")
    args = parser.parse_args(argv)
    if not args.crm:
        parser.error("--crm or CRM_CHECKOUT is required")
    crm = Path(args.crm).resolve()
    source = crm / "tests" / "contract"
    if not source.is_dir():
        parser.error(f"{source} is not a directory")

    added, removed, changed = _diff(source)
    for label, names in (("added", added), ("removed", removed), ("changed", changed)):
        for name in names:
            print(f"{label}: {name}")

    if args.check:
        if added or removed or changed:
            print("contract fixtures differ from the CRM checkout", file=sys.stderr)
            return 1
        print("contract fixtures match the CRM checkout")
        return 0

    TARGET.mkdir(parents=True, exist_ok=True)
    for name in removed:
        (TARGET / name).unlink()
    for name in added + changed:
        shutil.copyfile(source / name, TARGET / name)
    commit = _crm_commit(crm)
    VERSION_FILE.write_text(
        f"commit={commit}\nsource=CRM tests/contract/*.json\n", encoding="utf-8"
    )
    print(
        f"synced from CRM {commit[:12]}: {len(added)} added, {len(changed)} changed, "
        f"{len(removed)} removed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
