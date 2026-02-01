import argparse
import glob
from pathlib import Path
from typing import Iterable

REQUIRED_GROUPS = [
    ["database/brickovery.db"],
    ["inputs/super_db/downloads.zip"],
    ["inputs/super_db/brickovery_db.csv"],
    ["inputs/super_db/inventories*.csv", "inputs/super_db/inventories*.zip"],
    ["inputs/super_db/inventory_parts*.csv", "inputs/super_db/inventory_parts*.zip"],
    ["inputs/super_db/minifigs*.csv", "inputs/super_db/minifigs*.zip"],
]

OPTIONAL_PATTERNS = [
    "inputs/super_db/sets*.csv",
    "inputs/super_db/sets*.zip",
    "inputs/super_db/inventory_minifigs*.csv",
    "inputs/super_db/inventory_minifigs*.zip",
    "inputs/super_db/parts*.csv",
    "inputs/super_db/parts*.zip",
    "inputs/super_db/colors*.csv",
    "inputs/super_db/colors*.zip",
]


def _resolve_patterns(patterns: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern))
    return sorted(set(matches))


def validate_inputs(root: Path) -> int:
    missing = []
    for patterns in REQUIRED_GROUPS:
        matches = []
        for pattern in patterns:
            matches.extend(glob.glob(str(root / pattern)))
        if not matches:
            missing.append(" OR ".join(patterns))

    optional = _resolve_patterns([str(root / pattern) for pattern in OPTIONAL_PATTERNS])
    optional_rel = [str(Path(path).relative_to(root)) for path in optional]

    if missing:
        print("Missing required inputs:")
        for path in missing:
            print(f"- {path}")
        print("\nOptional inputs detected:")
        for path in optional_rel:
            print(f"- {path}")
        return 1

    print("Required inputs found.")
    print("Optional inputs detected:")
    for path in optional_rel:
        print(f"- {path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SuperDB inputs.")
    parser.add_argument(
        "--root",
        default=Path.cwd(),
        type=Path,
        help="Repository root (default: current working directory)",
    )
    args = parser.parse_args()
    raise SystemExit(validate_inputs(args.root))


if __name__ == "__main__":
    main()
