import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv
from loguru import logger
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def is_server_error(exception: BaseException) -> bool:
    if isinstance(exception, requests.exceptions.HTTPError):
        resp = getattr(exception, "response", None)
        if resp is not None and getattr(resp, "status_code", 0) >= 500:
            return True
    return False

class NutritionModel(BaseModel):
    protein: float = Field(default=0, ge=0, description="Protein (g) | 蛋白质 (g)")
    carbs: float = Field(default=0, ge=0, description="Carbohydrates (g) | 碳水化合物 (g)")
    fat: float = Field(default=0, ge=0, description="Total Fat (g) | 脂肪 (g)")
    # 微量元素 (Optional)
    sodium: float | None = Field(None, ge=0, description="Sodium (mg) | 钠 (mg)")
    potassium: float | None = Field(None, ge=0, description="Potassium (mg) | 钾 (mg)")
    calcium: float | None = Field(None, ge=0, description="Calcium (%DV) | 钙 (%DV)")
    iron: float | None = Field(None, ge=0, description="Iron (%DV) | 铁 (%DV)")
    vitamin_a: float | None = Field(None, ge=0, description="Vitamin A (%DV) | 维生素 A (%DV)")
    vitamin_c: float | None = Field(None, ge=0, description="Vitamin C (%DV) | 维生素 C (%DV)")
    fiber: float | None = Field(None, ge=0, description="Dietary Fiber (g) | 膳食纤维 (g)")
    sugar: float | None = Field(None, ge=0, description="Sugar (g) | 糖分 (g)")
    vitamin_d: float | None = Field(None, ge=0, description="Vitamin D (%DV) | 维生素 D (%DV)")
    cholesterol: float | None = Field(None, ge=0, description="Cholesterol (mg) | 胆固醇 (mg)")
    saturated_fat: float | None = Field(None, ge=0, description="Saturated Fat (g) | 饱和脂肪 (g)")
    polyunsaturated_fat: float | None = Field(None, ge=0, description="Polyunsaturated Fat (g) | 多不饱和脂肪 (g)")
    monounsaturated_fat: float | None = Field(None, ge=0, description="Monounsaturated Fat (g) | 单不饱和脂肪 (g)")
    trans_fat: float | None = Field(None, ge=0, description="Trans Fat (g) | 反式脂肪 (g)")

class FoodItemModel(BaseModel):
    name: str = Field(..., description="Food name | 食物名称")
    calories: float | None = Field(None, ge=0, description="Calories (kcal), optional — system will auto-lookup if omitted | 热量 (kcal)，可选——不填则自动查库")
    macros: NutritionModel | None = Field(None, description="Macro and micronutrients, optional | 营养素指标，可选")
    meal_type: str | None = Field(None, description="Meal type (breakfast/lunch/dinner/snack) | 餐次类型")
    date: str | None = Field(None, description="Date (YYYY-MM-DD) | 日期")
    serving_ratio: float | None = Field(1.0, description="Serving size multiplier | 食用比例系数")

class ExerciseModel(BaseModel):
    name: str = Field(..., description="Exercise name (e.g., 'Running') | 运动名称（如：跑步）")
    exercise_type: str = Field(..., description="'cardio' or 'strength' | 'cardio'(有氧) 或 'strength'(力量)")
    date: str = Field(..., description="Date (YYYY-MM-DD) | 日期")
    calories_burned: float | None = Field(None, description="Estimated calories burned | 预估消耗热量")
    duration_min: float | None = Field(None, description="Duration in minutes | 运动时长（分钟）")
    sets: int | None = Field(None, description="Number of sets | 组数")
    reps: int | None = Field(None, description="Repetitions per set | 每组次数")
    weight_kg: float | None = Field(None, description="Weight per set (kg) | 每组重量（公斤）")

load_dotenv()

# 配置 loguru
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="DEBUG",
)

class SessionExpiredError(Exception):
    """当 MyFitnessPal 会话过期或无效时抛出"""
    pass

