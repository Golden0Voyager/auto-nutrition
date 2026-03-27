import os
import json
import time
import requests
import yaml
from datetime import datetime
from typing import List, Dict, Optional, Any
from dotenv import load_dotenv
from loguru import logger
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def is_server_error(exception: BaseException) -> bool:
    if isinstance(exception, requests.exceptions.HTTPError):
        resp = getattr(exception, "response", None)
        if resp is not None and getattr(resp, "status_code", 0) >= 500:
            return True
    return False

class MacroModel(BaseModel):
    protein: float = Field(..., ge=0, description="蛋白质 (g)")
    carbs: float = Field(..., ge=0, description="碳水化合物 (g)")
    fat: float = Field(..., ge=0, description="脂肪 (g)")

class FoodItemModel(BaseModel):
    name: str = Field(..., description="食物名称")
    weight_g: Optional[float] = Field(None, description="重量 (g)")
    calories: float = Field(..., ge=0, description="热量 (kcal)")
    macros: MacroModel = Field(..., description="宏量营养素")
    serving_ratio: float = Field(default=1.0, gt=0, description="食用比例")

load_dotenv()

# 配置 loguru
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="INFO",
)

class SessionExpiredError(Exception):
    """当 MyFitnessPal 会话过期或无效时抛出"""
    pass

