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

class NutritionModel(BaseModel):
    protein: float = Field(default=0, ge=0, description="Protein (g) | 蛋白质 (g)")
    carbs: float = Field(default=0, ge=0, description="Carbohydrates (g) | 碳水化合物 (g)")
    fat: float = Field(default=0, ge=0, description="Total Fat (g) | 脂肪 (g)")
    # 微量元素 (Optional)
    sodium: Optional[float] = Field(None, ge=0, description="Sodium (mg) | 钠 (mg)")
    potassium: Optional[float] = Field(None, ge=0, description="Potassium (mg) | 钾 (mg)")
    calcium: Optional[float] = Field(None, ge=0, description="Calcium (%DV) | 钙 (%DV)")
    iron: Optional[float] = Field(None, ge=0, description="Iron (%DV) | 铁 (%DV)")
    vitamin_a: Optional[float] = Field(None, ge=0, description="Vitamin A (%DV) | 维生素 A (%DV)")
    vitamin_c: Optional[float] = Field(None, ge=0, description="Vitamin C (%DV) | 维生素 C (%DV)")
    fiber: Optional[float] = Field(None, ge=0, description="Dietary Fiber (g) | 膳食纤维 (g)")
    sugar: Optional[float] = Field(None, ge=0, description="Sugar (g) | 糖分 (g)")
    vitamin_d: Optional[float] = Field(None, ge=0, description="Vitamin D (%DV) | 维生素 D (%DV)")
    cholesterol: Optional[float] = Field(None, ge=0, description="Cholesterol (mg) | 胆固醇 (mg)")
    saturated_fat: Optional[float] = Field(None, ge=0, description="Saturated Fat (g) | 饱和脂肪 (g)")
    polyunsaturated_fat: Optional[float] = Field(None, ge=0, description="Polyunsaturated Fat (g) | 多不饱和脂肪 (g)")
    monounsaturated_fat: Optional[float] = Field(None, ge=0, description="Monounsaturated Fat (g) | 单不饱和脂肪 (g)")
    trans_fat: Optional[float] = Field(None, ge=0, description="Trans Fat (g) | 反式脂肪 (g)")

class FoodItemModel(BaseModel):
    name: str = Field(..., description="Food name | 食物名称")
    calories: float = Field(..., description="Calories (kcal) | 热量 (kcal)")
    macros: NutritionModel = Field(..., description="Macro and micronutrients | 营养素指标")
    meal_type: Optional[str] = Field(None, description="Meal type (breakfast/lunch/dinner/snack) | 餐次类型")
    date: Optional[str] = Field(None, description="Date (YYYY-MM-DD) | 日期")
    serving_ratio: Optional[float] = Field(1.0, description="Serving size multiplier | 食用比例系数")

class ExerciseModel(BaseModel):
    name: str = Field(..., description="Exercise name (e.g., 'Running') | 运动名称（如：跑步）")
    exercise_type: str = Field(..., description="'cardio' or 'strength' | 'cardio'(有氧) 或 'strength'(力量)")
    date: str = Field(..., description="Date (YYYY-MM-DD) | 日期")
    calories_burned: Optional[float] = Field(None, description="Estimated calories burned | 预估消耗热量")
    duration_min: Optional[float] = Field(None, description="Duration in minutes | 运动时长（分钟）")
    sets: Optional[int] = Field(None, description="Number of sets | 组数")
    reps: Optional[int] = Field(None, description="Repetitions per set | 每组次数")
    weight_kg: Optional[float] = Field(None, description="Weight per set (kg) | 每组重量（公斤）")

load_dotenv()

