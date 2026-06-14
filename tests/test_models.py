import pytest
from pydantic import ValidationError
from mfp_adapter import NutritionModel, FoodItemModel, ExerciseModel


class TestNutritionModel:
    def test_defaults(self):
        m = NutritionModel()
        assert m.protein == 0
        assert m.carbs == 0
        assert m.fat == 0
        assert m.sodium is None
        assert m.potassium is None
        assert m.fiber is None
        assert m.sugar is None

    def test_valid_values(self):
        m = NutritionModel(protein=10, carbs=20, fat=5, sodium=100, fiber=3)
        assert m.protein == 10
        assert m.carbs == 20
        assert m.fat == 5
        assert m.sodium == 100
        assert m.fiber == 3

    def test_zero_values_allowed(self):
        m = NutritionModel(protein=0, carbs=0, fat=0)
        assert m.protein == 0

    def test_negative_protein_rejected(self):
        with pytest.raises(ValidationError):
            NutritionModel(protein=-1)

    def test_negative_carbs_rejected(self):
        with pytest.raises(ValidationError):
            NutritionModel(carbs=-5)

    def test_negative_fat_rejected(self):
        with pytest.raises(ValidationError):
            NutritionModel(fat=-0.1)

    def test_negative_optional_rejected(self):
        with pytest.raises(ValidationError):
            NutritionModel(sodium=-10)

    def test_all_micro_fields(self):
        m = NutritionModel(
            protein=10, carbs=20, fat=5,
            sodium=100, potassium=200, calcium=10, iron=5,
            vitamin_a=20, vitamin_c=30, fiber=3, sugar=5,
            vitamin_d=10, cholesterol=50, saturated_fat=2,
            polyunsaturated_fat=1, monounsaturated_fat=1.5, trans_fat=0.5,
        )
        assert m.sodium == 100
        assert m.trans_fat == 0.5


class TestFoodItemModel:
    def test_minimal_valid(self):
        item = FoodItemModel(name="Apple")
        assert item.name == "Apple"
        assert item.calories is None
        assert item.macros is None
        assert item.serving_ratio == 1.0

    def test_full_item(self):
        item = FoodItemModel(
            name="Chicken Breast",
            calories=165,
            macros=NutritionModel(protein=31, carbs=0, fat=3.6),
            meal_type="lunch",
            date="2026-01-01",
            serving_ratio=0.5,
        )
        assert item.calories == 165
        assert item.macros.protein == 31
        assert item.serving_ratio == 0.5

    def test_name_required(self):
        with pytest.raises(ValidationError):
            FoodItemModel()

    def test_negative_calories_rejected(self):
        with pytest.raises(ValidationError):
            FoodItemModel(name="X", calories=-10)

    def test_serving_ratio_default(self):
        item = FoodItemModel(name="X")
        assert item.serving_ratio == 1.0


class TestExerciseModel:
    def test_minimal_valid(self):
        ex = ExerciseModel(name="Running", exercise_type="cardio", date="2026-01-01")
        assert ex.name == "Running"
        assert ex.exercise_type == "cardio"
        assert ex.calories_burned is None
        assert ex.duration_min is None

    def test_full_exercise(self):
        ex = ExerciseModel(
            name="Bench Press",
            exercise_type="strength",
            date="2026-01-01",
            calories_burned=200,
            duration_min=45,
            sets=4,
            reps=10,
            weight_kg=80,
        )
        assert ex.sets == 4
        assert ex.weight_kg == 80

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ExerciseModel(exercise_type="cardio", date="2026-01-01")

    def test_exercise_type_required(self):
        with pytest.raises(ValidationError):
            ExerciseModel(name="Running", date="2026-01-01")

    def test_date_required(self):
        with pytest.raises(ValidationError):
            ExerciseModel(name="Running", exercise_type="cardio")
