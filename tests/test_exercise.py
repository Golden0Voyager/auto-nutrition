"""运动记录：v2 写入、动作检索、删除。

真实接口事实（2026-10-23 实测）：
  GET  /v2/exercises/search?search=running  -> {"exercises":[{id, description}]}
  POST /v2/diary  {type:exercise_entry, exercise:{id}, duration:<秒>,
                   energy:{value,unit}, start_time:"YYYY-MM-DDTHH:MM:SS"} -> 201
  DELETE /v2/diary/{uuid} -> 204
力量动作额外字段：sets / reps_per_set / weight_per_set(磅)。
"""

from unittest.mock import MagicMock, patch


class TestSearchExercises:
    def test_returns_catalog_matches(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"exercises": [
            {"id": "134028375027565", "description": "Running (jogging), 8.4 kph"},
            {"id": "133478619213805", "description": "Running (jogging), 9.6 kph"},
        ]}
        adapter.session.get.return_value = resp

        results = adapter.search_exercises("running")
        assert len(results) == 2
        assert results[0]["id"] == "134028375027565"

    def test_empty_catalog(self, adapter):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"exercises": []}
        adapter.session.get.return_value = resp

        assert adapter.search_exercises("nope-no-such-exercise") == []


class TestRecordExerciseEntry:
    def _capture(self, adapter, **kwargs):
        adapter.session.post.return_value = MagicMock(raise_for_status=MagicMock())
        adapter.get_diary_data = MagicMock(return_value={"items": []})
        adapter.get_food_entries_from_html = MagicMock(return_value=[])
        adapter.record_exercise_entry(**kwargs)
        return adapter.session.post.call_args[1]["json"]["items"][0]

    def test_cardio_payload(self, adapter):
        entry = self._capture(
            adapter, date_str="2026-10-23", exercise_id="134028375027565",
            duration_min=30, calories=392,
        )
        assert entry["type"] == "exercise_entry"
        assert entry["exercise"] == {"id": "134028375027565"}
        assert entry["duration"] == 1800  # v2 要求秒
        assert entry["energy"] == {"value": 392, "unit": "calories"}
        assert entry["start_time"] == "2026-10-23T12:00:00"

    def test_strength_payload_uses_pounds(self, adapter):
        entry = self._capture(
            adapter, date_str="2026-10-23", exercise_id="134028370832877",
            duration_min=20, calories=150, sets=4, reps=8, weight_kg=60,
        )
        assert entry["sets"] == 4
        assert entry["reps_per_set"] == 8
        assert entry["weight_per_set"]["unit"] == "pounds"
        assert entry["weight_per_set"]["value"] > 130  # 60kg ≈ 132lb

    def test_omits_reps_when_not_strength(self, adapter):
        entry = self._capture(
            adapter, date_str="2026-10-23", exercise_id="1", duration_min=30, calories=300,
        )
        assert "sets" not in entry
        assert "reps_per_set" not in entry


class TestDeleteExerciseEntry:
    def test_deletes(self, adapter):
        adapter.session.delete.return_value = MagicMock(status_code=204)
        assert adapter.delete_exercise_entry("aa3af9f9-e2e5-43d4-9980-ceb852a9f670") is True

    def test_missing_entry(self, adapter):
        adapter.session.delete.return_value = MagicMock(status_code=404)
        assert adapter.delete_exercise_entry("nope") is False


