import argparse
import csv
import glob
import hashlib
import shutil
import sqlite3
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator
from xml.etree import ElementTree

REQUIRED_GROUPS = [
    ["database/brickovery.db"],
    ["inputs/super_db/downloads.zip"],
    ["inputs/super_db/brickovery_db.csv"],
    ["inputs/super_db/inventories*.csv", "inputs/super_db/inventories*.zip"],
    ["inputs/super_db/inventory_parts*.csv", "inputs/super_db/inventory_parts*.zip"],
    ["inputs/super_db/minifigs*.csv", "inputs/super_db/minifigs*.zip"],
]

REBRICKABLE_PATTERNS = {
    "inventories": [
        "inputs/super_db/inventories*.csv",
        "inputs/super_db/inventories*.zip",
    ],
    "inventory_parts": [
        "inputs/super_db/inventory_parts*.csv",
        "inputs/super_db/inventory_parts*.zip",
    ],
    "minifigs": [
        "inputs/super_db/minifigs*.csv",
        "inputs/super_db/minifigs*.zip",
    ],
    "sets": [
        "inputs/super_db/sets*.csv",
        "inputs/super_db/sets*.zip",
    ],
    "inventory_minifigs": [
        "inputs/super_db/inventory_minifigs*.csv",
        "inputs/super_db/inventory_minifigs*.zip",
    ],
}

OPTIONAL_PATTERNS = [
    "inputs/super_db/parts*.csv",
    "inputs/super_db/parts*.zip",
    "inputs/super_db/colors*.csv",
    "inputs/super_db/colors*.zip",
]

OPTIONAL_KEYS = {
    "sets": "missing_optional_sets",
    "inventory_minifigs": "missing_optional_inventory_minifigs",
    "parts": "missing_optional_parts",
    "colors": "missing_optional_colors",
}


