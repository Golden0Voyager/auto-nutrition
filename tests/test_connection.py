import json
from datetime import datetime

from mfp_adapter import MFPAdapter, SessionExpiredError


def test_mfp_connection():
    """
    端到端连通性测试：
    1. 从 Cookie 建立会话
    2. 获取 Bearer Token
    3. 录入 1 kcal 测试数据到今天的 Snack
    """
    print("=" * 50)
    print("  Auto_Nutrition 连通性测试")
    print("=" * 50)

    try:
        # Step 1 & 2: 初始化 Adapter（内部完成 Cookie 加载 + Token 获取）
        print("\n[1/3] 初始化 MFP Adapter...")
        adapter = MFPAdapter()
        print(f"  ✅ User ID: {adapter.user_id}")
        print(f"  ✅ Token 有效 (前 20 字符): {adapter.access_token[:20]}...")
        print(f"  ✅ 补剂配置: {len(adapter.supplements)} 条")

        # Step 3: 录入测试
        today = datetime.now().strftime("%Y-%m-%d")
        test_items = [
            {
                "name": "自动化测试 (Auto Test - 可删除)",
                "calories": 1,
                "macros": {"protein": 0, "carbs": 0, "fat": 0},
            }
        ]

        print(f"\n[2/3] 录入测试数据: {today} / Snack / 1 kcal ...")
        result = adapter.record_nutrition(today, "snack", test_items)

        print("\n[3/3] ✅ 录入成功!")
        print(f"  返回详情: {json.dumps(result, indent=2, ensure_ascii=False)}")

        print("\n" + "=" * 50)
        print("  全部测试通过 ✅")
        print("=" * 50)
        print(f"\n💡 请打开 https://www.myfitnesspal.com/food/diary/{today}")
        print("   检查 Snack 栏是否出现 '自动化测试' 条目。")

    except SessionExpiredError as e:
        print(f"\n  ❌ 会话错误: {e}")
        print("  请在浏览器中重新登录 MFP 并更新 cookies.json。")
    except Exception as e:
        print(f"\n  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_mfp_connection()
