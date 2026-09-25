from __future__ import annotations

import inspect
import unittest

import src.platform.display_f3_config_service as config_service
import src.platform.display_project_config as config_module
from src.platform.display_project_config import DisplayProjectConfigWindow
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_visual_reference_status import (
    DisplayProjectConfigPresenceWindow,
)


class DisplayF3ConfigArchitectureTests(unittest.TestCase):
    def test_canonical_open_returns_to_tk_before_building_window(self):
        source = inspect.getsource(
            DisplayProductionF3Mixin.abrir_configuracao_projeto_display
        )
        self.assertIn("_display_f3_configuration_opening = True", source)
        self.assertIn("root.after_idle(build)", source)
        self.assertIn("DisplayProjectConfigWindow(", source)

    def test_initial_project_load_is_deferred_after_shell_creation(self):
        source = inspect.getsource(config_module)
        self.assertIn("self._schedule_initial_refresh()", source)
        constructor_start = source.index("class DisplayProjectConfigWindow")
        constructor_end = source.index(
            "    def _widget_inside_project_scroll",
            constructor_start,
        )
        constructor = source[constructor_start:constructor_end]
        self.assertNotIn("\n        self.refresh()\n", constructor)

    def test_mask_preview_configure_event_only_schedules_work(self):
        module_source = inspect.getsource(config_module)
        self.assertIn(
            "self._on_mask_reference_preview_configure",
            module_source,
        )
        handler = inspect.getsource(
            DisplayProjectConfigWindow._on_mask_reference_preview_configure
        )
        self.assertIn("after_cancel", handler)
        self.assertIn("F3_CONFIG_PREVIEW_RESIZE_DEBOUNCE_MS", handler)
        self.assertNotIn("cv2.", handler)
        self.assertNotIn("update_idletasks", handler)

    def test_mask_preview_heavy_work_is_owned_by_background_service(self):
        request = inspect.getsource(
            DisplayProjectConfigWindow._render_mask_reference_preview
        )
        self.assertIn("submit_mask_reference_preview", request)
        self.assertNotIn("cv2.", request)
        self.assertNotIn("PhotoImage", request)
        worker = inspect.getsource(
            config_service.DisplayF3ConfigPreviewService._render_mask_reference_preview
        )
        self.assertIn("cv2.imread", worker)
        self.assertIn("cv2.resize", worker)
        self.assertIn("draw_reference_geometry", worker)

    def test_presence_previews_do_not_decode_images_in_tk_method(self):
        source = inspect.getsource(
            DisplayProjectConfigPresenceWindow._update_project_presence_detail
        )
        self.assertIn("get_all", source)
        self.assertIn("submit_presence_reference_preview", source)
        self.assertNotIn("cv2.imread", source)
        self.assertNotIn("_photo_from_image", source)
        self.assertNotIn("PhotoImage", source)

    def test_preview_service_has_single_worker_and_no_tk_dependency(self):
        source = inspect.getsource(config_service)
        self.assertIn('name="ODIN-F3-ConfigPreview"', source)
        self.assertIn("self._pending[str(key)] = request", source)
        self.assertIn("self._queued", source)
        self.assertNotIn("import tkinter", source)
        self.assertNotIn("tk.", source)


if __name__ == "__main__":
    unittest.main()