class USDALocalResolver:
    """Local USDA database query engine with full nutrient support.

    Supports both the new normalized schema (foods/nutrients/food_nutrients)
    and the legacy flat schema for backward compatibility.
    """
    DB_PATH = Path(__file__).resolve().parent / "usda_core.db"

    # USDA nutrient_id -> (our_field_name, original_unit)
    # These field names align with _create_custom_food's field_map
    NUTRIENT_MAP: dict[int, tuple] = {
        1008: ("energy", "kcal"),          # 传统通用值，覆盖广
        2047: ("energy_atwater", "kcal"),   # Atwater General Factors — 新版条目，精度中
        2048: ("energy_atwater_sp", "kcal"),# Atwater Specific Factors — 新版条目，精度最高
        1003: ("protein", "g"),
        1005: ("carbs", "g"),
        1004: ("fat", "g"),
        1093: ("sodium", "mg"),
        1092: ("potassium", "mg"),
        1087: ("calcium", "mg"),
        1089: ("iron", "mg"),
        1079: ("fiber", "g"),
        2000: ("sugar", "g"),
        1258: ("saturated_fat", "g"),
        1253: ("cholesterol", "mg"),
        1106: ("vitamin_a", "mcg"),     # RAE
        1162: ("vitamin_c", "mg"),
        1114: ("vitamin_d", "mcg"),
        1293: ("polyunsaturated_fat", "g"),
        1292: ("monounsaturated_fat", "g"),
        1257: ("trans_fat", "g"),
    }

    # MFP expects %DV for these fields; convert from absolute values
    DV_BASES: dict[str, float] = {
        "calcium": 1300.0,   # mg
        "iron": 18.0,        # mg
        "vitamin_a": 900.0,  # mcg RAE
        "vitamin_c": 90.0,   # mg
        "vitamin_d": 20.0,   # mcg
    }

    # Language guard hints for common non-English food names
    LANG_GUARD_HINTS = {
        "苹果": "Apple", "鸡蛋": "Egg", "牛肉": "Beef", "鸡胸肉": "Chicken Breast",
        "三文鱼": "Salmon", "糙米": "Brown Rice", "菠菜": "Spinach", "牛油果": "Avocado",
        "花椰菜": "Broccoli", "全麦面包": "Whole Wheat Bread", "猪肉": "Pork",
        "燕麦": "Oats", "香蕉": "Banana", "西红柿": "Tomato",
    }

    def search(self, query: str, page_size: int = 3) -> list[dict[str, Any]]:
        """Full-text search with complete nutrient profiles.

        Returns per-100g data. The caller should multiply by serving_ratio.
        IMPORTANT: query MUST be in English for FTS5 to work.
        """
        # Language guard
        has_non_ascii = any(ord(c) > 127 for c in query)
        if has_non_ascii:
            hint = next(
                (eng for cn, eng in self.LANG_GUARD_HINTS.items() if cn in query),
                None,
            )
            hint_msg = f" Suggested: '{hint}'" if hint else " Please translate to English."
            logger.warning(
                "[USDA Language Guard] Non-English query: '{}' -- FTS5 requires English!{}",
                query, hint_msg,
            )

        if not self.DB_PATH.exists():
            logger.warning("Local USDA database not found, skipping Level 2.")
            return []

        try:
            conn = sqlite3.connect(self.DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 清洗查询：只保留英文单词（去掉数字、中文、括号等干扰项），提高 FTS 命中率
            # 使用 AND 组合确保每个关键词都命中（FTS5 默认 OR，多词时 AND 更精准）
            # 同时处理单复数：对每个词额外生成复数/单数形式，组内用 OR 连接
            english_words = re.findall(r'[a-zA-Z]+', query)
            if not english_words:
                logger.warning("[USDA] 清洗后无有效英文关键词: '{}'", query)
                conn.close()
                return []
            token_groups = []
            for word in english_words:
                group = {word}
                if not word.endswith('s') and len(word) > 2:
                    group.add(f"{word}s")
                elif word.endswith('s') and len(word) > 3:
                    group.add(word[:-1])
                token_groups.append(group)
            processed_query = ' AND '.join([
                f"({' OR '.join(sorted(group))})" if len(group) > 1 else list(group)[0]
                for group in token_groups
            ])

            # Auto-detect schema: normalized (new) vs flat (legacy)
            has_normalized = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='food_nutrients'"
            ).fetchone()

            if has_normalized:
                results = self._search_normalized(cursor, processed_query, page_size, english_words)
            else:
                results = self._search_legacy(cursor, processed_query, page_size, english_words)

            # Fallback: 如果 AND 查询无结果，改用 OR 查询（解决修饰词过多导致零命中）
            if not results and len(token_groups) > 1:
                or_query = ' OR '.join([
                    f"({' OR '.join(sorted(group))})" if len(group) > 1 else list(group)[0]
                    for group in token_groups
                ])
                logger.info("[USDA] AND 查询 '{}' 无结果，fallback 到 OR 查询 '{}'", processed_query, or_query)
                if has_normalized:
                    results = self._search_normalized(cursor, or_query, page_size, english_words)
                else:
                    results = self._search_legacy(cursor, or_query, page_size, english_words)

            conn.close()
            return results
        except Exception as e:
            logger.error("USDA search failed: {}", e)
            return []

    def _food_relevance_score(self, description: str, query_words: list[str]) -> float:
        """自定义食物描述质量评分，优先基础食材，惩罚噪声条目。"""
        desc_lower = description.lower()
        score = 0.0
        for word in query_words:
            word_lower = word.lower()
            # 以查询词作为描述开头的主词（如 "Rice, white" / "Egg, whole" / "Apples, raw"）→ 最高分
            first_term = desc_lower.split(',')[0].split(' ')[0].strip()
            if first_term.startswith(word_lower):
                score += 200
            # 描述中包含独立词
            elif any(p in desc_lower for p in [
                f", {word_lower} ", f", {word_lower},",
                f" {word_lower} ", f" {word_lower},",
            ]):
                score += 100
            elif word_lower in desc_lower:
                score += 20

        # 惩罚非基础食物（零食、饮料、加工食品等）
        noise_words = [
            "crackers", "cakes", "snacks", "candies", "puddings",
            "beverage", "restaurant", "fast foods", "babyfood",
            "breaded", "batter", "coated", "flavored", "seasoned",
            "sauce", "soup", "stew", "mix", "prepared", "entree",
            "frozen", "canned", "dried", "powder", "flour", "bran",
            "noodles", "pasta", "cereal", "crumbs", "chips",
            "nuggets", "seam fat", "external fat", "separable fat",
            "manufacturing", "juice", "sauce", "yogurt",
            "pastrami", "bologna", "sausage", "corned", "cured",
            "chopped", "smoked", "roasted", "sliced",
        ]
        for nw in noise_words:
            if nw in desc_lower:
                score -= 150

        # 奖励基础状态（raw / cooked / fresh / whole / lean / ground）
        bonus_words = ["raw", "cooked", "fresh", "whole", "lean", "ground"]
        for bw in bonus_words:
            if bw in desc_lower:
                score += 50

        # 短描述加分（基础食材通常较短）
        score -= len(description) * 0.1
        return score

    def _search_normalized(self, cursor, query: str, page_size: int, query_words: list[str]) -> list[dict[str, Any]]:
        """Query the normalized schema with full nutrient profiles."""
        # 先按是否有能量数据排序（有能量的优先），再按 bm25 排序。
        # 避免大量无能量数据的 brand/sample 条目占据前排，导致基础食材被 LIMIT 截断。
        cursor.execute(
            """
            SELECT f.fdc_id, f.description,
                   EXISTS (
                       SELECT 1 FROM food_nutrients fn
                       WHERE fn.fdc_id = f.fdc_id
                         AND fn.nutrient_id IN (1008, 2047, 2048)
                         AND fn.amount > 0
                   ) AS has_energy
            FROM foods f
            JOIN foods_fts fts ON f.fdc_id = fts.fdc_id
            WHERE fts.description MATCH ?
              AND f.description NOT LIKE 'Minerals,%'
              AND f.description NOT LIKE 'Proximates,%'
              AND f.description NOT LIKE 'Sugars,%'
              AND f.description NOT LIKE 'Fatty Acids,%'
              AND f.description NOT LIKE 'Vitamins,%'
              AND f.description NOT LIKE 'Cholesterol,%'
            ORDER BY has_energy DESC, bm25(foods_fts)
            LIMIT ?
            """,
            (query, page_size * 100),
        )
        food_rows = cursor.fetchall()

        target_nids = set(self.NUTRIENT_MAP.keys())
        results = []

        for food in food_rows:
            fdc_id = food["fdc_id"]

            cursor.execute(
                "SELECT nutrient_id, amount FROM food_nutrients WHERE fdc_id = ?",
                (fdc_id,),
            )

            calories = 0.0
            macros: dict[str, float] = {}

            for nrow in cursor.fetchall():
                nid = nrow["nutrient_id"]
                if nid not in target_nids:
                    continue
                amount = nrow["amount"]
                field_name, _ = self.NUTRIENT_MAP[nid]

                if field_name in ("energy", "energy_atwater", "energy_atwater_sp"):
                    if field_name == "energy_atwater_sp" or (field_name == "energy_atwater" and calories == 0.0) or (field_name == "energy" and calories == 0.0):
                        calories = round(amount, 1)
                    continue

                if field_name in self.DV_BASES:
                    amount = round(amount / self.DV_BASES[field_name] * 100, 1)
                else:
                    amount = round(amount, 2)
                macros[field_name] = amount

            results.append({
                "name": food["description"],
                "calories_per_100g": calories,
                "macros_per_100g": macros,
            })

        valid_results = [r for r in results if r["calories_per_100g"] > 0]
        valid_results.sort(key=lambda r: self._food_relevance_score(r["name"], query_words), reverse=True)
        return valid_results[:page_size]

    def _search_legacy(self, cursor, query: str, page_size: int, query_words: list[str]) -> list[dict[str, Any]]:
        """Backward-compatible query for the old flat schema."""
        cursor.execute(
            """
            SELECT f.*
            FROM foods f
            JOIN foods_fts fts ON f.fdc_id = fts.fdc_id
            WHERE fts.description MATCH ?
              AND f.description NOT LIKE 'Minerals,%'
              AND f.description NOT LIKE 'Proximates,%'
              AND f.description NOT LIKE 'Sugars,%'
              AND f.description NOT LIKE 'Fatty Acids,%'
              AND f.description NOT LIKE 'Vitamins,%'
              AND f.description NOT LIKE 'Cholesterol,%'
            ORDER BY (f.energy > 0) DESC, bm25(foods_fts)
            LIMIT ?
            """,
            (query, page_size * 100),
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "name": row["description"],
                "calories_per_100g": row["energy"],
                "macros_per_100g": {
                    "protein": row["protein"],
                    "carbs": row["carbs"],
                    "fat": row["fat"],
                    "sodium": row["sodium"],
                    "potassium": row["potassium"],
                    "fiber": row["fiber"],
                    "sugar": row["sugar"],
                },
            })
        valid_results = [r for r in results if r["calories_per_100g"] > 0]
        valid_results.sort(key=lambda r: self._food_relevance_score(r["name"], query_words), reverse=True)
        return valid_results[:page_size]





