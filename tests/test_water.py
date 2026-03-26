import logging
import json
from mfp_adapter import MFPAdapter
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO)

def test_record_water():
    try:
        print("--- 开始测试 MyFitnessPal 饮水量录入 ---")
        adapter = MFPAdapter()
        
        today = datetime.now().strftime("%Y-%m-%d")
        test_ml = 250  # 测试录入 250ml
        
        print(f"正在尝试向 {today} 录入饮水量: {test_ml}ml...")
        
        result = adapter.record_water(test_ml, today)
        
        print("✅ 饮水量录入成功！接口返回详情:")
        print(json.dumps(result, indent=2))
        
        print("\n--- 测试完成 ---")
    except Exception as e:
        print(f"❌ 录入失败: {str(e)}")

if __name__ == "__main__":
    test_record_water()