class TestSearchExerciseTool:
    def test_lists_ids(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [
            {"id": "134028375027565", "description": "Running (jogging), 8.4 kph"},
        ]
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import search_exercise
            result = search_exercise("running")
            assert "134028375027565" in result
            assert "Running" in result

    def test_no_results(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = []
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import search_exercise
            assert "没有" in search_exercise("zzz")


class TestRecordExerciseTool:
    def _model(self, **kwargs):
        from mfp_adapter import ExerciseModel
        defaults = {"name": "Running", "exercise_type": "cardio", "date": "2026-10-23"}
        return ExerciseModel(**{**defaults, **kwargs})

    def _run(self, mock_get_adapter, model):
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import record_exercise
            return record_exercise(model)

    def test_uses_given_exercise_id(self, mock_get_adapter):
        mock_get_adapter.record_exercise_entry.return_value = {"id": "x"}
        result = self._run(mock_get_adapter, self._model(
            exercise_id="134028375027565", duration_min=30, calories_burned=300))
        assert "成功记录" in result
        mock_get_adapter.search_exercises.assert_not_called()
        kwargs = mock_get_adapter.record_exercise_entry.call_args[1]
        assert kwargs["exercise_id"] == "134028375027565"
        assert kwargs["calories"] == 300

    def test_resolves_name_via_catalog(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [
            {"id": "134028375027565", "description": "Running (jogging), 8.4 kph"},
        ]
        mock_get_adapter.record_exercise_entry.return_value = {"id": "x"}
        result = self._run(mock_get_adapter, self._model(duration_min=30, calories_burned=300))
        assert "Running (jogging), 8.4 kph" in result
        assert mock_get_adapter.record_exercise_entry.call_args[1]["exercise_id"] == "134028375027565"

    def test_unknown_exercise_points_to_search(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = []
        result = self._run(mock_get_adapter, self._model(duration_min=30))
        assert "search_exercise" in result
        mock_get_adapter.record_exercise_entry.assert_not_called()

    def test_cardio_requires_duration(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [{"id": "1", "description": "Running"}]
        result = self._run(mock_get_adapter, self._model())
        assert "duration_min" in result

    def test_strength_requires_sets_and_reps(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [{"id": "1", "description": "Bench Press"}]
        result = self._run(mock_get_adapter, self._model(exercise_type="strength"))
        assert "sets" in result

    def test_estimates_calories_when_missing(self, mock_get_adapter):
        mock_get_adapter.search_exercises.return_value = [
            {"id": "1", "description": "Running (jogging), 8.4 kph"}]
        mock_get_adapter.get_latest_weight.return_value = 70.0
        mock_get_adapter.record_exercise_entry.return_value = {"id": "x"}

        result = self._run(mock_get_adapter, self._model(duration_min=30))
        assert "估算" in result
        calories = mock_get_adapter.record_exercise_entry.call_args[1]["calories"]
        assert 250 < calories < 450  # 9.8 MET * 70kg * 0.5h ≈ 343

    def test_exception(self, mock_get_adapter):
        mock_get_adapter.search_exercises.side_effect = Exception("boom")
        assert "失败" in self._run(mock_get_adapter, self._model(duration_min=30))


class TestDeleteExerciseTool:
    def _items(self):
        return {"items": [
            {"type": "exercise_entry", "id": "e1",
             "exercise": {"description": "Running (jogging), 8.4 kph"}},
            {"type": "exercise_entry", "id": "e2",
             "exercise": {"description": "Running (jogging), 9.6 kph"}},
            {"type": "food_entry", "id": "f1"},
        ]}

    def test_delete_by_id(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = self._items()
        mock_get_adapter.delete_exercise_entry.return_value = True
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_exercise
            result = delete_exercise("2026-10-23", entry_id="e2")
            assert "已删除" in result
            mock_get_adapter.delete_exercise_entry.assert_called_once_with("e2")

    def test_delete_by_unique_name(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = self._items()
        mock_get_adapter.delete_exercise_entry.return_value = True
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_exercise
            delete_exercise("2026-10-23", name="9.6")
            mock_get_adapter.delete_exercise_entry.assert_called_once_with("e2")

    def test_ambiguous_name_lists_candidates(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = self._items()
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_exercise
            result = delete_exercise("2026-10-23", name="Running")
            assert "多个" in result
            mock_get_adapter.delete_exercise_entry.assert_not_called()

    def test_no_exercise_entries(self, mock_get_adapter):
        mock_get_adapter.get_diary_data.return_value = {"items": []}
        with patch("mfp_adapter.get_adapter", return_value=mock_get_adapter):
            from mfp_adapter import delete_exercise
            assert "没有" in delete_exercise("2026-10-23", entry_id="e1")


class TestEstimateCalories:
    def test_running_is_higher_than_yoga(self):
        from mfp_adapter import _estimate_calories
        assert _estimate_calories("Running (jogging)", 30, 70) > _estimate_calories("Yoga", 30, 70)

    def test_unknown_name_uses_default(self):
        from mfp_adapter import _estimate_calories
        assert _estimate_calories("Something Weird", 60, 70) > 0