def _resolve_patterns(root: Path, patterns: Iterable[str]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(Path(path) for path in glob.glob(str(root / pattern)))
    return sorted(set(matches))


def _compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _open_csv_from_zip(path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not members:
            return iter(())
        with archive.open(members[0]) as handle:
            text = handle.read().decode("utf-8", errors="ignore").splitlines()
        return iter(csv.DictReader(text))


def _open_csv(path: Path) -> Iterator[dict[str, str]]:
    if path.suffix.lower() == ".zip":
        return _open_csv_from_zip(path)
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        return iter(csv.DictReader(handle))


def _load_rebrickable_paths(root: Path) -> dict[str, Path | None]:
    resolved: dict[str, Path | None] = {}
    for key, patterns in REBRICKABLE_PATTERNS.items():
        matches = _resolve_patterns(root, patterns)
        resolved[key] = matches[0] if matches else None
    return resolved


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS super_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS xref_bl_to_bk (
            item_type TEXT NOT NULL,
            bl_part_id TEXT NOT NULL,
            bl_color_id INTEGER NOT NULL,
            bk_part_key TEXT,
            bk_color_id INTEGER,
            weight REAL,
            boid TEXT,
            bo_color_id INTEGER,
            PRIMARY KEY (item_type, bl_part_id, bl_color_id)
        );

        CREATE TABLE IF NOT EXISTS bl_category_dim (
            category_id INTEGER PRIMARY KEY,
            category_name TEXT
        );

        CREATE TABLE IF NOT EXISTS bl_minifig_dim (
            bl_fig_num TEXT PRIMARY KEY,
            name TEXT,
            category_id INTEGER,
            category_name TEXT,
            year INTEGER,
            weight REAL
        );

        CREATE TABLE IF NOT EXISTS bl_minifig_parts (
            bl_fig_num TEXT NOT NULL,
            bl_part_id TEXT NOT NULL,
            bl_color_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            PRIMARY KEY (bl_fig_num, bl_part_id, bl_color_id)
        );

        CREATE TABLE IF NOT EXISTS bl_part_color_to_fig (
            bl_part_id TEXT NOT NULL,
            bl_color_id INTEGER NOT NULL,
            bl_fig_num TEXT NOT NULL,
            qty INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bl_part_color_stats (
            bl_part_id TEXT NOT NULL,
            bl_color_id INTEGER NOT NULL,
            fig_count INTEGER NOT NULL,
            PRIMARY KEY (bl_part_id, bl_color_id)
        );

        CREATE TABLE IF NOT EXISTS rb_minifig_dim (
            rb_fig_num TEXT PRIMARY KEY,
            name TEXT,
            num_parts INTEGER,
            img_url TEXT
        );

        CREATE TABLE IF NOT EXISTS rb_fig_parts (
            rb_fig_num TEXT NOT NULL,
            rb_part_num TEXT NOT NULL,
            rb_color_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            is_spare INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rb_part_color_to_fig (
            rb_part_num TEXT NOT NULL,
            rb_color_id INTEGER NOT NULL,
            rb_fig_num TEXT NOT NULL,
            qty INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rb_part_color_stats (
            rb_part_num TEXT NOT NULL,
            rb_color_id INTEGER NOT NULL,
            fig_count INTEGER NOT NULL,
            PRIMARY KEY (rb_part_num, rb_color_id)
        );

        CREATE TABLE IF NOT EXISTS rb_set_dim (
            set_num TEXT PRIMARY KEY,
            name TEXT,
            year INTEGER,
            theme_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS rb_fig_in_sets (
            rb_fig_num TEXT NOT NULL,
            set_num TEXT NOT NULL,
            qty INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bl_parts_lookup
            ON bl_minifig_parts (bl_part_id, bl_color_id);
        CREATE INDEX IF NOT EXISTS idx_bl_part_color_to_fig
            ON bl_part_color_to_fig (bl_part_id, bl_color_id);
        CREATE INDEX IF NOT EXISTS idx_rb_parts_lookup
            ON rb_fig_parts (rb_part_num, rb_color_id);
        CREATE INDEX IF NOT EXISTS idx_rb_part_color_to_fig
            ON rb_part_color_to_fig (rb_part_num, rb_color_id);
        CREATE INDEX IF NOT EXISTS idx_xref_bk_lookup
            ON xref_bl_to_bk (bk_part_key, bk_color_id);
        """
    )


def _truncate_tables(conn: sqlite3.Connection) -> None:
    tables = [
        "super_meta",
        "xref_bl_to_bk",
        "bl_category_dim",
        "bl_minifig_dim",
        "bl_minifig_parts",
        "bl_part_color_to_fig",
        "bl_part_color_stats",
        "rb_minifig_dim",
        "rb_fig_parts",
        "rb_part_color_to_fig",
        "rb_part_color_stats",
        "rb_set_dim",
        "rb_fig_in_sets",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")


def _insert_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO super_meta (key, value) VALUES (?, ?) \
        ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _load_crosswalk(conn: sqlite3.Connection, path: Path) -> int:
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                (
                    row.get("item_type") or row.get("ITEMTYPE") or row.get("itemType"),
                    row.get("bl_part_id") or row.get("ITEMID") or row.get("blPartId"),
                    int(row.get("bl_color_id") or row.get("COLOR") or row.get("blColorId") or 0),
                    row.get("bk_part_key") or row.get("bkPartKey"),
                    _safe_int(row.get("bk_color_id") or row.get("bkColorId")),
                    _safe_float(row.get("weight")),
                    row.get("boid") or row.get("boId"),
                    _safe_int(row.get("bo_color_id") or row.get("boColorId")),
                )
            )
    conn.executemany(
        """
        INSERT OR REPLACE INTO xref_bl_to_bk (
            item_type, bl_part_id, bl_color_id, bk_part_key, bk_color_id, weight, boid, bo_color_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _safe_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _load_bricklink(conn: sqlite3.Connection, downloads_zip: Path) -> dict[str, int]:
    counts = {"bl_minifigs": 0, "bl_parts": 0}
    with zipfile.ZipFile(downloads_zip) as archive:
        if "items/M.csv" not in archive.namelist():
            raise FileNotFoundError("Missing items/M.csv in downloads.zip")
        with archive.open("items/M.csv") as handle:
            text = handle.read().decode("utf-8", errors="ignore").splitlines()
        reader = csv.DictReader(text, delimiter="\t")
        categories: dict[int, str] = {}
        fig_rows = []
        for row in reader:
            fig_id = row.get("ITEMID")
            if not fig_id:
                continue
            category_id = _safe_int(row.get("CATEGORYID"))
            category_name = row.get("CATEGORYNAME")
            if category_id is not None and category_name:
                categories[category_id] = category_name
            fig_rows.append(
                (
                    fig_id,
                    row.get("ITEMNAME"),
                    category_id,
                    categories.get(category_id) if category_id is not None else None,
                    None,
                    None,
                )
            )
        conn.executemany(
            """
            INSERT OR REPLACE INTO bl_minifig_dim (
                bl_fig_num, name, category_id, category_name, year, weight
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            fig_rows,
        )
        if categories:
            conn.executemany(
                "INSERT OR REPLACE INTO bl_category_dim (category_id, category_name) VALUES (?, ?)",
                list(categories.items()),
            )
        counts["bl_minifigs"] = len(fig_rows)

        if "items/M.xml" in archive.namelist():
            with archive.open("items/M.xml") as handle:
                xml_data = handle.read()
            root = ElementTree.fromstring(xml_data)
            updates = []
            for item in root.findall("ITEM"):
                fig_id = item.findtext("ITEMID")
                year = _safe_int(item.findtext("YEAR"))
                weight = _safe_float(item.findtext("WEIGHT"))
                if fig_id:
                    updates.append((year, weight, fig_id))
            conn.executemany(
                "UPDATE bl_minifig_dim SET year = ?, weight = ? WHERE bl_fig_num = ?",
                updates,
            )

        part_rows = defaultdict(int)
        for name in archive.namelist():
            if not name.startswith("M/") or not name.endswith(".xml"):
                continue
            with archive.open(name) as handle:
                xml_data = handle.read()
            root = ElementTree.fromstring(xml_data)
            fig_num = root.findtext("ITEMID") or root.findtext("ITEM")
            if not fig_num:
                fig_num = name.split("/")[-1].replace(".xml", "")
            for item in root.findall("ITEM"):
                part_id = item.findtext("ITEMID")
                color_id = _safe_int(item.findtext("COLOR"))
                qty = _safe_int(item.findtext("QTY")) or 0
                if not part_id or color_id is None:
                    continue
                part_rows[(fig_num, part_id, color_id)] += qty

        conn.executemany(
            """
            INSERT OR REPLACE INTO bl_minifig_parts (bl_fig_num, bl_part_id, bl_color_id, qty)
            VALUES (?, ?, ?, ?)
            """,
            [(k[0], k[1], k[2], v) for k, v in part_rows.items()],
        )
        counts["bl_parts"] = len(part_rows)

        stats = defaultdict(set)
        for (fig_num, part_id, color_id), qty in part_rows.items():
            stats[(part_id, color_id)].add(fig_num)
        conn.executemany(
            """
            INSERT OR REPLACE INTO bl_part_color_stats (bl_part_id, bl_color_id, fig_count)
            VALUES (?, ?, ?)
            """,
            [(part_id, color_id, len(figs)) for (part_id, color_id), figs in stats.items()],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO bl_part_color_to_fig (bl_part_id, bl_color_id, bl_fig_num, qty)
            VALUES (?, ?, ?, ?)
            """,
            [(part_id, color_id, fig_num, qty) for (fig_num, part_id, color_id), qty in part_rows.items()],
        )

    return counts


def _load_rebrickable(conn: sqlite3.Connection, paths: dict[str, Path | None]) -> dict[str, int]:
    counts = {"rb_minifigs": 0, "rb_parts": 0, "rb_sets": 0, "rb_fig_in_sets": 0}
    if not paths.get("minifigs") or not paths.get("inventories") or not paths.get("inventory_parts"):
        return counts

    minifigs_path = paths["minifigs"]
    inventories_path = paths["inventories"]
    inventory_parts_path = paths["inventory_parts"]
    if not minifigs_path or not inventories_path or not inventory_parts_path:
        return counts

    minifig_rows = []
    for row in _open_csv(minifigs_path):
        fig_num = row.get("fig_num") or row.get("figNum")
        if not fig_num:
            continue
        minifig_rows.append(
            (
                fig_num,
                row.get("name"),
                _safe_int(row.get("num_parts")),
                row.get("img_url"),
            )
        )
    conn.executemany(
        "INSERT OR REPLACE INTO rb_minifig_dim (rb_fig_num, name, num_parts, img_url) VALUES (?, ?, ?, ?)",
        minifig_rows,
    )
    counts["rb_minifigs"] = len(minifig_rows)

    fig_inventory_map: dict[str, str] = {}
    set_inventory_map: dict[str, str] = {}
    for row in _open_csv(inventories_path):
        inventory_id = row.get("id") or row.get("inventory_id")
        set_num = row.get("set_num") or row.get("setNum")
        if not inventory_id or not set_num:
            continue
        if set_num.startswith("fig-"):
            fig_inventory_map[inventory_id] = set_num
        else:
            set_inventory_map[inventory_id] = set_num

    part_rows = []
    for row in _open_csv(inventory_parts_path):
        inventory_id = row.get("inventory_id") or row.get("inventoryId")
        fig_num = fig_inventory_map.get(inventory_id)
        if not fig_num:
            continue
        part_num = row.get("part_num") or row.get("partNum")
        color_id = _safe_int(row.get("color_id")) or 0
        qty = _safe_int(row.get("quantity")) or 0
        is_spare = _safe_int(row.get("is_spare")) or 0
        if not part_num:
            continue
        part_rows.append((fig_num, part_num, color_id, qty, is_spare))

    conn.executemany(
        """
        INSERT INTO rb_fig_parts (rb_fig_num, rb_part_num, rb_color_id, qty, is_spare)
        VALUES (?, ?, ?, ?, ?)
        """,
        part_rows,
    )
    counts["rb_parts"] = len(part_rows)

    stats = defaultdict(set)
    for fig_num, part_num, color_id, qty, is_spare in part_rows:
        stats[(part_num, color_id)].add(fig_num)
    conn.executemany(
        """
        INSERT OR REPLACE INTO rb_part_color_stats (rb_part_num, rb_color_id, fig_count)
        VALUES (?, ?, ?)
        """,
        [(part_num, color_id, len(figs)) for (part_num, color_id), figs in stats.items()],
    )
    conn.executemany(
        """
        INSERT INTO rb_part_color_to_fig (rb_part_num, rb_color_id, rb_fig_num, qty)
        VALUES (?, ?, ?, ?)
        """,
        [(part_num, color_id, fig_num, qty) for fig_num, part_num, color_id, qty, _ in part_rows],
    )

    sets_path = paths.get("sets")
    if sets_path:
        set_rows = []
        for row in _open_csv(sets_path):
            set_num = row.get("set_num") or row.get("setNum")
            if not set_num:
                continue
            set_rows.append(
                (
                    set_num,
                    row.get("name"),
                    _safe_int(row.get("year")),
                    _safe_int(row.get("theme_id")),
                )
            )
        conn.executemany(
            "INSERT OR REPLACE INTO rb_set_dim (set_num, name, year, theme_id) VALUES (?, ?, ?, ?)",
            set_rows,
        )
        counts["rb_sets"] = len(set_rows)

    inv_minifigs_path = paths.get("inventory_minifigs")
    if inv_minifigs_path:
        fig_in_sets_rows = []
        for row in _open_csv(inv_minifigs_path):
            inventory_id = row.get("inventory_id") or row.get("inventoryId")
            fig_num = row.get("fig_num") or row.get("figNum")
            qty = _safe_int(row.get("quantity")) or 0
            set_num = set_inventory_map.get(inventory_id)
            if not fig_num or not set_num:
                continue
            fig_in_sets_rows.append((fig_num, set_num, qty))
        conn.executemany(
            "INSERT INTO rb_fig_in_sets (rb_fig_num, set_num, qty) VALUES (?, ?, ?)",
            fig_in_sets_rows,
        )
        counts["rb_fig_in_sets"] = len(fig_in_sets_rows)

    return counts


def _record_hashes(conn: sqlite3.Connection, root: Path, paths: Iterable[Path]) -> None:
    for path in paths:
        if not path.exists():
            continue
        rel = str(path.relative_to(root))
        _insert_meta(conn, f"input_sha256:{rel}", _compute_sha256(path))


def _record_missing_optionals(conn: sqlite3.Connection, paths: dict[str, Path | None]) -> None:
    for key, meta_key in OPTIONAL_KEYS.items():
        if not paths.get(key):
            _insert_meta(conn, meta_key, "true")


def _ensure_required(root: Path) -> None:
    missing = []
    for patterns in REQUIRED_GROUPS:
        matches = []
        for pattern in patterns:
            matches.extend(glob.glob(str(root / pattern)))
        if not matches:
            missing.append(" OR ".join(patterns))
    if missing:
        print("Missing required inputs:")
        for path in missing:
            print(f"- {path}")
        raise SystemExit(1)


def build_superdb(root: Path, output: Path, force: bool) -> None:
    _ensure_required(root)
    base_db = root / "database/brickovery.db"

    if output.exists():
        if not force:
            print(f"Output database already exists: {output}. Use --force to rebuild.")
            raise SystemExit(1)
        output.unlink()

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_db, output)

    conn = sqlite3.connect(output)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        _create_schema(conn)
        _truncate_tables(conn)

        downloads_zip = root / "inputs/super_db/downloads.zip"
        crosswalk_csv = root / "inputs/super_db/brickovery_db.csv"

        _record_hashes(
            conn,
            root,
            [base_db, downloads_zip, crosswalk_csv],
        )

        crosswalk_count = _load_crosswalk(conn, crosswalk_csv)
        bl_counts = _load_bricklink(conn, downloads_zip)

        rb_paths = _load_rebrickable_paths(root)
        optional_paths = _resolve_patterns(root, OPTIONAL_PATTERNS)
        _record_hashes(
            conn,
            root,
            [path for path in rb_paths.values() if path] + optional_paths,
        )
        _record_missing_optionals(conn, rb_paths)
        rb_counts = _load_rebrickable(conn, rb_paths)

        _insert_meta(conn, "count_xref", str(crosswalk_count))
        _insert_meta(conn, "count_bl_minifig_dim", str(bl_counts["bl_minifigs"]))
        _insert_meta(conn, "count_bl_minifig_parts", str(bl_counts["bl_parts"]))
        _insert_meta(conn, "count_rb_minifig_dim", str(rb_counts["rb_minifigs"]))
        _insert_meta(conn, "count_rb_fig_parts", str(rb_counts["rb_parts"]))
        _insert_meta(conn, "count_rb_set_dim", str(rb_counts["rb_sets"]))
        _insert_meta(conn, "count_rb_fig_in_sets", str(rb_counts["rb_fig_in_sets"]))

        conn.commit()
    finally:
        conn.close()

    print(f"SuperDB created at: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the SuperDB SQLite database.")
    parser.add_argument(
        "--root",
        default=Path.cwd(),
        type=Path,
        help="Repository root (default: current working directory)",
    )
    parser.add_argument(
        "--output",
        default=Path("database/brickovery_sp.db"),
        type=Path,
        help="Output SQLite path (default: database/brickovery_sp.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output database if it exists",
    )
    args = parser.parse_args()

    try:
        build_superdb(args.root, args.output, args.force)
    except (FileNotFoundError, sqlite3.Error, ElementTree.ParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
