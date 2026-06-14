from unittest.mock import patch, MagicMock

import pytest
import mfp_adapter


class TestGetAdapter:
    def setup_method(self):
        mfp_adapter.adapter = None

    def test_creates_singleton(self):
        with patch("mfp_adapter.MFPAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock()
            a = mfp_adapter.get_adapter()
            assert a is not None
            MockAdapter.assert_called_once()

    def test_returns_same_instance(self):
        with patch("mfp_adapter.MFPAdapter") as MockAdapter:
            MockAdapter.return_value = MagicMock()
            a1 = mfp_adapter.get_adapter()
            a2 = mfp_adapter.get_adapter()
            assert a1 is a2
            MockAdapter.assert_called_once()

    def test_resets_on_import_cookies(self):
        with patch("mfp_adapter.MFPAdapter") as MockAdapter:
            instance1 = MagicMock()
            instance2 = MagicMock()
            MockAdapter.side_effect = [instance1, instance2]

            a1 = mfp_adapter.get_adapter()

            mfp_adapter.adapter = None
            a2 = mfp_adapter.get_adapter()
            assert a1 is not a2


class TestMainEntryPoint:
    def test_main_function(self):
        with patch("mfp_adapter.mcp") as mock_mcp:
            from mfp_adapter import main
            main()
            mock_mcp.run.assert_called_once()

    def test_main_as_main_guard(self):
        import runpy
        from mcp.server.fastmcp import FastMCP
        with patch.object(FastMCP, "run") as mock_run:
            runpy.run_path(mfp_adapter.__file__, run_name="__main__")
            mock_run.assert_called_once()
