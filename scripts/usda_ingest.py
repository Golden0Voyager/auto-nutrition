import os
import sqlite3
import zipfile
import requests
import csv
import io
from loguru import logger
from pathlib import Path

# USDA Core Data URLs (Latest as of Dec 2025/Historical SR Legacy)
USDA_URLS = {
    "foundation": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2024-10-31.zip",
    "sr_legacy": "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04-20.zip"
}

# 核心营养素 ID 映射 (与 mfp_adapter.py 一致)
NUTRIENT_IDS = {
    '1008': 'energy',
    '1003': 'protein',
    '1005': 'carbs',
    '1004': 'fat',
    '1093': 'sodium',
    '1092': 'potassium',
    '1087': 'calcium',
    '1089': 'iron',
    '1079': 'fiber',
    '2000': 'sugar',
    '1258': 'saturated_fat',
    '1001': 'cholesterol' # or 1253
}

DB_PATH = Path("usda_core.db")

def setup_db(conn):
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS foods")
    cursor.execute("""
        CREATE TABLE foods (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT,
            data_type TEXT,
            energy REAL DEFAULT 0,
            protein REAL DEFAULT 0,
            carbs REAL DEFAULT 0,
            fat REAL DEFAULT 0,
            sodium REAL DEFAULT 0,
            potassium REAL DEFAULT 0,
            fiber REAL DEFAULT 0,
            sugar REAL DEFAULT 0
        )
    """)
    # 建立全文搜索索引
    cursor.execute("DROP TABLE IF EXISTS foods_fts")
    cursor.execute("CREATE VIRTUAL TABLE foods_fts USING fts5(description, fdc_id UNINDEXED)")
    conn.commit()

def ingest_zip(url, conn):
    logger.info(f"正在从 {url} 下载数据...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        # 查找目标文件名（USDA 不同包里的路径可能不同），确保匹配的是根文件
        file_list = z.namelist()
        food_file = next(f for f in file_list if f.split('/')[-1] == "food.csv")
        nutrient_file = next(f for f in file_list if f.split('/')[-1] == "food_nutrient.csv")
        
        logger.info(f"解析食物基础信息: {food_file}")
        foods = {}
        with z.open(food_file) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
            for row in reader:
                fdc_id = int(row['fdc_id'])
                foods[fdc_id] = {
                    "description": row['description'],
                    "data_type": row.get('data_type', 'SR Legacy'),
                    "nutrients": {}
                }

        logger.info(f"解析营养素详情 (耗时较长): {nutrient_file}")
        with z.open(nutrient_file) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
            for row in reader:
                fdc_id = int(row['fdc_id'])
                n_id = row['nutrient_id']
                if fdc_id in foods and n_id in NUTRIENT_IDS:
                    try:
                        amount = float(row['amount'])
                        foods[fdc_id]["nutrients"][NUTRIENT_IDS[n_id]] = amount
                    except (ValueError, TypeError):
                        continue

        logger.info(f"写入数据库: {len(foods)} 条记录")
        cursor = conn.cursor()
        for fdc_id, info in foods.items():
            n = info["nutrients"]
            cursor.execute("""
                INSERT INTO foods (fdc_id, description, data_type, energy, protein, carbs, fat, sodium, potassium, fiber, sugar)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fdc_id, info["description"], info["data_type"],
                n.get("energy", 0), n.get("protein", 0), n.get("carbs", 0), n.get("fat", 0),
                n.get("sodium", 0), n.get("potassium", 0), n.get("fiber", 0), n.get("sugar", 0)
            ))
            cursor.execute("INSERT INTO foods_fts (description, fdc_id) VALUES (?, ?)", (info["description"], fdc_id))
        conn.commit()

def main():
    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)
    
    try:
        # 下载 Foundation Foods
        ingest_zip(USDA_URLS["foundation"], conn)
        # 下载 SR Legacy
        ingest_zip(USDA_URLS["sr_legacy"], conn)
        
        logger.info("🎉 USDA 本地数据库构建完成！")
        # 优化数据库体积
        conn.execute("VACUUM")
    except Exception as e:
        logger.error(f"构建失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
