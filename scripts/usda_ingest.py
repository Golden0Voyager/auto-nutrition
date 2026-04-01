"""USDA FoodData Central full-nutrient ingest script.

Downloads Foundation Foods and SR Legacy datasets, then imports ALL nutrients
into a normalized SQLite schema for comprehensive nutrition queries.

Schema:
  foods(fdc_id, description, data_type)
  nutrients(nutrient_id, name, unit_name)
  food_nutrients(fdc_id, nutrient_id, amount)   ← ALL data points
  foods_fts(description, fdc_id)                ← FTS5 full-text index
"""

import sqlite3
import zipfile
import csv
import io
import sys

import requests
from loguru import logger
from pathlib import Path

# USDA FoodData Central CSV download URLs
USDA_URLS = {
    "foundation": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2024-10-31.zip",
    "sr_legacy": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip",
}

DB_PATH = Path(__file__).resolve().parent.parent / "usda_core.db"
BATCH_SIZE = 10000


def setup_db(conn: sqlite3.Connection) -> None:
    """Create normalized schema with 3 core tables + FTS5 index."""
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS food_nutrients")
    cursor.execute("DROP TABLE IF EXISTS nutrients")
    cursor.execute("DROP TABLE IF EXISTS foods")
    cursor.execute("DROP TABLE IF EXISTS foods_fts")

    cursor.execute("""
        CREATE TABLE foods (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE nutrients (
            nutrient_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            unit_name TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE food_nutrients (
            fdc_id INTEGER NOT NULL,
            nutrient_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            PRIMARY KEY (fdc_id, nutrient_id)
        )
    """)

    cursor.execute(
        "CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)"
    )

    conn.commit()
    logger.info("Database schema created (normalized 3-table design).")


def ingest_zip(url: str, conn: sqlite3.Connection) -> None:
    """Download a USDA CSV zip and import all data."""
    logger.info("Downloading: {}", url.split("/")[-1])
    resp = requests.get(url, timeout=180, stream=False)
    resp.raise_for_status()
    logger.info("Download complete ({:.1f} MB), parsing...", len(resp.content) / 1e6)

    cursor = conn.cursor()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        file_list = z.namelist()
        food_file = next(f for f in file_list if f.split("/")[-1] == "food.csv")
        nutrient_file = next(
            f for f in file_list if f.split("/")[-1] == "food_nutrient.csv"
        )
        nutrient_def_file = next(
            (f for f in file_list if f.split("/")[-1] == "nutrient.csv"), None
        )

        # ── 1. Nutrient definitions ──
        if nutrient_def_file:
            logger.info("Importing nutrient definitions: {}", nutrient_def_file)
            count = 0
            with z.open(nutrient_def_file) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                for row in reader:
                    cursor.execute(
                        "INSERT OR IGNORE INTO nutrients (nutrient_id, name, unit_name) VALUES (?, ?, ?)",
                        (int(row["id"]), row["name"], row.get("unit_name", "")),
                    )
                    count += 1
            logger.info("  → {} nutrient definitions imported.", count)

        # ── 2. Food items ──
        logger.info("Importing food items: {}", food_file)
        food_ids = set()
        with z.open(food_file) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            for row in reader:
                fdc_id = int(row["fdc_id"])
                desc = row["description"]
                data_type = row.get("data_type", "SR Legacy")
                cursor.execute(
                    "INSERT OR IGNORE INTO foods (fdc_id, description, data_type) VALUES (?, ?, ?)",
                    (fdc_id, desc, data_type),
                )
                cursor.execute(
                    "INSERT INTO foods_fts (description, fdc_id) VALUES (?, ?)",
                    (desc, fdc_id),
                )
                food_ids.add(fdc_id)
        logger.info("  → {} food items imported.", len(food_ids))

        # ── 3. ALL food-nutrient data points (no filtering!) ──
        logger.info(
            "Importing ALL food nutrients (full extraction, may take 1-2 min): {}",
            nutrient_file,
        )
        batch: list[tuple] = []
        total = 0
        skipped = 0
        with z.open(nutrient_file) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            for row in reader:
                fdc_id = int(row["fdc_id"])
                if fdc_id not in food_ids:
                    skipped += 1
                    continue
                try:
                    nutrient_id = int(row["nutrient_id"])
                    amount = float(row["amount"])
                    batch.append((fdc_id, nutrient_id, amount))
                    total += 1
                    if len(batch) >= BATCH_SIZE:
                        cursor.executemany(
                            "INSERT OR IGNORE INTO food_nutrients (fdc_id, nutrient_id, amount) VALUES (?, ?, ?)",
                            batch,
                        )
                        batch = []
                        if total % 100000 == 0:
                            logger.info("  ... {} data points processed", total)
                except (ValueError, TypeError):
                    continue

        if batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO food_nutrients (fdc_id, nutrient_id, amount) VALUES (?, ?, ?)",
                batch,
            )

        logger.info(
            "  → {} nutrient data points imported ({} orphan rows skipped).",
            total,
            skipped,
        )

    conn.commit()


def create_indexes(conn: sqlite3.Connection) -> None:
    """Create performance indexes for fast nutrient lookups."""
    logger.info("Creating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fn_fdc ON food_nutrients(fdc_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fn_nutrient ON food_nutrients(nutrient_id)"
    )
    conn.commit()
    logger.info("Indexes created.")


def main() -> None:
    """Entry point: build full USDA local database."""
    logger.remove()
    logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | {message}")

    logger.info("=== USDA Full-Nutrient Database Builder ===")
    logger.info("Target: {}", DB_PATH)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")  # Speed up bulk import

    setup_db(conn)

    try:
        for name, url in USDA_URLS.items():
            logger.info("--- Processing dataset: {} ---", name)
            ingest_zip(url, conn)

        create_indexes(conn)

        # Final stats
        foods_count = conn.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
        nutrients_count = conn.execute("SELECT COUNT(*) FROM nutrients").fetchone()[0]
        fn_count = conn.execute("SELECT COUNT(*) FROM food_nutrients").fetchone()[0]
        db_size_mb = DB_PATH.stat().st_size / 1e6

        logger.info("=== Build Complete ===")
        logger.info("  Foods:       {:,}", foods_count)
        logger.info("  Nutrients:   {:,}", nutrients_count)
        logger.info("  Data points: {:,}", fn_count)
        logger.info("  DB size:     {:.1f} MB", db_size_mb)

        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("VACUUM")
        logger.info(
            "  Final size:  {:.1f} MB (after VACUUM)", DB_PATH.stat().st_size / 1e6
        )
    except Exception as e:
        logger.error("Build failed: {}", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
