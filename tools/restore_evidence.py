"""Verify and copy included recordings into the local dashboard's run history."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def restore(group="all", destination=None):
    manifest = json.loads((ROOT / "evidence" / "manifest.json").read_text())
    destination = Path(destination) if destination is not None else ROOT / ".runtime" / "runs"
    selected = [run for run in manifest["runs"] if group == "all" or run["group"] == group]
    pending = []
    for run in selected:
        if run["group"] not in ("report", "failback", "additional") or not RUN_ID.fullmatch(run["run_id"]):
            raise ValueError("Invalid evidence group or run ID in manifest")
        directory = destination / run["run_id"]
        if directory.is_symlink():
            raise ValueError(f"Refusing a symlink run directory: {directory}")
        for entry in run["files"]:
            relative = Path(entry["name"])
            if relative.is_absolute() or len(relative.parts) != 1 or relative.name in (".", ".."):
                raise ValueError("Invalid evidence filename in manifest")
            source = ROOT / "evidence" / "runs" / run["group"] / run["run_id"] / relative
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError(f"Evidence checksum mismatch: {source}")
            target = directory / relative
            if target.is_symlink():
                raise ValueError(f"Refusing a symlink evidence file: {target}")
            if target.exists():
                if target.read_bytes() != source.read_bytes():
                    raise ValueError(f"Refusing to overwrite different existing evidence: {target}")
            else:
                pending.append((source, target))
    for source, target in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return len(selected), len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "report", "failback", "additional"), default="all")
    args = parser.parse_args()
    try:
        runs, copied = restore(args.group)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Cannot restore evidence: {error}\n")
    print(f"Verified {runs} recordings; copied {copied} missing files.")
    print("To show earlier recordings: python3 reset_dashboard.py --restore")
    print("Then start the saved-results dashboard: python3 dashboard/server.py")


if __name__ == "__main__":
    main()