class MFPAdapter:
    """
    MyFitnessPal 适配器，负责维护会话并执行写入操作。
    """

    BASE_URL = "https://api.myfitnesspal.com/v2"
    TOKEN_URL = "https://www.myfitnesspal.com/user/auth_token?refresh=true"
    COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")

    def __init__(self, username: Optional[str] = None):
        self.username = username or os.getenv("MFP_USERNAME")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        })

        self.access_token = None
        self.user_id = None
        self.token_expires_at = 0
        self.supplements = {}

        self._load_cookies()
        self._fetch_access_token()

    def _load_cookies(self) -> None:
        if not os.path.exists(self.COOKIES_FILE):
            raise SessionExpiredError(f"未找到 {self.COOKIES_FILE}")
        try:
            with open(self.COOKIES_FILE, "r") as f:
                cookie_data = json.load(f)
            jar = requests.cookies.RequestsCookieJar()
            for cookie in cookie_data:
                jar.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ".myfitnesspal.com"), path=cookie.get("path", "/"))
            self.session.cookies.update(jar)
            logger.info("从 {} 加载了 {} 条 Cookie", self.COOKIES_FILE, len(cookie_data))
        except Exception as exc:
            raise SessionExpiredError(f"加载 Cookie 文件失败: {exc}")

    def _fetch_access_token(self) -> None:
        try:
            resp = self.session.get(self.TOKEN_URL)
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["access_token"]
            self.user_id = data.get("user_id")
            expires_in = data.get("expires_in", 864000)
            self.token_expires_at = time.time() + expires_in
            self.session.headers.update({
                "Authorization": f"Bearer {self.access_token}",
                "mfp-client-id": "mfp-main-js",
                "mfp-user-id": self.user_id or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            logger.info("Bearer Token 获取成功 | User ID: {}", self.user_id)
        except Exception as exc:
            raise SessionExpiredError(f"获取 Token 失败: {exc}")

    def _ensure_token_valid(self) -> None:
        if time.time() > (self.token_expires_at - 3600):
            self._fetch_access_token()

    def _create_custom_food(self, item: Dict[str, Any]) -> Dict[str, str]:
        food_payload = {
            "item": {
                "type": "food",
                "description": item["name"],
                "brand_name": "Auto_Nutrition",
                "serving_sizes": [{"value": 1.0, "unit": "serving(s)", "nutrition_multiplier": 1.0}],
                "nutritional_contents": {
                    "energy": {"unit": "calories", "value": item["calories"]},
                    "protein": item["macros"].get("protein", 0),
                    "carbohydrates": item["macros"].get("carbs", 0),
                    "fat": item["macros"].get("fat", 0),
                },
            }
        }
        response = self.session.post(f"{self.BASE_URL}/foods", json=food_payload)
        response.raise_for_status()
        data = response.json()
        food_info = data["items"][0] if "items" in data else data["item"]
        return {"id": food_info["id"], "version": food_info["version"]}

    def get_diary_data(self, date_str: str) -> Dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/diary?entry_date={date_str}"
        response = self.session.get(endpoint)
        response.raise_for_status()
        return response.json()

    def record_weight(self, weight_kg: float, date_str: str) -> Dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/measurements"
        payload = {"items": [{"type": "measurement", "date": date_str, "value": float(weight_kg), "unit": "kg", "measurement_type": "weight"}]}
        response = self.session.post(endpoint, json=payload)
        response.raise_for_status()
        return {"status": "ok", "weight_kg": weight_kg, "date": date_str}

    def record_water(self, ml: int, date_str: str) -> Dict[str, Any]:
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

    def _apply_config_safeguard(self, item: Dict[str, Any]) -> Dict[str, Any]:
        config_path = os.path.join(os.path.dirname(__file__), "supplements_config.yaml")
        if not os.path.exists(config_path):
            return item
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                conf_data = yaml.safe_load(f)
            supplements = {}
            for section in ("supplements", "regional_foods"):
                if section in conf_data: supplements.update(conf_data[section])
            
            name_lower = item["name"].lower()
            for key, conf in supplements.items():
                if key.lower() in name_lower or conf.get("name", "").lower() in name_lower:
                    ratio = float(item.get("serving_ratio", 1.0))
                    safe_item = item.copy()
                    safe_item["name"] = conf.get("name", item["name"])
                    safe_item["calories"] = round(conf.get("calories", 0) * ratio, 1)
                    m = conf.get("macros", {})
                    safe_item["macros"] = {
                        "protein": round(m.get("protein", 0) * ratio, 1),
                        "carbs": round(m.get("carbs", 0) * ratio, 1),
                        "fat": round(m.get("fat", 0) * ratio, 1)
                    }
                    return safe_item
        except: pass
        return item

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def record_nutrition(self, date_str: str, meal_type: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._ensure_token_valid()
        meal_map = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snacks"}
        meal_name = meal_map.get(meal_type.lower(), "Snacks")
        
        # --- 新增组合展开逻辑 ---
        expanded_items = []
        config_path = os.path.join(os.path.dirname(__file__), "supplements_config.yaml")
        combos = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    conf_data = yaml.safe_load(f)
                    combos = conf_data.get("meal_combos", {})
            except: pass

        for raw_item in items:
            is_combo = False
            item_name_lower = raw_item["name"].lower()
            for combo_key, combo_conf in combos.items():
                if combo_key.lower() in item_name_lower or any(a.lower() in item_name_lower for a in combo_conf.get("aliases", [])):
                    # 发现匹配组合，执行展开
                    logger.info("检测到组合匹配: {} -> 展开为 {} 项", raw_item["name"], len(combo_conf["items"]))
                    ratio = float(raw_item.get("serving_ratio", 1.0))
                    for c_item in combo_conf["items"]:
                        new_item = c_item.copy()
                        # 应用比例系数
                        new_item["calories"] = round(new_item["calories"] * ratio, 1)
                        if "macros" in new_item:
                            new_item["macros"] = {k: round(v * ratio, 1) for k, v in new_item["macros"].items()}
                        expanded_items.append(new_item)
                    is_combo = True
                    break
            
            if not is_combo:
                expanded_items.append(raw_item)
        # --- 展开结束 ---

        results = []
        for raw_item in expanded_items:
            item = self._apply_config_safeguard(raw_item)
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
            response = self.session.post(f"{self.BASE_URL}/diary", json={"items": [diary_entry]})
            response.raise_for_status()
            results.append(response.json())
            logger.info('录入 "{name}" ({cal} kcal) -> {date} / {meal}', name=item["name"], cal=item["calories"], date=date_str, meal=meal_name)
        return {"status": "ok", "count": len(results)}

    def get_nutrition_goals(self, date_str: str) -> Dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/nutrition_goals?date={date_str}"
        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [{}])[0]

    def search_food_reference(self, query: str) -> str:
        """
        [辅助方法] 为 AI 提供联网对齐后的营养参考。
        """
        # 这里预留接口，未来可对接 Nutritionix 等公开 API
        # 目前主要引导 AI 通过 Google Search 工具进行外部校验
        logger.info("执行食物营养参考搜索: {}", query)
        return f"请结合外部 Google Search 结果对 '{query}' 进行最终数值对齐。"

mcp = FastMCP("Auto_Nutrition")
adapter = None

def get_adapter():
    global adapter
    if adapter is None: adapter = MFPAdapter()
    return adapter

@mcp.tool(description="按日期和餐次记录营养信息到MyFitnessPal")
def record_nutrition(date: str, meal_type: str, items: List[FoodItemModel]) -> str:
    try:
        mfp = get_adapter()
        validated_items = [i.model_dump() for i in items]
        result = mfp.record_nutrition(date, meal_type, validated_items)
        return f"成功写入 MyFitnessPal。详情: {json.dumps(result, indent=2, ensure_ascii=False)}"
    except Exception as exc: return f"错误: {exc}"

@mcp.tool()
def get_daily_summary(date: str) -> str:
    try:
        mfp = get_adapter()
        diary_data = mfp.get_diary_data(date)
        
        # 1. 目标设定 (Goals)
        # 由于 V2 API 目标接口暂不可用，使用截图中的 2760 作为默认参考值
        cal_goal = 2760.0
        protein_goal = 138.0  # 假设值，可根据需要调整
        carbs_goal = 345.0
        fat_goal = 92.0

        # 2. 计算已吃 (Eaten) 和 运动 (Burned)
        cal_eaten = 0.0
        protein_eaten = 0.0
        carbs_eaten = 0.0
        fat_eaten = 0.0
        cal_burned = 0.0

        for item in diary_data.get("items", []):
            itype = item.get("type")
            if itype == "diary_meal":
                nc = item.get("nutritional_contents", {})
                cal_eaten += nc.get("energy", {}).get("value", 0)
                protein_eaten += nc.get("protein", 0)
                carbs_eaten += nc.get("carbohydrates", 0)
                fat_eaten += nc.get("fat", 0)
            elif itype == "exercise_entry":
                cal_burned += item.get("energy", {}).get("value", 0)

        # 3. 计算剩余 (Remaining)
        cal_remaining = cal_goal - cal_eaten + cal_burned
        
        output = (
            f"📅 {date} 营养预算总结:\n"
            f"🔥 卡路里: {round(cal_goal)} (目标) - {round(cal_eaten)} (已吃) + {round(cal_burned)} (运动) = {round(cal_remaining)} (剩余)\n"
            f"🥩 蛋白质剩余: {round(max(0, protein_goal - protein_eaten), 1)}g\n"
            f"🍞 碳水剩余: {round(max(0, carbs_goal - carbs_eaten), 1)}g\n"
            f"🥑 脂肪剩余: {round(max(0, fat_goal - fat_eaten), 1)}g\n\n"
            f"💡 建议: 您今天目前的‘可用余额’非常充足 ({round(cal_remaining)} kcal)。"
        )
        return output
    except Exception as exc: return f"获取总结失败: {exc}"

@mcp.tool()
def record_weight(weight_kg: float, date: str) -> str:
    try:
        mfp = get_adapter()
        mfp.record_weight(weight_kg, date)
        return f"体重 {weight_kg}kg 记录成功 ({date})。"
    except Exception as exc: return f"失败: {exc}"

@mcp.tool()
def record_water(ml: int, date: str) -> str:
    try:
        mfp = get_adapter()
        mfp.record_water(ml, date)
        return f"成功记录饮水量: {ml}ml ({date})。"
    except Exception as exc: return f"失败: {exc}"

if __name__ == "__main__": mcp.run()
