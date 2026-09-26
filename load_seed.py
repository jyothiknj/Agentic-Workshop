"""Load seed/tickets.csv and seed/customers.csv into app.db, rebuilding both tables on every run."""

import csv
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = REPO_ROOT / "app.db"
DEFAULT_SEED_DIR = REPO_ROOT / "seed"

# table name -> (CSV file name, columns in order). Names match mcp/triage_server.py.
TABLES: dict[str, tuple[str, list[str]]] = {
    "tickets": ("tickets.csv", ["ticket_id", "customer_id", "created_at", "text"]),
    "customers": ("customers.csv", ["customer_id", "name", "plan", "open_tickets"]),
}


class SeedError(Exception):
    """A seed file is missing or does not have the expected header."""


def _read_csv(path: Path, columns: list[str]) -> list[tuple[str, ...]]:
    if not path.is_file():
        raise SeedError(f"Seed file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            raise SeedError(
                f"{path} has header {reader.fieldnames}; expected columns {columns}"
            )
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise SeedError(
                    f"{path} line {reader.line_num} does not have exactly {len(columns)} fields"
                )
            rows.append(tuple(row[c] for c in columns))
        return rows


def load_seed(db_path: Path = DEFAULT_DB_PATH, seed_dir: Path = DEFAULT_SEED_DIR) -> dict[str, int]:
    """Rebuild the tickets and customers tables in ``db_path`` from the CSVs in ``seed_dir``.

    Both CSVs are read and checked before the database is touched, and the drop,
    create and insert run in one transaction, so a failed run changes nothing.
    Returns the row count per table.
    """
    seed_dir = Path(seed_dir)
    data = {
        table: (columns, _read_csv(seed_dir / file_name, columns))
        for table, (file_name, columns) in TABLES.items()
    }

    db_path = Path(db_path)
    existed = db_path.exists()
    try:
        # With autocommit=False, closing without commit rolls the transaction back.
        with closing(sqlite3.connect(db_path, autocommit=False)) as conn:
            for table, (columns, rows) in data.items():
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.execute(f"CREATE TABLE {table} ({', '.join(f'{c} TEXT' for c in columns)})")
                placeholders = ", ".join("?" for _ in columns)
                conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows)
            conn.commit()
    except BaseException:
        if not existed:
            db_path.unlink(missing_ok=True)
        raise

    return {table: len(rows) for table, (_, rows) in data.items()}


def main() -> int:
    try:
        counts = load_seed(DEFAULT_DB_PATH, DEFAULT_SEED_DIR)
    except (SeedError, sqlite3.Error) as e:
        print(f"load_seed: {e}", file=sys.stderr)
        return 1
    print(f"Loaded {counts['tickets']} tickets and {counts['customers']} customers into {DEFAULT_DB_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
