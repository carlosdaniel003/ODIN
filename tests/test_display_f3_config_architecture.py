from __future__ import annotations

import inspect
import unittest

import numpy as np

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
        self.assertIn("root.after(1, build)", source)
        self.assertNotIn("root.after_idle(build)", source)
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

    def test_configuracao_f3_expoe_os_dois_zooms_no_projeto(self):
        source = inspect.getsource(config_module.DisplayProjectConfigWindow)
        self.assertIn("ZOOM DA CÂMERA / ODIN", source)
        self.assertIn("Usar zoom digital da câmera", source)
        self.assertIn("Zoom ODIN (software)", source)
        self.assertIn("salvar_zoom_projeto", source)

    def test_configuracao_zoom_tem_preview_final_e_viewport_arrastavel(self):
        source = inspect.getsource(config_module.DisplayProjectConfigWindow)
        self.assertIn("ENQUADRAMENTO • ARRASTE A JANELA", source)
        self.assertIn("VISUALIZAÇÃO AO VIVO • SAÍDA FINAL DO F3", source)
        self.assertIn("<B1-Motion>", source)
        self.assertIn("software_zoom_center_x_var", source)
        self.assertIn("software_zoom_center_y_var", source)

    def test_preview_de_zoom_reutiliza_scheduler_sem_criar_timer_proprio(self):
        source = inspect.getsource(
            DisplayProjectConfigWindow.update_live_zoom_preview
        )
        self.assertNotIn(".after(", source)
        self.assertIn("aplicar_zoom_software_frame_display_f3", source)

        production = inspect.getsource(
            DisplayProductionF3Mixin._render_preview_display_f3_once
        )
        self.assertIn("update_live_zoom_preview", production)
        self.assertIn("_display_f3_runtime_raw_frame", production)

    def test_zoom_software_mantem_resolucao_e_amplia_crop_central(self):
        frame = np.zeros((12, 20, 3), dtype=np.uint8)
        frame[3:9, 5:15] = 200
        zoomed = DisplayProductionF3Mixin._aplicar_zoom_software_frame_display_f3(
            frame,
            2.0,
        )
        self.assertEqual(frame.shape, zoomed.shape)
        self.assertGreater(float(zoomed.mean()), float(frame.mean()))

    def test_zoom_de_hardware_so_e_aplicado_com_f3_ativo(self):
        source = inspect.getsource(
            DisplayProductionF3Mixin._aplicar_zoom_camera_projeto_display_f3
        )
        self.assertIn('"display_f3_ativo"', source)
        self.assertLess(
            source.index('"display_f3_ativo"'),
            source.index("atualizar_configuracoes_camera_ao_vivo"),
        )

    def test_zoom_software_nao_le_repositorio_no_hot_path(self):
        source = inspect.getsource(
            DisplayProductionF3Mixin._obter_frame_runtime_display_f3
        )
        self.assertIn("_display_f3_zoom_runtime_config", source)
        self.assertNotIn("carregar_projeto(", source)
        self.assertNotIn("obter_projeto_ativo(", source)

    def test_preview_service_uses_canonical_heavy_executor_and_no_tk(self):
        source = inspect.getsource(config_service)
        self.assertIn("self._executor.submit(", source)
        self.assertIn("F3HeavyWorkPriority.LOW", source)
        self.assertIn("replace_pending=True", source)
        self.assertIn("maxsize=F3_CONFIG_PREVIEW_RESULT_LIMIT", source)
        self.assertNotIn("threading.Thread(", source)
        self.assertNotIn("import tkinter", source)
        self.assertNotIn("tk.", source)


if __name__ == "__main__":
    unittest.main()
