"""真实配置的日常补剂锚点：9 款产品必须能被口语别名解析到正确剂量。

这些断言针对仓库里的 supplements_config.yaml，而不是测试内造的假配置——
补剂库的价值全在「说别名 → 拿到准确营养值」，条目被误删或剂量被改小
都会让记账失真，所以在这里钉住。
"""

import pytest

from mfp_adapter import MFPAdapter, _size_scale, _size_spec

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


class TestEnglishAliasScope:
    """英文别名必须开头锚定；规格不同要按比例折算，不能直接套用配置值。

    两个真实事故：
    - ``Yogurt, plain, whole milk`` 里的 milk 命中牛奶条目，酸奶被记成 180 kcal
    - 训练包的 ``Milk (Full Cream, 250ml)`` 被 300ml 条目覆盖，多记 30 kcal
    """

    def test_milk_inside_yogurt_name_is_not_matched(self, real_adapter):
        item = real_adapter._apply_config_safeguard({"name": "Yogurt, plain, whole milk"})

        assert item.get("_config_matched") is not True

    def test_smaller_size_is_scaled_not_overridden(self, real_adapter):
        """250ml 命中 300ml 条目后应折算成 150 kcal，且保留原本的规格名。"""
        item = real_adapter._apply_config_safeguard({"name": "Milk (Full Cream, 250ml)"})

        assert item.get("_config_matched") is True
        assert item["calories"] == 150.0
        assert "250ml" in item["name"]
        assert item["macros"]["protein"] == 8.2  # 9.8 × 5/6

    def test_same_size_still_applies_config(self, real_adapter):
        item = real_adapter._apply_config_safeguard({"name": "Milk (Full Cream, 300ml)"})

        assert item.get("_config_matched") is True
        assert item["calories"] == 180

    def test_chinese_alias_keeps_substring_semantics(self, real_adapter):
        """中文别名不受影响：「一杯全脂牛奶」仍要命中。"""
        item = real_adapter._apply_config_safeguard({"name": "一杯全脂牛奶"})

        assert item.get("_config_matched") is True
        assert item["calories"] == 180

    def test_whey_english_alias_hits_config_not_usda(self, real_adapter):
        """训练包写英文 Whey Protein，缺别名会掉进 USDA 的 100g 口径（352 kcal）。"""
        item = real_adapter._apply_config_safeguard({"name": "Whey Protein"})

        assert item.get("_config_matched") is True
        assert item["calories"] == 120


class TestSizeSpec:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Milk (Full Cream, 250ml)", (250.0, "ml")),
            ("1.5l 牛奶", (1500.0, "ml")),
            ("100g Chicken", (100.0, "g")),
            ("0.5kg Beef", (500.0, "g")),
            ("300ml牛奶", (300.0, "ml")),
            ("Whey Protein", None),
            ("1large", None),
        ],
    )
    def test_extracts_first_volume_or_mass(self, text, expected):
        assert _size_spec(text) == expected

    def test_missing_size_on_one_side_means_no_spec_conversion(self):
        # (比例, 是否真的按规格算过)：False 表示沿用 serving_ratio
        assert _size_scale("牛奶", "Milk (Full Cream, 300ml)") == (1.0, False)
        assert _size_scale("Milk (Full Cream, 250ml)", "Milk") == (1.0, False)

    def test_same_unit_scales_by_ratio(self):
        ratio, applied = _size_scale("Milk (Full Cream, 250ml)", "Milk (Full Cream, 300ml)")
        assert ratio == pytest.approx(5 / 6)
        assert applied is True
        assert _size_scale("Milk (Full Cream, 300ml)", "Milk (Full Cream, 300ml)") == (1.0, True)

    def test_incomparable_units_are_rejected(self):
        assert _size_scale("250ml 牛奶", "Milk (Full Cream, 300g)") is None

    def test_display_qty_supplies_the_missing_size(self):
        """`250ml 牛奶` 的数量被 _parse_quantity 剥走了，只能从 display_qty 拿。"""
        ratio, applied = _size_scale("牛奶", "Milk (Full Cream, 300ml)", "250ml")
        assert ratio == pytest.approx(5 / 6)
        assert applied is True
        assert _size_scale("Oats", "Oats (燕麦片 15g)", "15g") == (1.0, True)
        # display_qty 是计数单位（份/勺/片）时不算规格
        assert _size_scale("牛奶", "Milk (Full Cream, 300ml)", "2份") == (1.0, False)


class TestDisplayQuantityScaling:
    """坑 1 收尾：数量写在名字前面时，配置折算也要认。

    修复前这些都会走 per-100g 语义，把配置值乘以「毫升数/100」：
      - `250ml 牛奶`      ratio 2.5 → 450 kcal（应为 150）
      - `600ml 佳得乐`    ratio 6.0 → 936 kcal（应为 156）
      - `25g 火腿片`      ratio 0.25 → 7.5 kcal（应为 30）
    """

    def test_volume_prefix_scales_against_config_size(self, real_adapter):
        item = real_adapter._apply_config_safeguard(
            {"name": "牛奶", "serving_ratio": 2.5, "display_qty": "250ml"}
        )

        assert item.get("_config_matched") is True
        assert item["calories"] == 150.0
        assert "牛奶" in item["name"]

    def test_exact_volume_prefix_is_not_multiplied(self, real_adapter):
        """`300ml 牛奶` 必须正好一份，不能因为 ratio=3 变成 540 kcal。"""
        item = real_adapter._apply_config_safeguard(
            {"name": "牛奶", "serving_ratio": 3.0, "display_qty": "300ml"}
        )

        assert item["calories"] == 180

    def test_large_volume_drink_is_not_exploded(self, real_adapter):
        """`600ml 佳得乐` 命中 600ml 条目，应正好 156 kcal 而不是 936。"""
        item = real_adapter._apply_config_safeguard(
            {"name": "佳得乐", "serving_ratio": 6.0, "display_qty": "600ml"}
        )

        assert item["calories"] == 156

    def test_small_gram_prefix_is_not_shrunk(self, real_adapter):
        """`25g 火腿片` 命中「1片约25g」条目，应正好 30 kcal 而不是 7.5。"""
        item = real_adapter._apply_config_safeguard(
            {"name": "火腿片", "serving_ratio": 0.25, "display_qty": "25g"}
        )

        assert item["calories"] == 30

    def test_count_unit_still_uses_serving_ratio(self, real_adapter):
        """`2 份 牛奶` 没有规格可比，仍按 2 份算。"""
        item = real_adapter._apply_config_safeguard(
            {"name": "牛奶", "serving_ratio": 2.0, "display_qty": "2份"}
        )

        assert item["calories"] == 360.0