class MFPAdapter:
    """
    MyFitnessPal 适配器，负责维护会话并执行写入操作。
    """

    BASE_URL = "https://api.myfitnesspal.com/v2"
    TOKEN_URL = "https://www.myfitnesspal.com/user/auth_token?refresh=true"
    COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")
    JOURNAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nutrition_journal.json")

    def __init__(self, username: str | None = None):
        self.BASE_URL = "https://api.myfitnesspal.com/v2"
        # 使用类属性定义的绝对路径，确保日志始终写入项目目录
        self.JOURNAL_FILE = self.__class__.JOURNAL_FILE
        self._JOURNAL_MAX_ENTRIES = 200
        self.usda = USDALocalResolver()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        })

        self.access_token = None
        self.user_id = None
        self.token_expires_at = 0
        self._config = None

        self._load_cookies()
        self._fetch_access_token()

    def _load_config(self) -> dict[str, Any]:
        """按需加载配置，基于文件修改时间自动热更新。"""
        config_path = os.path.join(os.path.dirname(__file__), "supplements_config.yaml")
        if not os.path.exists(config_path):
            self._config = {}
            return self._config

        current_mtime = os.path.getmtime(config_path)
        if self._config is not None and hasattr(self, '_config_mtime') and self._config_mtime == current_mtime:
            return self._config  # 文件未修改，返回缓存

        try:
            with open(config_path, encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            self._config_mtime = current_mtime
            logger.info("配置文件已热更新 (mtime: {})", current_mtime)
            return self._config
        except Exception as e:
            logger.error("配置文件解析失败: {}", e)
            self._config = {}
            return self._config

    def _load_cookies(self) -> None:
        if not os.path.exists(self.COOKIES_FILE):
            logger.warning(f"未找到 {self.COOKIES_FILE}，请先执行 `refresh_login` 工具重置登录凭据。")
            return
        try:
            with open(self.COOKIES_FILE) as f:
                cookie_data = json.load(f)
            jar = requests.cookies.RequestsCookieJar()
            for cookie in cookie_data:
                jar.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ".myfitnesspal.com"), path=cookie.get("path", "/"))
            self.session.cookies.update(jar)
            logger.info("从 {} 加载了 {} 条 Cookie", self.COOKIES_FILE, len(cookie_data))
        except Exception as exc:
            logger.warning(f"加载 Cookie 文件失败，请重新登录: {exc}")

    def _fetch_access_token(self) -> None:
        if not self.session.cookies:
            logger.warning("未找到有效 Cookie，跳过 Token 获取。")
            return
        try:
            resp = self.session.get(self.TOKEN_URL)
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["access_token"]
            self.user_id = data.get("user_id") # 获取当前用户 ID
            expires_in = data.get("expires_in", 3600)  # MFP 默认 Token 有效期通常为 1 小时
            self.token_expires_at = time.time() + expires_in
            self.session.headers.update({
                "Authorization": f"Bearer {self.access_token}",
                "mfp-client-id": "mfp-main-js",
                "mfp-user-id": str(self.user_id) if self.user_id else "",
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            logger.info("Bearer Token 刷新成功 | User ID: {} | 有效期: {}s", self.user_id, expires_in)
        except Exception as exc:
            # 如果请求返回 401 且 Cookie 确实失效，主动清理
            if isinstance(exc, requests.exceptions.HTTPError) and exc.response.status_code == 401:
                logger.warning("检测到会话已彻底失效 (401)，正在置空 Token...")
                self.access_token = None
            else:
                logger.warning("获取 Token 失败，可能是网络波动或 Cookie 已失效: {}", exc)
                self.access_token = None

    def _ensure_token_valid(self) -> None:
        if time.time() > (self.token_expires_at - 3600):
            self._fetch_access_token()
        if not self.access_token:
            raise SessionExpiredError("MFP 会话已过期或未登录，请调用 `refresh_login` 工具重置登录凭据。")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def _create_custom_food(self, item: dict[str, Any]) -> dict[str, str]:
        nutritional_contents = {
            "energy": {"unit": "calories", "value": item.get("calories", 0)},
        }

        # 内部映射，将模型字段还原为 MFP 字段
        field_map = {
            "protein": "protein",
            "carbs": "carbohydrates",
            "fat": "fat",
            "sodium": "sodium",
            "potassium": "potassium",
            "iron": "iron",
            "calcium": "calcium",
            "vitamin_a": "vitamin_a",
            "vitamin_c": "vitamin_c",
            "vitamin_d": "vitamin_d",
            "fiber": "fiber",
            "sugar": "sugars",
            "cholesterol": "cholesterol",
            "saturated_fat": "saturated_fat",
            "polyunsaturated_fat": "polyunsaturated_fat",
            "monounsaturated_fat": "monounsaturated_fat",
            "trans_fat": "trans_fat"
        }

        macros_data = item.get("macros", {})
        for model_field, mfp_field in field_map.items():
            if model_field in macros_data and macros_data[model_field] is not None:
                nutritional_contents[mfp_field] = macros_data[model_field]

        food_payload = {
            "item": {
                "type": "food",
                "description": item["name"],
                "brand_name": "Auto_Nutrition",
                "serving_sizes": [{"value": 1.0, "unit": "serving(s)", "nutrition_multiplier": 1.0}],
                "nutritional_contents": nutritional_contents,
            }
        }
        micro_count = len([k for k in nutritional_contents if k != "energy"])
        logger.info("MFP Food Payload ({} micros): {}", micro_count, json.dumps(food_payload, indent=2, ensure_ascii=False))
        response = self.session.post(f"{self.BASE_URL}/foods", json=food_payload)
        response.raise_for_status()
        data = response.json()
        food_info = data["items"][0] if "items" in data else data["item"]
        return {"id": food_info["id"], "version": food_info["version"]}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def get_diary_data(self, date_str: str) -> dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/diary?entry_date={date_str}"
        response = self.session.get(endpoint)
        response.raise_for_status()
        return response.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def record_weight(self, weight_kg: float, date_str: str) -> dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/measurements"
        payload = {"items": [{"type": "measurement", "date": date_str, "value": float(weight_kg), "unit": "kg", "measurement_type": "weight"}]}
        response = self.session.post(endpoint, json=payload)
        response.raise_for_status()
        return {"status": "ok", "weight_kg": weight_kg, "date": date_str}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def record_water(self, ml: int, date_str: str) -> dict[str, Any]:
        """
        录入饮水量。
        """
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/diary/water"
        payload = {
            "date": date_str,
            "value": int(ml),
            "units": "milliliters"
        }
        # 必须确保包含特定的用户和客户端标识头部
        self.session.headers.update({
            "mfp-client-id": "mfp-main-js",
            "mfp-user-id": str(self.user_id)
        })
        response = self.session.post(endpoint, json=payload)
        response.raise_for_status()
        return {"status": "ok", "ml": ml, "date": date_str}

    def _apply_config_safeguard(self, item: dict[str, Any]) -> dict[str, Any]:
        conf_data = self._load_config()
        if not conf_data:
            return item

        # 合并不同类别的配置数据进行匹配
        matched_conf = None
        name_lower = item["name"].lower()

        # 遍历所有可能的单项配置节点进行“模糊+全量”匹配
        for section in ("supplements", "regional_foods", "common_foods"):
            section_data = conf_data.get(section, {})
            for key, conf in section_data.items():
                # 别名列表包含：Key 本身, 配置中的 Name, 以及显式定义的 Aliases
                aliases = {key.lower(), conf.get("name", "").lower()} | {a.lower() for a in conf.get("aliases", [])}
                aliases.discard("") # 移除空字符串

                for alias in aliases:
                    if all(ord(c) < 128 for c in alias):
                        # 纯英文使用单词边界正则匹配，防止 "Gel" 匹配 "Gelatin"
                        # 将下划线和空格视为等价，统一为 \s+ 或 [_\s]+ 进行匹配
                        alias_pattern = re.escape(alias).replace('_', r'[\s_]+').replace(r'\ ', r'[\s_]+')
                        if re.search(r'\b' + alias_pattern + r'\b', name_lower):
                            matched_conf = conf
                            break
                    else:
                        # 包含中文则使用子字符串匹配
                        if alias in name_lower:
                            matched_conf = conf
                            break
                if matched_conf:
                    break
            if matched_conf:
                break

        if matched_conf:
            ratio = float(item.get("serving_ratio", 1.0))
            safe_item = item.copy()
            # 如果配置中有正式名称，则使用配置名称，否则保持用户输入
            official_name = matched_conf.get("name", item["name"])

            # 核心优化：如果匹配到配置，则强制执行数值校准，防止大模型幻觉
            safe_item["name"] = f"{official_name}"
            safe_item["calories"] = round(matched_conf.get("calories", 0) * ratio, 1)

            # 合并宏量和微量元素
            combined_nutrients = matched_conf.get("macros", {}).copy()
            if "micros" in matched_conf:
                combined_nutrients.update(matched_conf["micros"])

            safe_item["macros"] = {
                k: round(v * ratio, 1) for k, v in combined_nutrients.items()
            }
            logger.info("应用配置保护: {} -> {}", item["name"], safe_item["name"])
            safe_item["_config_matched"] = True
            return safe_item

        return item

    def _parse_quantity(self, text: str) -> tuple[float, str, str]:
        """Parse quantity, unit, and food name from a string.

        Examples:
            '100g Chicken Breast' -> (1.0, '100g', 'Chicken Breast')
            '300ml Whole Milk'    -> (3.0, '300ml', 'Whole Milk')
            '1 Banana'            -> (1.0, '1', 'Banana')
            '300ml牛奶'            -> (3.0, '300ml', '牛奶')
        """
        match = re.match(r'^([\d\.]+)\s*(.*)$', text.strip())
        if match:
            qty_str, rest = match.groups()
            qty_f = float(qty_str)
            unit = ''
            name = rest.strip()

            KNOWN_UNITS = {'g', 'ml', 'oz', 'lb', 'kg', '个', '根', '片', '块', '份', '勺', '杯', 'cup', 'tsp', 'tbsp', 'serving', 'servings'}
            for u in sorted(KNOWN_UNITS, key=len, reverse=True):
                if rest.lower().startswith(u.lower()):
                    remain = rest[len(u):]
                    if remain == '' or remain.startswith(' ') or u.lower() in {'g', 'ml', 'oz', 'lb', 'kg'}:
                        unit = rest[:len(u)]
                        name = remain.strip()
                        break

            unit_lower = unit.lower()

            # 重量/容量单位 → 统一换算为"每100g"的 ratio
            if unit_lower == 'g' or unit_lower == 'ml':
                ratio = qty_f / 100.0
            elif unit_lower == 'oz':
                ratio = (qty_f * 28.35) / 100.0
            elif unit_lower == 'lb':
                ratio = (qty_f * 453.6) / 100.0
            elif unit_lower == 'kg':
                ratio = (qty_f * 1000) / 100.0
            else:
                ratio = qty_f

            return ratio, f"{qty_str}{unit}", name
        return 1.0, "1 serving", text



    def record_nutrition(self, date_str: str, meal_type: str, items: list[Any]) -> dict[str, Any]:
        self._ensure_token_valid()
        meal_map = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snacks"}
        meal_name = meal_map.get(meal_type.lower(), "Snacks")

        # 预处理：将所有输入转为 Dict，并提取份量
        # AI 预填的 calories/macros 暂存到 ai_ 前缀字段，清空主字段让管线完整执行
        processed_items = []
        for raw in items:
            if isinstance(raw, str):
                ratio, display_qty, name = self._parse_quantity(raw)
                # 提取 AI 预填的热量值：支持 "(300 kcal, ...)" 和 "300kcal" 格式
                ai_cal = None
                ai_cal_match = re.search(r'\((\d+(?:\.\d+)?)\s*kcal\b', raw, re.IGNORECASE)
                if ai_cal_match:
                    ai_cal = float(ai_cal_match.group(1))
                else:
                    ai_cal_match = re.search(r'\b(\d+(?:\.\d+)?)\s*kcal\b', raw, re.IGNORECASE)
                    if ai_cal_match:
                        ai_cal = float(ai_cal_match.group(1))
                # 从名称中移除 AI 标注的热量信息（如 "(300 kcal, ...)" 或 " 450kcal"），避免干扰后续匹配
                name = re.sub(r'\s*\(\d+(?:\.\d+)?\s*kcal[^)]*\)', '', name, flags=re.IGNORECASE).strip()
                name = re.sub(r'\s+\d+(?:\.\d+)?\s*kcal\b', '', name, flags=re.IGNORECASE).strip()
                processed_items.append({
                    "name": name,
                    "serving_ratio": ratio,
                    "display_qty": display_qty,
                    "ai_calories": ai_cal
                })
            elif isinstance(raw, dict):
                # 处理客户端可能给键名加了引号的情况，如 {'"name"': 'Apple'}
                normalized = {k.strip('"').strip("'"): v for k, v in raw.items()}
                try:
                    validated = FoodItemModel(**normalized)
                    d = validated.model_dump(exclude_unset=True)
                    # 暂存 AI 预填值，让管线优先查配置和 USDA
                    if "calories" in d and d["calories"] is not None:
                        d["ai_calories"] = d.pop("calories")
                    if "macros" in d and d["macros"] is not None:
                        d["ai_macros"] = d.pop("macros")
                    processed_items.append(d)
                except Exception as e:
                    logger.error("AI 提供的字典未能通过 Pydantic 校验: {}", e)
                    raise ValueError(f"提供的食物字典校验失败，请检查必填项(name): {e}") from e
            else: # Pydantic Model
                processed_items.append(raw.model_dump() if hasattr(raw, 'model_dump') else raw)

        # --- 组合/包展开逻辑 ---
        expanded_items = []
        conf_data = self._load_config()
        combos = conf_data.get("meal_combos", {}).copy()
        combos.update(conf_data.get("routines", {}))

        for raw_item in processed_items:
            is_combo = False
            item_name_lower = raw_item["name"].lower()
            for combo_key, combo_conf in combos.items():
                aliases = [combo_key.lower(), combo_conf.get("name", "").lower()] + [a.lower() for a in combo_conf.get("aliases", [])]
                if any(alias in item_name_lower for alias in aliases if alias):
                    logger.info("检测到组合/包匹配: {} -> 展开为 {} 项", raw_item["name"], len(combo_conf["items"]))
                    ratio = float(raw_item.get("serving_ratio", 1.0))
                    for c_item in combo_conf["items"]:
                        new_item = c_item.copy()
                        new_item["calories"] = round(new_item.get("calories", 0) * ratio, 1)
                        if "macros" in new_item:
                            new_item["macros"] = {k: round(v * ratio, 1) for k, v in new_item["macros"].items()}
                        if "micros" in new_item:
                            new_item.setdefault("macros", {})
                            for mk, mv in new_item["micros"].items():
                                new_item["macros"][mk] = round(mv * ratio, 1)
                        expanded_items.append(new_item)
                    is_combo = True
                    break
            if not is_combo:
                expanded_items.append(raw_item)

        results = []
        processed_items = []
        for raw_item in expanded_items:
            # 提取 AI 暂存值
            ai_calories = raw_item.pop("ai_calories", None)
            ai_macros = raw_item.pop("ai_macros", None)

            # Level 1: 本地配置 (supplements_config.yaml) — 始终执行，优先级最高
            item = self._apply_config_safeguard(raw_item)
            config_matched = item.get("_config_matched", False)

            # Level 2: USDA 数据库 — 配置未命中时执行
            if not config_matched and (item.get("calories") is None or item.get("calories", 0) == 0):
                name_for_search = item["name"]
                logger.info("Level 2 | 本地未匹配，尝试 USDA 搜索: {}", name_for_search)
                try:
                    usda_results = self.usda.search(name_for_search, page_size=1)
                    if usda_results:
                        top = usda_results[0]
                        ratio = float(item.get("serving_ratio", 1.0))
                        item["calories"] = round(top["calories_per_100g"] * ratio, 1)
                        item["macros"] = {k: round(v * ratio, 1) for k, v in top["macros_per_100g"].items()}
                        logger.info("Level 2 | USDA 匹配成功: {} ({} kcal)", top["name"], item["calories"])
                except Exception as e:
                    logger.warning("Level 2 | USDA 搜索异常: {}", e)

            # Level 3: AI 预填值 — 配置和 USDA 都未命中时，使用 AI 估算作为 fallback
            if (item.get("calories") is None or item.get("calories", 0) == 0) and ai_calories:
                item["calories"] = ai_calories
                if ai_macros:
                    # ai_macros 可能是 NutritionModel dict，需要提取有效字段
                    if isinstance(ai_macros, dict):
                        item["macros"] = {k: v for k, v in ai_macros.items() if v is not None}
                    else:
                        item["macros"] = ai_macros
                logger.info("Level 3 | 使用 AI 估算数据: {} ({} kcal)", item["name"], ai_calories)

            # Level 4: 兜底 — 所有数据源均未命中，标记警告
            if item.get("calories") is None or item.get("calories", 0) == 0:
                logger.warning('Level 4 | ⚠️ "{}" 未匹配到任何营养数据，将以 0 kcal 录入', item["name"])
                item["calories"] = 0
                item.setdefault("macros", {})
                item["_unmatched"] = True
            if "macros" not in item:
                item["macros"] = {}

            processed_items.append(item)

            try:
                time.sleep(0.5)
                food_ref = self._create_custom_food(item)
                diary_entry = {
                    "type": "food_entry",
                    "date": date_str,
                    "meal_name": meal_name,
                    "food": {"id": food_ref["id"], "version": food_ref["version"]},
                    "servings": 1.0,
                    "serving_size": {"value": 1.0, "unit": "serving(s)", "nutrition_multiplier": 1.0},
                    "client_id": "mfp-main-js"
                }
                self._post_diary_entry(diary_entry)
                results.append({"name": item["name"], "calories": item["calories"], "unmatched": item.get("_unmatched", False), "status": "ok"})
                logger.info('成功录入: "{name}" ({cal} kcal)', name=item["name"], cal=item["calories"])
            except requests.exceptions.HTTPError as he:
                err_detail = he.response.text if hasattr(he, 'response') and he.response is not None else str(he)
                logger.error('API 拒绝了 "{name}" 的请求: {error}', name=item["name"], error=err_detail)
                results.append({"name": item["name"], "calories": item["calories"], "unmatched": item.get("_unmatched", False), "status": "error", "error": err_detail})
            except Exception as e:
                logger.error('录入 "{name}" 失败: {error}', name=item["name"], error=e)
                results.append({"name": item["name"], "calories": item["calories"], "unmatched": item.get("_unmatched", False), "status": "error", "error": str(e)})

        # --- 本地高保真日志记录 ---
        self._log_to_local_journal(date_str, meal_name, processed_items)

        unmatched = [r["name"] for r in results if r.get("unmatched")]
        result = {"status": "ok", "count": len(results)}
        if unmatched:
            result["warnings"] = [f'⚠️ 以下食物未匹配到营养数据，以 0 kcal 录入: {", ".join(unmatched)}']
        return result

    def _log_to_local_journal(self, date_str: str, meal_name: str, items: list[dict[str, Any]]) -> None:
        """
        在本地保存完整的营养数据副本，包括 MFP 不支持的微量元素。
        采用原子写入（tempfile + os.replace）机制防崩溃。
        写入前自动清理内部字段和 None 值以节省空间。
        """
        try:
            journal = []
            if os.path.exists(self.JOURNAL_FILE):
                with open(self.JOURNAL_FILE, encoding="utf-8") as f:
                    journal = json.load(f)

            # 清理 items：去掉内部字段和 None 值
            def _clean_item(item: dict[str, Any]) -> dict[str, Any]:
                cleaned = {}
                for k, v in item.items():
                    if k.startswith("_"):
                        continue
                    if v is None:
                        continue
                    if isinstance(v, dict):
                        v = {sk: sv for sk, sv in v.items() if sv is not None}
                        if not v:
                            continue
                    cleaned[k] = v
                return cleaned

            # 日志条目结构
            entry = {
                "timestamp": datetime.now().isoformat(),
                "date": date_str,
                "meal_name": meal_name,
                "items": [_clean_item(it) for it in items]
            }
            journal.append(entry)

            # 保持近期日志 (保留最近 200 条，约 10 天的完整记录)
            if len(journal) > self._JOURNAL_MAX_ENTRIES:
                journal = journal[-self._JOURNAL_MAX_ENTRIES:]

            with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(self.JOURNAL_FILE), encoding="utf-8") as tf:
                json.dump(journal, tf, indent=2, ensure_ascii=False)
                temp_name = tf.name

            os.replace(temp_name, self.JOURNAL_FILE)
            logger.info("本地高保真日志已原子录入 ({}, {} items)", len(items), len(json.dumps(entry, ensure_ascii=False)))
        except Exception as e:
            logger.error("本地日志原子录入失败: {}", e)
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.remove(temp_name)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def get_food_entries_from_html(self, date_str: str) -> list:
        """
        从 MFP 网页端 HTML 解析出单条食物记录（含 entry ID 和所属餐次）。
        v2 API 只返回 diary_meal 聚合数据，不含可删除的 food_entry ID。
        """
        self._ensure_token_valid()
        resp = self.session.get(
            f"https://www.myfitnesspal.com/food/diary?date={date_str}",
            headers={"Accept": "text/html"}
        )
        resp.raise_for_status()
        text = resp.text

        events = []
        for m in re.finditer(r'class="meal_header"[^>]*>.*?<td[^>]*>([^<]+)', text, re.DOTALL):
            meal = m.group(1).strip()
            if meal in ("Breakfast", "Lunch", "Dinner", "Snacks"):
                events.append(("meal", m.start(), meal))

        for m in re.finditer(r'data-food-entry-id="(\d+)"[^>]*>([^<]+)', text):
            events.append(("entry", m.start(), (m.group(1), m.group(2).strip())))

        events.sort(key=lambda x: x[1])

        current_meal = None
        entries = []
        for evt_type, _, data in events:
            if evt_type == "meal":
                current_meal = data
            else:
                eid, name = data
                entries.append({"id": eid, "name": name, "meal": current_meal})
        return entries

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def delete_diary_entry(self, entry_id: str) -> bool:
        """
        删除指定的日记条目。使用网页端 /food/remove/ 端点，需要 CSRF token。
        """
        self._ensure_token_valid()
        # 获取 CSRF token
        if not hasattr(self, '_csrf_token') or not self._csrf_token:
            resp = self.session.get(
                "https://www.myfitnesspal.com/food/diary",
                headers={"Accept": "text/html"}
            )
            match = re.search(r'name="csrf-token"\s+content="([^"]+)"', resp.text)
            self._csrf_token = match.group(1) if match else ""

        endpoint = f"https://www.myfitnesspal.com/food/remove/{entry_id}"
        headers = {
            "X-CSRF-Token": self._csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/javascript, application/javascript, */*; q=0.01",
        }
        response = self.session.delete(endpoint, headers=headers)
        if response.status_code in (200, 204):
            logger.info("成功删除日记条目: {}", entry_id)
            return True
        elif response.status_code == 404:
            logger.warning("条目不存在或已被删除: {}", entry_id)
            return False
        else:
            response.raise_for_status()
            return True

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def get_nutrition_goals(self, date_str: str) -> dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/nutrition_goals?date={date_str}"
        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [{}])[0]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def _post_diary_entry(self, diary_entry: dict[str, Any]) -> None:
        """带重试的日记条目写入，供 record_nutrition 和 record_exercise 共用。"""
        response = self.session.post(f"{self.BASE_URL}/diary", json={"items": [diary_entry]})
        response.raise_for_status()

mcp = FastMCP("Auto_Nutrition")
adapter = None

def get_adapter():
    global adapter
    if adapter is None:
        adapter = MFPAdapter()
    return adapter

@mcp.tool()
def record_nutrition(date: str, meal_type: str, items: list[Any]) -> str:
    """
    Record food, nutrients, or supplements to MyFitnessPal.
    记录食物、营养素或补剂到 MyFitnessPal。

    ## Data Source Priority (automatic, no manual intervention needed)
    The system resolves nutrition data in this order:
      1. Local config (supplements_config.yaml) — user-calibrated, highest trust
      2. USDA database (usda_core.db) — standard reference data
      3. AI-provided values (from Dict input) — estimation fallback
      4. Zero with warning — last resort

    ## Input Format

    ### Preferred: String with weight in grams + English food name
    Translate food names to English and normalize weight to grams.
    Examples:
      "100g Fried Egg"       (1 egg ≈ 50g, 2 eggs = 100g)
      "120g Banana"          (1 banana ≈ 120g)
      "500g Mantis Shrimp steamed"
      "200g Cooked Rice"

    ### Fallback: Dict for regional/complex dishes unlikely in USDA
    Only use Dict when the dish is culture-specific (宫保鸡丁, Paella, etc.).
    calories and macros are OPTIONAL — system will still try config/USDA first.
      {"name": "宫保鸡丁 Kung Pao Chicken (200g)", "calories": 360,
       "macros": {"protein": 28, "carbs": 18, "fat": 16}}

    Args:
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
        meal_type (str): breakfast, lunch, dinner, or snack. | 餐次类型。
        items (List[Union[str, Dict]]): Food items as strings or dicts. | 食物列表。
    """
    try:
        mfp = get_adapter()

        # 🛡️ 服务端时间校验防护层
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        time_warnings = []
        if date != today_str:
            time_warnings.append(f"⚠️ 注意：当前日期为 {today_str}，但正在录入 {date} 的数据。")

        hour = now.hour
        expected_meals = {
            range(5, 10): "breakfast",
            range(10, 14): "lunch",
            range(14, 17): "snack",
            range(17, 21): "dinner",
        }
        expected = "snack"
        for r, m in expected_meals.items():
            if hour in r:
                expected = m
                break
        if date == today_str and meal_type.lower() != expected:
            time_warnings.append(
                f"💡 提示：当前时间 {now.strftime('%H:%M')} 通常对应 {expected}，但录入了 {meal_type}。"
            )

        result = mfp.record_nutrition(date, meal_type, items)

        output = f"成功写入 MyFitnessPal。详情: {json.dumps(result, indent=2, ensure_ascii=False)}"
        if time_warnings:
            output += "\n\n" + "\n".join(time_warnings)
        return output
    except Exception as exc:
        return f"错误: {exc}"

@mcp.tool()
def get_daily_summary(date: str) -> str:
    """
    Get a daily nutrition budget summary (calories, protein, carbs, fat) for a specific date.
    获取指定日期的每日营养预算总结（卡路里、蛋白质、碳水、脂肪）。

    Args:
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
    """
    try:
        mfp = get_adapter()
        diary_data = mfp.get_diary_data(date)

        # 尝试获取真实目标，获取失败则使用默认值
        try:
            goals = mfp.get_nutrition_goals(date)
            cal_goal = float(goals.get("energy", {}).get("value", 2800.0))
            protein_goal = float(goals.get("protein", 210.0))
            carbs_goal = float(goals.get("carbohydrates", 280.0))
            fat_goal = float(goals.get("fat", 93.0))
            logger.info("成功获取 {} 的动态营养目标", date)
        except Exception as e:
            logger.warning("获取动态目标失败，使用新版保底目标 (40/30/30): {}", e)
            cal_goal = 2800.0
            protein_goal = 210.0
            carbs_goal = 280.0
            fat_goal = 93.0

        cal_eaten = 0.0
        protein_eaten = 0.0
        carbs_eaten = 0.0
        fat_eaten = 0.0
        cal_burned = 0.0

        for item in diary_data.get("items", []):
            itype = item.get("type")
            if itype in ["diary_meal", "food_entry"]:
                nc = item.get("nutritional_contents", {})
                cal_eaten += nc.get("energy", {}).get("value", 0)
                protein_eaten += nc.get("protein", 0)
                carbs_eaten += nc.get("carbohydrates", 0)
                fat_eaten += nc.get("fat", 0)
            elif itype == "exercise_entry":
                cal_burned += item.get("energy", {}).get("value", 0)

        cal_remaining = cal_goal - cal_eaten + cal_burned


        # 用户体征数据 (原 get_user_metadata 功能)
        user_section = ""
        try:
            weight_resp = mfp.session.get(f"{mfp.BASE_URL}/measurements?type=weight")
            weight_resp.raise_for_status()
            weights = weight_resp.json().get("items", [])
            if weights:
                latest_weight = weights[0].get("value")
                user_section = f"\n👤 当前体重: {latest_weight}kg"
        except Exception:
            pass

        output = (
            f"📅 {date} 营养预算总结:\n"
            f"🔥 卡路里: {round(cal_goal)} (目标) - {round(cal_eaten)} (已吃) + {round(cal_burned)} (运动) = {round(cal_remaining)} (剩余)\n"
            f"🥩 蛋白质剩余: {round(max(0, protein_goal - protein_eaten), 1)}g\n"
            f"🍞 碳水剩余: {round(max(0, carbs_goal - carbs_eaten), 1)}g\n"
            f"🥑 脂肪剩余: {round(max(0, fat_goal - fat_eaten), 1)}g\n\n"
            f"💡 建议: 您今天目前的'可用余额'剩余 {round(cal_remaining)} kcal。"
            f"{user_section}"
        )
        return output
    except Exception as exc:
        return f"获取总结失败: {exc}"



@mcp.tool()
def get_cookie_guide() -> str:
    """
    Get the manual cookie export guide for bypass Cloudflare/CAPTCHA issues.
    获取手动导出 Cookie 并修复 MFP 认证的详细教程（用于绕过防火墙或验证码）。
    """
    guide = (
        "### 🛡️ 手动认证恢复指南 (Manual Auth Bypass)\n\n"
        "由于 MyFitnessPal 启用了 Cloudflare 真人验证，自动登录有时会被拦截。您可以按照以下步骤 1 分钟内手动恢复服务：\n\n"
        "1. **安装插件**：在 Chrome 或 Edge 浏览器安装 `Cookie-Editor` (推荐) 或 `EditThisCookie` 扩展。\n"
        "2. **正常登录**：在浏览器中打开并登录 [MyFitnessPal.com](https://www.myfitnesspal.com/account/login)。\n"
        "3. **导出数据**：\n"
        "   - 点击浏览器右上角的插件图标。\n"
        "   - 点击 **Export** (导出)，选择 **JSON** 格式。\n"
        "4. **粘贴导入**：复制剪贴板中的内容，然后调用当前助手的 `import_cookies(json_data='...')` 工具，将内容直接贴入参数中。\n\n"
        "一旦完成，服务将立即满血恢复。您的 Cookie 将保留在本地，不会流向云端。"
    )
    return guide

@mcp.tool()
def import_cookies(json_data: str) -> str:
    """
    Manually import MyFitnessPal cookies from a JSON string (exported from browser extensions).
    手动导入浏览器导出的 MFP Cookie JSON 字符串，以绕过登录阻断。

    Args:
        json_data (str): The exported JSON cookies string. | 浏览器插件导出的 JSON 字符串。
    """
    try:
        data = json.loads(json_data.strip())
        if not isinstance(data, list):
            return "格式错误：请确保您粘贴的是从 Cookie-Editor 导出的 JSON 数组格式内容。"

        # 验证核心令牌是否存在
        has_token = any(c.get('name') in ['__Secure-next-auth.session-token', 'mfp-session'] for c in data)
        if not has_token:
            logger.warning("录入的 Cookie 可能缺少核心 Session 令牌，建议重新登录后导出。")

        cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # 强制重置单例
        global adapter
        adapter = None

        return "🎉 手动录入成功！服务已重载并完全恢复。您可以继续进行营养录入或查询了。"
    except Exception as e:
        logger.error("手动导入 Cookie 失败: {}", e)
        return f"导入失败：解析 JSON 时出错。请确保粘贴的是完整且格式正确的 JSON。错误信息: {e}"

@mcp.tool()
def get_nutrition_trends(days: int = 7) -> str:
    """
    Get nutrition trends for the last N days with high-fidelity micronutrients.
    获取最近 N 天的营养趋势分析，结合 MFP 宏量与本地高保真微量元素。

    Args:
        days (int): Number of days to analyze (default 7, max 30). | 需分析的天数（默认7天，上限30天）。
    """
    try:
        mfp = get_adapter()
        days = max(1, min(int(days), 30))
        from datetime import datetime, timedelta
        end_date = datetime.now()
        trends = []

        # 完整的微量营养素字段集合（排除核心宏量）
        ALL_MICRO_FIELDS = {
            "sodium", "potassium", "calcium", "iron",
            "vitamin_a", "vitamin_c", "vitamin_d",
            "fiber", "sugar", "cholesterol",
            "saturated_fat", "polyunsaturated_fat",
            "monounsaturated_fat", "trans_fat"
        }

        # 高耗时：预加载本地日志将其提至循环外
        all_logs = []
        if os.path.exists(mfp.JOURNAL_FILE):
            try:
                with open(mfp.JOURNAL_FILE, encoding="utf-8") as f:
                    all_logs = json.load(f)
            except Exception as e:
                logger.warning("预加载本地日志失败: {}", e)

        for i in range(days):
            date_str = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
            data = mfp.get_diary_data(date_str)

            # 1. 基础宏量统计 (来自 MFP 官方数据，确保包含用户手动录入项)
            day_stats = {"date": date_str, "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

            # 从 MFP 读取宏量 + 微量营养素
            # diary_meal 提供宏量聚合；food_entry 可能携带完整微量营养素
            mfp_micro_fields = set()
            for item in data.get("items", []):
                itype = item.get("type")
                if itype == "diary_meal":
                    nc = item.get("nutritional_contents", {})
                    day_stats["calories"] += nc.get("energy", {}).get("value", 0)
                    day_stats["protein"] += nc.get("protein", 0)
                    day_stats["carbs"] += nc.get("carbohydrates", 0)
                    day_stats["fat"] += nc.get("fat", 0)
                    for field in ALL_MICRO_FIELDS:
                        if field in nc:
                            val = nc[field]
                            if isinstance(val, dict):
                                val = val.get("value", 0)
                            day_stats[field] = day_stats.get(field, 0.0) + float(val)
                            mfp_micro_fields.add(field)
                elif itype == "food_entry":
                    nc = item.get("nutritional_contents", {})
                    for field in ALL_MICRO_FIELDS:
                        if field in nc:
                            val = nc[field]
                            if isinstance(val, dict):
                                val = val.get("value", 0)
                            day_stats[field] = day_stats.get(field, 0.0) + float(val)
                            mfp_micro_fields.add(field)

            # 2. 高保真微量元素增强 (来自预加载的本地 Journal)
            # 只补充 MFP 中缺失的字段，避免重复叠加
            if all_logs:
                day_logs = [log for log in all_logs if log.get("date") == date_str]
                for log in day_logs:
                    for meal_item in log.get("items", []):
                        micros = meal_item.get("macros", {})
                        for k, v in micros.items():
                            if k in ("protein", "carbs", "fat", "calories"):
                                continue
                            if k not in mfp_micro_fields and v is not None:
                                day_stats[k] = day_stats.get(k, 0.0) + float(v)

            trends.append(day_stats)

        # 3. 视觉优化：转换为 Markdown 表格
        if not trends:
            return "没有找到趋势数据。"

        # 整理表头：获取所有出现的 Key 并排序 (日期在前，宏量其次，微量在后)
        all_keys = set()
        for t in trends:
            all_keys.update(t.keys())

        core_cols = ["date", "calories", "protein", "carbs", "fat"]
        micro_cols = sorted([k for k in all_keys if k not in core_cols])
        headers = core_cols + micro_cols

        # 如果列数过多，只展示核心及有值的数据
        table = "| " + " | ".join(headers) + " |\n"
        table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

        for t in reversed(trends): # 按时间正序
            row = []
            for h in headers:
                val = t.get(h, 0.0)
                if isinstance(val, float):
                    val = round(val, 1)
                row.append(str(val))
            table += "| " + " | ".join(row) + " |\n"

        return f"### 📊 过去 {days} 天趋势分析 (高保真数据)\n\n{table}\n\n> 注：宏量元素来自 MFP，微量元素结合了本地高保真日志。"
    except Exception as exc:
        logger.error("趋势分析失败: {}", exc)
        return f"获取趋势失败: {exc}"

@mcp.tool()
def get_food_config() -> str:
    """
    Get the list of common foods and supplements from the local configuration.
    获取本地配置中的常用食物和补剂列表，用于提供点餐建议。

    Args:
        None | 无
    """
    try:
        mfp = get_adapter()
        conf = mfp._load_config()
        # 只返回食物和补剂部分，减少 token
        essential_conf = {
            "common_foods": conf.get("common_foods", {}),
            "regional_foods": conf.get("regional_foods", {}),
            "supplements": conf.get("supplements", {})
        }
        return f"本地食物库配置: {json.dumps(essential_conf, indent=2, ensure_ascii=False)}"
    except Exception as exc:
        return f"获取配置失败: {exc}"

@mcp.tool()
def delete_last_entry(date: str, count: int = 1, meal_type: str | None = None) -> str:
    """
    Delete records. Supports deleting the most recent N entries or all entries for a specific meal type.
    删除记录。支持删除最近的 N 条，或删除指定餐次（如 breakfast/lunch/dinner/snack）的所有记录。

    Args:
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
        count (int): Number of most recent items to delete. | 待删除的最近条目数。
        meal_type (str, optional): Meal type to target for deletion. | 指定删除的餐次。
    """
    try:
        mfp = get_adapter()
        # v2 API 不返回单条 food_entry，必须从 HTML 页面解析
        food_entries = mfp.get_food_entries_from_html(date)

        # 映射餐次名称
        meal_map = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snacks"}
        target_meal_name = meal_map.get(meal_type.lower()) if meal_type else None

        if target_meal_name:
            food_entries = [e for e in food_entries if e.get("meal") == target_meal_name]
            if not food_entries:
                return f"{date} 的 {meal_type} 没有找到可以删除的饮食记录。"
            # 如果指定了餐次且未特别指定数量，默认删除该餐次的所有记录
            if count == 1:
                to_delete = food_entries
            else:
                to_delete = food_entries[-count:]
        else:
            if not food_entries:
                return f"{date} 没有找到可以删除的饮食记录。"
            to_delete = food_entries[-count:]

        deleted_names = []
        for entry in to_delete:
            entry_id = entry.get("id")
            name = entry.get("name", "未知食物")
            if entry_id:
                if mfp.delete_diary_entry(entry_id):
                    deleted_names.append(name)

        if not deleted_names:
            return "未能成功删除任何条目。"

        meal_msg = f" ({meal_type})" if meal_type else ""
        return f"已成功删除以下{meal_msg}记录: {', '.join(deleted_names)}"
    except Exception as exc:
        return f"删除失败: {exc}"

@mcp.tool()
def record_exercise(exercise: ExerciseModel) -> str:
    """
    Record cardiovascular or strength exercises to MyFitnessPal.
    记录有氧运动或力量训练到 MyFitnessPal。

    Args:
        exercise (ExerciseModel): Exercise data model. | 运动数据模型。
    """
    try:
        mfp = get_adapter()
        mfp._ensure_token_valid()

        diary_entry = {
            "type": "exercise_entry",
            "date": exercise.date,
            "exercise_name": exercise.name,
            "client_id": "mfp-main-js"
        }

        if exercise.exercise_type.lower() == "cardio":
            diary_entry["exercise_type"] = "cardiovascular"
            if exercise.calories_burned:
                diary_entry["energy_burned"] = {"value": exercise.calories_burned, "unit": "calories"}
            if exercise.duration_min:
                diary_entry["duration"] = int(exercise.duration_min * 60) # 秒
        else:
            diary_entry["exercise_type"] = "strength"
            if exercise.sets:
                diary_entry["sets"] = exercise.sets
            if exercise.reps:
                diary_entry["repetitions"] = exercise.reps
            if exercise.weight_kg:
                diary_entry["weight_per_set"] = {"value": exercise.weight_kg, "unit": "kilograms"}

        mfp._post_diary_entry(diary_entry)

        type_cn = "有氧" if exercise.exercise_type.lower() == "cardio" else "力量"
        return f"成功记录{type_cn}运动: {exercise.name} ({exercise.date})。"
    except Exception as exc:
        return f"记录运动失败: {exc}"

@mcp.tool()
def record_measurement(measurement_type: str, value: float, date: str) -> str:
    """
    Record body weight (kg) or water intake (ml).
    记录体重（公斤）或饮水量（毫升）。

    Args:
        measurement_type (str): 'weight' or 'water'. | 'weight'(体重) 或 'water'(饮水)。
        value (float): Weight in kg or water in ml. | 体重(kg)或饮水量(ml)。
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
    """
    try:
        mfp = get_adapter()
        if measurement_type.lower() == "weight":
            mfp.record_weight(value, date)
            return f"体重 {value}kg 记录成功 ({date})。"
        elif measurement_type.lower() == "water":
            mfp.record_water(int(value), date)
            return f"成功记录饮水量: {int(value)}ml ({date})。"
        else:
            return f"未知类型 '{measurement_type}'，请使用 'weight' 或 'water'。"
    except Exception as exc:
        return f"失败: {exc}"

@mcp.tool()
def lookup_food_nutrition(query: str) -> str:
    """
    Look up detailed nutrition data (including micronutrients) from the local USDA FoodData Central
    SQLite database (usda_core.db).
    从本地 USDA 权威食物数据库查询完整营养数据（含微量元素）。

    ## ⚠️ MANDATORY CONSTRAINT: query MUST be in English

    The underlying FTS5 full-text index only understands English tokens.
    Passing Chinese, Japanese, Spanish, French, or any non-English text will
    return ZERO results even if the food exists in the database.

    ## Language Translation Reference (MUST translate before calling)

    | User language input          | Correct English query       |
    |------------------------------|-----------------------------|
    | 苹果 / Manzana / りんご       | Apple                       |
    | 鸡蛋 / Huevo / Ei / Œuf      | Egg                         |
    | 牛肉 / Boeuf / Carne de res  | Beef                        |
    | 鸡胸肉 / Pechuga / 鳥胸肉    | Chicken Breast              |
    | 三文鱼 / Salmón / サーモン    | Salmon                      |
    | 糙米 / Arroz integral        | Brown Rice                  |
    | 全麦面包 / Pain complet      | Whole Wheat Bread           |
    | 菠菜 / Espinaca / Épinard    | Spinach                     |
    | 牛油果 / Aguacate / Avocat   | Avocado                     |
    | 花椰菜 / Brocoli             | Broccoli                    |
    | 燕麦 / Avena / Flocons d'avoine | Oats                     |
    | 香蕉 / Plátano / Banane      | Banana                      |
    | 西红柿 / Tomate / トマト      | Tomato                      |
    | 猪肉 / Cerdo / Porc          | Pork                        |
    | 杏仁 / Almendra / Amande     | Almond                      |
    | 豆腐 / Tofu / 두부           | Tofu                        |

    ## When NOT to call this tool
    Do NOT call this tool for regional dishes that are unlikely to exist in USDA:
    - 宫保鸡丁, 佛跳墙, 打抛猪肉饭 → Use AI estimation with a full Dict instead.
    - Paella, Rendang, Biryani → AI estimation preferred.
    - Any dish with a sauce, braise, or complex spice mix → AI estimation.

    ## Unit Normalization
    Results are per 100g. To get actual nutritional values:
      actual_value = usda_per_100g_value × (actual_grams / 100)
    Common conversions before determining actual_grams:
      1 oz = 28.35g | 1 cup ≈ 240g (liquid) | 1 tbsp ≈ 15g | 1 tsp ≈ 5g

    Args:
        query (str): Food name in English ONLY (e.g., "chicken breast", "brown rice").
                     NEVER pass Chinese or other non-English characters here.
                     | 食物英文名称（严禁传入中文或其他非英文字符）。
    """
    try:
        mfp = get_adapter()
        results = mfp.usda.search(query, page_size=3)
        if not results:
            return f"未找到 '{query}' 的 USDA 数据。请尝试更通用的英文名称。"
        return f"USDA 查询结果 (每 100g): {json.dumps(results, indent=2, ensure_ascii=False)}"
    except Exception as exc:
        return f"USDA 查询失败: {exc}"

@mcp.tool()
def get_current_time() -> str:
    """
    Get the current system date and time (UTC and Local),
    with a suggested meal_type based on local time.
    获取当前时间，并根据本地时间自动建议对应的 meal_type。
    """
    try:
        now = datetime.now()
        utc_now = datetime.utcnow()
        tz_name = time.tzname[time.daylight] if hasattr(time, 'tzname') else "Unknown"

        # 服务端计算建议 meal_type，消除 AI 推断延迟
        hour = now.hour
        if 5 <= hour < 10:
            suggested_meal = "breakfast"
        elif 10 <= hour < 14:
            suggested_meal = "lunch"
        elif 14 <= hour < 17:
            suggested_meal = "snack"
        elif 17 <= hour < 21:
            suggested_meal = "dinner"
        else:
            suggested_meal = "snack"  # 夜宵归入 snack

        res = {
            "local": now.strftime("%Y-%m-%d %H:%M:%S"),
            "utc": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": tz_name,
            "date": now.strftime("%Y-%m-%d"),
            "day_of_week": now.strftime("%A"),
            "suggested_meal_type": suggested_meal,
        }
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"获取时间失败: {e}"


def main():
    """MCP Server Entry Point."""
    mcp.run()

if __name__ == "__main__":
    main()