# 配置 loguru
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
    level="DEBUG",
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
        self._config = None

        self._load_cookies()
        self._fetch_access_token()

    def _load_config(self) -> Dict[str, Any]:
        """按需加载并缓存配置文件内容。"""
        if self._config is not None:
            return self._config
        
        config_path = os.path.join(os.path.dirname(__file__), "supplements_config.yaml")
        if not os.path.exists(config_path):
            self._config = {}
            return self._config
            
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            return self._config
        except Exception as e:
            logger.error("配置文件解析失败: {}", e)
            self._config = {}
            return self._config

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
            logger.error("获取 Token 失败，可能是 Cookie 已失效: {}", exc)
            raise SessionExpiredError(f"获取 Token 失败 (请检查 cookies.json): {exc}")

    def _ensure_token_valid(self) -> None:
        if time.time() > (self.token_expires_at - 3600):
            self._fetch_access_token()

    def _create_custom_food(self, item: Dict[str, Any]) -> Dict[str, str]:
        nutritional_contents = {
            "energy": {"unit": "calories", "value": item["calories"]},
            "protein": item["macros"].get("protein", 0),
            "carbohydrates": item["macros"].get("carbs", 0),
            "fat": item["macros"].get("fat", 0),
        }
        
        # 映射微量营养素 (MyFitnessPal API 字段映射)
        field_map = {
            "sodium": "sodium",
            "potassium": "potassium",
            "calcium": "calcium",
            "iron": "iron",
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
        
        for model_field, mfp_field in field_map.items():
            if model_field in item["macros"] and item["macros"][model_field] is not None:
                nutritional_contents[mfp_field] = item["macros"][model_field]

        food_payload = {
            "item": {
                "type": "food",
                "description": item["name"],
                "brand_name": "Auto_Nutrition",
                "serving_sizes": [{"value": 1.0, "unit": "serving(s)", "nutrition_multiplier": 1.0}],
                "nutritional_contents": nutritional_contents,
            }
        }
        logger.info("MFP Food Payload: {}", json.dumps(food_payload, indent=2, ensure_ascii=False))
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
                
                if any(alias in name_lower for alias in aliases):
                    matched_conf = conf
                    matched_key = key
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
            return safe_item
            
        return item

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=4), retry=retry_if_exception(is_server_error))
    def record_nutrition(self, date_str: str, meal_type: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._ensure_token_valid()
        meal_map = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snacks"}
        meal_name = meal_map.get(meal_type.lower(), "Snacks")
        
        # --- 组合/包展开逻辑 ---
        expanded_items = []
        conf_data = self._load_config()
        # 统一处理 meal_combos 和 routines
        combos = conf_data.get("meal_combos", {}).copy()
        combos.update(conf_data.get("routines", {}))

        for raw_item in items:
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
                        # 同时支持组合内的 micros 字段映射到 macros
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

    def delete_diary_entry(self, entry_id: str) -> bool:
        """
        删除指定的日记条目。
        """
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/diary/{entry_id}"
        response = self.session.delete(endpoint)
        if response.status_code == 204:
            logger.info("成功删除日记条目: {}", entry_id)
            return True
        elif response.status_code == 404:
            logger.warning("条目不存在或已被删除: {}", entry_id)
            return False
        else:
            response.raise_for_status()
            return True

    def get_nutrition_goals(self, date_str: str) -> Dict[str, Any]:
        self._ensure_token_valid()
        endpoint = f"{self.BASE_URL}/nutrition_goals?date={date_str}"
        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [{}])[0]

mcp = FastMCP("Auto_Nutrition")
adapter = None

def get_adapter():
    global adapter
    if adapter is None: adapter = MFPAdapter()
    return adapter

