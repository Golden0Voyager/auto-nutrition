"""真实配置的 routine 结构：训练包已删除，所有每日补剂都落在每日段。

补剂 routine 是「说一句话，记一整包」的快捷方式，键名和别名一旦被误删或
回退，快捷方式就会静默失效，所以在 CI 里钉住结构。
"""

from pathlib import Path

import yaml

import mfp_adapter

CONFIG_PATH = Path(__file__).resolve().parent.parent / "supplements_config.yaml"


def _routines() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["routines"]


def test_routine_keys():
    assert set(_routines()) == {
        "morning_stack",
        "dinner_stack",
        "night_stack",
        "d3_k2_stack",
    }


def test_workout_stack_is_gone():
    """训练包已彻底删除：配置、每日段常量、段名别名三处都不能残留。"""
    routines = _routines()

    assert "workout_stack" not in routines
    assert "workout_stack" not in {key for key, _ in mfp_adapter.DAILY_SUPPLEMENT_SEGMENTS}
    assert "workout_stack" not in mfp_adapter._SEGMENT_ALIASES.values()
    assert "workout_stack" not in mfp_adapter._SEGMENT_LABELS


def test_d3_k2_lives_in_its_own_every_other_day_segment():
    """D3+K2 隔天 1 粒，绝不能混进晨补。

    晨补的定时任务每天都跑，把它放在 morning_stack 里就会天天记一遍，
    journal 的维生素 D 摄入凭空翻倍。所以它单独成段，且**不在**
    DAILY_SUPPLEMENT_SEGMENTS 里——「全天补剂」不会写它，只有
    segments=["d3"] 显式点名才写。
    """
    routines = _routines()
    morning_names = [item["name"] for item in routines["morning_stack"]["items"]]

    assert "D3+K2" not in morning_names
    assert [item["name"] for item in routines["d3_k2_stack"]["items"]] == ["D3+K2"]
    all_names = [item["name"] for conf in routines.values() for item in conf["items"]]
    assert all_names.count("D3+K2") == 1

    standard_keys = {key for key, _ in mfp_adapter.DAILY_SUPPLEMENT_SEGMENTS}
    extra_keys = {key for key, _ in mfp_adapter.EXTRA_SUPPLEMENT_SEGMENTS}
    assert "d3_k2_stack" not in standard_keys
    assert "d3_k2_stack" in extra_keys


def test_vitamin_c_lives_in_morning_stack_only_once():
    """汤臣倍健维C片 2026-11-08 入档：常规日只在早餐后 1 片。

    晚餐那片是「大跑量/关节高负荷日选加」，不能进固定栈——晨补和晚餐补剂
    每天都由定时任务写入，放进去会让休息日凭空多出 120mg 维C。
    """
    routines = _routines()
    morning_names = [item["name"] for item in routines["morning_stack"]["items"]]
    all_names = [item["name"] for conf in routines.values() for item in conf["items"]]

    assert "维生素C" in morning_names
    assert all_names.count("维生素C") == 1


def test_whey_and_milk_sit_with_creatine_in_dinner_stack():
    """肌酸 + 蛋白粉 15g + 牛奶 250ml 是同一杯混合饮，三者同段每天各记一次。"""
    routines = _routines()
    dinner_items = routines["dinner_stack"]["items"]
    dinner_names = [item["name"] for item in dinner_items]

    assert "肌酸" in dinner_names
    assert "蛋白粉15g" in dinner_names
    assert "Milk (Full Cream, 250ml)" in dinner_names

    whey = [item for item in dinner_items if item["name"] == "蛋白粉15g"]
    assert len(whey) == 1
    assert whey[0]["calories"] == 60
    assert whey[0]["macros"] == {"carbs": 1.5, "protein": 12, "fat": 0.75}

    all_names = [item["name"] for conf in routines.values() for item in conf["items"]]
    assert all_names.count("蛋白粉15g") == 1
    assert all_names.count("Milk (Full Cream, 250ml)") == 1
    assert "甜菜根粉" not in all_names  # 训练包已删除


def test_legacy_aliases_removed():
    routines = _routines()
    aliases = {alias for conf in routines.values() for alias in conf.get("aliases", [])}

    for legacy in ("运动前喝的", "运动后补充", "蛋白粉牛奶", "练后补剂", "甜菜根冲剂"):
        assert legacy not in aliases
    for legacy_key in ("pre_workout_stack", "post_workout_stack", "workout_stack"):
        assert legacy_key not in routines
