import pytest
from mfp_adapter import MFPAdapter


@pytest.fixture
def adapter():
    """Minimal adapter for quantity parsing tests (no network)."""
    a = MFPAdapter.__new__(MFPAdapter)
    return a


class TestParseQuantity:
    def test_grams(self, adapter):
        ratio, qty, name = adapter._parse_quantity("100g Chicken Breast")
        assert ratio == 1.0  # 100g / 100
        assert qty == "100g"
        assert name == "Chicken Breast"

    def test_milliliters(self, adapter):
        ratio, qty, name = adapter._parse_quantity("300ml Whole Milk")
        assert ratio == 3.0  # 300ml / 100
        assert qty == "300ml"
        assert name == "Whole Milk"

    def test_ounces(self, adapter):
        ratio, qty, name = adapter._parse_quantity("8oz Beef")
        assert ratio == pytest.approx(8 * 28.35 / 100)
        assert qty == "8oz"
        assert name == "Beef"

    def test_pounds(self, adapter):
        ratio, qty, name = adapter._parse_quantity("1lb Chicken")
        assert ratio == pytest.approx(453.6 / 100)
        assert qty == "1lb"
        assert name == "Chicken"

    def test_kilograms(self, adapter):
        ratio, qty, name = adapter._parse_quantity("2kg Rice")
        assert ratio == 20.0  # 2000g / 100
        assert qty == "2kg"
        assert name == "Rice"

    def test_no_unit(self, adapter):
        ratio, qty, name = adapter._parse_quantity("1 Banana")
        assert ratio == 1.0
        assert qty == "1"
        assert name == "Banana"

    def test_plain_text_no_number(self, adapter):
        ratio, qty, name = adapter._parse_quantity("Chicken Breast")
        assert ratio == 1.0
        assert qty == "1 serving"
        assert name == "Chicken Breast"

    def test_decimal_quantity(self, adapter):
        ratio, qty, name = adapter._parse_quantity("1.5 cup Rice")
        assert ratio == 1.5
        assert qty == "1.5cup"
        assert name == "Rice"

    def test_serving_unit(self, adapter):
        ratio, qty, name = adapter._parse_quantity("2 servings Pasta")
        assert ratio == 2.0
        assert name == "Pasta"

    def test_chinese_units(self, adapter):
        ratio, qty, name = adapter._parse_quantity("3个鸡蛋")
        assert ratio == 3.0
        assert name == "个鸡蛋"

    def test_250g_input(self, adapter):
        ratio, qty, name = adapter._parse_quantity("250g Salmon")
        assert ratio == 2.5
        assert name == "Salmon"

    def test_50g_small_amount(self, adapter):
        ratio, qty, name = adapter._parse_quantity("50g Oats")
        assert ratio == 0.5
        assert name == "Oats"

    def test_1000ml(self, adapter):
        ratio, qty, name = adapter._parse_quantity("1000ml Water")
        assert ratio == 10.0
        assert name == "Water"