@mcp.tool()
def record_nutrition(date: str, meal_type: str, items: List[FoodItemModel]) -> str:
    """
    Record food, nutrients, or supplements to MyFitnessPal.
    记录食物、营养素或补剂到 MyFitnessPal。
    
    Args:
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
        meal_type (str): breakfast, lunch, dinner, or snack. | 餐次类型。
        items (List[FoodItemModel]): List of food items to record. | 待记录的食物列表。
    """
    try:
        mfp = get_adapter()
        validated_items = [i.model_dump() for i in items]
        result = mfp.record_nutrition(date, meal_type, validated_items)
        return f"成功写入 MyFitnessPal。详情: {json.dumps(result, indent=2, ensure_ascii=False)}"
    except Exception as exc: return f"错误: {exc}"

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
            if itype == "diary_meal":
                nc = item.get("nutritional_contents", {})
                cal_eaten += nc.get("energy", {}).get("value", 0)
                protein_eaten += nc.get("protein", 0)
                carbs_eaten += nc.get("carbohydrates", 0)
                fat_eaten += nc.get("fat", 0)
            elif itype == "exercise_entry":
                cal_burned += item.get("energy", {}).get("value", 0)

        cal_remaining = cal_goal - cal_eaten + cal_burned
        
        output = (
            f"📅 {date} 营养预算总结:\n"
            f"🔥 卡路里: {round(cal_goal)} (目标) - {round(cal_eaten)} (已吃) + {round(cal_burned)} (运动) = {round(cal_remaining)} (剩余)\n"
            f"🥩 蛋白质剩余: {round(max(0, protein_goal - protein_eaten), 1)}g\n"
            f"🍞 碳水剩余: {round(max(0, carbs_goal - carbs_eaten), 1)}g\n"
            f"🥑 脂肪剩余: {round(max(0, fat_goal - fat_eaten), 1)}g\n\n"
            f"💡 建议: 您今天目前的‘可用余额’剩余 {round(cal_remaining)} kcal。"
        )
        return output
    except Exception as exc: return f"获取总结失败: {exc}"

@mcp.tool()
def get_user_metadata() -> str:
    """
    Get the user's latest biometric data (weight, height, age) for calorie linkage.
    获取用户最新的生物特征数据（体重、身高、年龄）用于热量联动。
    
    Args:
        None | 无
    """
    try:
        mfp = get_adapter()
        mfp._ensure_token_valid()
        
        # 1. 获取最新体重
        weight_resp = mfp.session.get(f"{mfp.BASE_URL}/measurements?type=weight")
        weight_resp.raise_for_status()
        weights = weight_resp.json().get("items", [])
        latest_weight = weights[0].get("value") if weights else 70.0 # 默认 70kg
        
        # 2. 获取用户基础资料 (年龄/身高)
        # 注意: 某些账户权限可能受限，如果失败则返回保底
        meta = {"weight_kg": latest_weight, "height_cm": 175, "age": 30}
        try:
            if mfp.user_id:
                user_resp = mfp.session.get(f"{mfp.BASE_URL}/users/{mfp.user_id}")
                user_resp.raise_for_status()
                u_data = user_resp.json().get("item", {})
                meta["height_cm"] = u_data.get("height", 175)
                # 年龄通常需要通过生日计算，或者从 profile 中取
                meta["username"] = u_data.get("username")
        except:
            pass
            
        return f"当前用户信息: {json.dumps(meta, ensure_ascii=False)}"
    except Exception as exc:
        return f"获取用户信息失败: {exc}"

@mcp.tool()
def refresh_login(username: Optional[str] = None, password: Optional[str] = None) -> str:
    """
    Refresh MyFitnessPal login cookies using a browser (Playwright). 
    If credentials are provided, it will attempt auto-fill.
    使用浏览器（Playwright）刷新 MyFitnessPal 登录状态。
    
    Args:
        username (str, optional): MFP Username/Email for auto-fill. | MFP 用户名或邮箱。
        password (str, optional): MFP Password for auto-fill. | MFP 密码。
    """
    try:
        from playwright.sync_api import sync_playwright
        import time
        
        with sync_playwright() as p:
            # 使用有头模式 (headless=False) 以便用户在必要时处理验证码
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            page = context.new_page()
            
            logger.info("正在打开 MyFitnessPal 登录页面...")
            page.goto("https://www.myfitnesspal.com/account/login", timeout=60000)
            
            if username and password:
                # 尝试自动填充
                try:
                    page.fill('input[name="username"]', username)
                    page.fill('input[name="password"]', password)
                    page.click('button[type="submit"]')
                except Exception as e:
                    logger.warning("自动填充失败，请手动输入: {}", e)
            
            logger.info("等待登录完成 (请在地浏览器中操作，完成后将自动跳转)...")
            # 等待跳转到日记或主页
            try:
                page.wait_for_url("**/diary**", timeout=120000)
            except:
                page.wait_for_url("**/home**", timeout=60000)
            
            # 获取并保存 Cookies
            cookies = context.cookies()
            with open("cookies.json", "w") as f:
                json.dump(cookies, f, indent=2)
            
            browser.close()
            return "登录成功！Cookies 已更新并刷新。您可以继续记录饮食了。"
            
    except Exception as exc:
        return f"登录失败: {exc}"

