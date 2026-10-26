"""真实配置的 routine 结构：练前 + 练后已合并为 workout_stack。

补剂 routine 是「说一句话，记一整包」的快捷方式，键名和别名一旦被误删或
回退成 5 个，快捷方式就会静默失效，所以在 CI 里钉住结构。
"""

from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "supplements_config.yaml"


def _routines() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["routines"]


def test_routine_keys():
    assert set(_routines()) == {
        "morning_stack",
        "dinner_stack",
        "night_stack",
        "workout_stack",
    }


def test_workout_stack_contains_pre_and_post_items():
    names = [item["name"] for item in _routines()["workout_stack"]["items"]]

    assert len(names) == 3
    assert "甜菜根粉" in names  # 练前 2-2.5h
    assert any(name.startswith("Whey Protein") for name in names)
    assert any(name.startswith("Milk") for name in names)
    assert "肌酸" not in names  # 每日恒量，已移到 dinner_stack


def test_creatine_sits_in_dinner_stack():
    """肌酸是每日 3g 恒量，必须落在每天都跑的晚餐段，且只能出现一次。

    放在 workout_stack 时，训练日会在 Snacks 再记一次，而幂等键是
    (餐次, 名称)，与午餐/晚餐的键永不相等，跨餐次重复检测不到。
    """
    routines = _routines()
    dinner_names = [item["name"] for item in routines["dinner_stack"]["items"]]

    assert "肌酸" in dinner_names
    all_names = [item["name"] for conf in routines.values() for item in conf["items"]]
    assert all_names.count("肌酸") == 1


def test_legacy_aliases_removed():
    routines = _routines()
    aliases = {alias for conf in routines.values() for alias in conf.get("aliases", [])}

    for legacy in ("运动前喝的", "运动后补充", "蛋白粉牛奶", "练后补剂", "甜菜根冲剂"):
        assert legacy not in aliases
    for legacy_key in ("pre_workout_stack", "post_workout_stack"):
        assert legacy_key not in routines
