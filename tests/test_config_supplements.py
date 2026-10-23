"""真实配置的日常补剂锚点：9 款产品必须能被口语别名解析到正确剂量。

这些断言针对仓库里的 supplements_config.yaml，而不是测试内造的假配置——
补剂库的价值全在「说别名 → 拿到准确营养值」，条目被误删或剂量被改小
都会让记账失真，所以在这里钉住。
"""

import pytest

from mfp_adapter import MFPAdapter

# (口语输入, 名称标记, 期望热量, 关键营养素)
DAILY_SUPPLEMENTS = [
    ("D3", "Sports Research", 0.0, {"vitamin_d": 625, "vitamin_k": 100}),
    ("鱼油", "Swisse", 10.0, {"epa": 180, "dha": 120}),
    ("B族", "康纽莱", 0.0, {"vitamin_b1": 7.5, "vitamin_b2": 6, "vitamin_b6": 6}),
    ("Move Free", "Move Free", 0.0, {"glucosamine": 1500, "calcium": 46.2}),
    ("姜黄素", "Piping Rock", 0.0, {"curcumin": 1000, "piperine": 5}),
    ("辅酶Q10", "三金牌", 0.0, {"coq10": 45}),
    ("锌镁片", "诺特兰德", 4.8, {"magnesium": 265, "zinc": 10.5}),
    ("甜菜根冲剂", "Beetroot", 35.0, {"potassium": 250}),
    ("肌酸", "Creatine Monohydrate", 0.0, {}),
]


@pytest.fixture
def real_adapter():
    """直连仓库真实配置的适配器（不加载网络/凭据）。"""
    adapter = MFPAdapter.__new__(MFPAdapter)
    adapter._config = None
    return adapter


@pytest.mark.parametrize("query, marker, calories, nutrients", DAILY_SUPPLEMENTS)
def test_daily_supplement_alias_resolves(real_adapter, query, marker, calories, nutrients):
    item = real_adapter._apply_config_safeguard({"name": query})

    assert item.get("_config_matched") is True, f"「{query}」没有命中任何补剂配置"
    assert marker in item["name"]
    assert item["calories"] == calories
    for key, expected in nutrients.items():
        assert item["macros"][key] == expected, f"「{query}」的 {key} 剂量不符"