@mcp.tool()
def get_nutrition_trends(days: int = 7) -> str:
    """
    Get nutrition trends for the last N days.
    获取最近 N 天的营养趋势分析。
    
    Args:
        days (int): Number of days to analyze. | 需分析的天数（默认7天）。
    """
    try:
        mfp = get_adapter()
        from datetime import datetime, timedelta
        end_date = datetime.now()
        trends = []
        
        for i in range(days):
            date_str = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
            data = mfp.get_diary_data(date_str)
            
            day_stats = {"date": date_str, "calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "sodium": 0.0}
            for item in data.get("items", []):
                if item.get("type") == "diary_meal":
                    nc = item.get("nutritional_contents", {})
                    day_stats["calories"] += nc.get("energy", {}).get("value", 0)
                    day_stats["protein"] += nc.get("protein", 0)
                    day_stats["carbs"] += nc.get("carbohydrates", 0)
                    day_stats["fat"] += nc.get("fat", 0)
                    day_stats["sodium"] += nc.get("sodium", 0)
            trends.append(day_stats)
            
        return f"过去 {days} 天的营养趋势数据: {json.dumps(trends, indent=2, ensure_ascii=False)}"
    except Exception as exc:
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
def delete_last_entry(date: str, count: int = 1, meal_type: Optional[str] = None) -> str:
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
        diary_data = mfp.get_diary_data(date)
        items = diary_data.get("items", [])
        
        # 映射餐次名称
        meal_map = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snacks"}
        target_meal_name = meal_map.get(meal_type.lower()) if meal_type else None
        
        # 筛选出符合条件的食物条目 (diary_meal)
        food_entries = [i for i in items if i.get("type") == "diary_meal"]
        
        if target_meal_name:
            # 进一步筛选出指定餐次的条目
            food_entries = [i for i in food_entries if i.get("meal_name") == target_meal_name]
            if not food_entries:
                return f"{date} 的 {meal_type} 没有找到可以删除的饮食记录。"
            # 如果指定了餐次，默认删除该餐次的所有记录 (通过设置一个较大的 count)
            if count == 1: # 如果用户没指定具体删几条，默认删掉这顿饭全部
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
            name = entry.get("food", {}).get("description", "未知食物")
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
            if exercise.sets: diary_entry["sets"] = exercise.sets
            if exercise.reps: diary_entry["repetitions"] = exercise.reps
            if exercise.weight_kg:
                diary_entry["weight_per_set"] = {"value": exercise.weight_kg, "unit": "kilograms"}
        
        endpoint = f"{mfp.BASE_URL}/diary"
        response = mfp.session.post(endpoint, json={"items": [diary_entry]})
        response.raise_for_status()
        
        type_cn = "有氧" if exercise.exercise_type.lower() == "cardio" else "力量"
        return f"成功记录{type_cn}运动: {exercise.name} ({exercise.date})。"
    except Exception as exc:
        return f"记录运动失败: {exc}"

@mcp.tool()
def record_weight(weight_kg: float, date: str) -> str:
    """
    Record body weight (kg).
    记录体重（公斤）。
    
    Args:
        weight_kg (float): Weight in kilograms. | 体重（公斤）。
        date (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
    """
    try:
        mfp = get_adapter()
        mfp.record_weight(weight_kg, date)
        return f"体重 {weight_kg}kg 记录成功 ({date})。"
    except Exception as exc: return f"失败: {exc}"

@mcp.tool()
def record_water(ml: int, date_str: str) -> str:
    """
    Record water intake (ml).
    记录饮水量（毫升）。
    
    Args:
        ml (int): Water amount in milliliters. | 饮水量（毫升）。
        date_str (str): Date in YYYY-MM-DD format. | 日期 (YYYY-MM-DD)。
    """
    try:
        mfp = get_adapter()
        mfp.record_water(ml, date_str)
        return f"成功记录饮水量: {ml}ml ({date_str})。"
    except Exception as exc: return f"失败: {exc}"

if __name__ == "__main__": mcp.run()
