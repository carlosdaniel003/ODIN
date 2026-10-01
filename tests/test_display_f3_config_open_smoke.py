from __future__ import annotations

import tempfile
import tkinter as tk
import traceback
import unittest
from pathlib import Path

import numpy as np

from src.platform.display_f3_heavy_executor import F3HeavyVisionExecutor
from src.platform.display_f3_tracking_orientation_ui import (
    instalar_ui_rastreamento_objetos_display_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_visual_reference_status import instalar_status_referencias_visuais_display
from src.platform.display_reference_roi import instalar_roi_referencias_display_f3
from src.platform.display_f3_fast_expected_gate import instalar_gate_rapido_check_esperado_display_f3
import src.platform.display_production_f3 as production_module


class DisplayF3ConfigOpenSmokeTests(unittest.TestCase):
    def test_final_config_window_opens_with_real_tk(self):
        root = tk.Tk()
        root.withdraw()
        created = None
        executor = None
        try:
            instalar_status_referencias_visuais_display()
            instalar_roi_referencias_display_f3()
            instalar_gate_rapido_check_esperado_display_f3()
            # Produção real instala esta camada depois da composição base.
            # O smoke precisa abrir exatamente a classe final usada pelo botão
            # CONFIGURAR, inclusive com o executor pesado compartilhado.
            instalar_ui_rastreamento_objetos_display_f3()

            with tempfile.TemporaryDirectory() as directory:
                repository = DisplayProjectRepository(Path(directory) / "display.json")
                repository.adicionar_projeto("CM_500_L", (1920, 1080))
                repository.definir_projeto_ativo("CM_500_L")
                executor = F3HeavyVisionExecutor()
                try:
                    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
                    frame[300:780, 520:1400] = (20, 180, 240)
                    zoom_preview_calls = []
                    software_zoom_preview_calls = []

                    created = production_module.DisplayProjectConfigWindow(
                        root=root,
                        repository=repository,
                        frame_provider=lambda: frame,
                        source_frame_provider=lambda: frame,
                        on_camera_zoom_preview=lambda enabled, value: (
                            zoom_preview_calls.append(
                                (bool(enabled), float(value))
                            )
                        ),
                        on_software_zoom_preview=lambda zoom, x, y: (
                            software_zoom_preview_calls.append(
                                (float(zoom), float(x), float(y))
                            )
                        ),
                        heavy_executor=executor,
                        on_change=lambda: None,
                        on_close=lambda: None,
                    )
                    root.update_idletasks()
                    root.update()
                except Exception:
                    traceback.print_exc()
                    raise

                self.assertTrue(created.visible)
                self.assertIs(created.repository, repository)
                self.assertIsNotNone(created.zoom_source_canvas)
                self.assertIsNotNone(created.zoom_final_canvas)

                # O refresh inicial é intencionalmente diferido por after().
                # O smoke deve validar a renderização sem depender do relógio
                # do runner/Xvfb, então publica explicitamente o frame real.
                created.update_live_zoom_preview(frame)
                root.update_idletasks()

                self.assertIsNotNone(created._zoom_source_photo)
                self.assertIsNotNone(created._zoom_final_photo)

                # Os callbacks dos sliders também dependem do refresh inicial
                # diferido; exercite-os explicitamente no smoke.
                created._on_hardware_zoom_changed()
                self.assertTrue(zoom_preview_calls)

                created.software_zoom_var.set(2.0)
                created._on_software_zoom_changed()
                self.assertTrue(software_zoom_preview_calls)
                self.assertEqual(2.0, software_zoom_preview_calls[-1][0])
        finally:
            if created is not None:
                try:
                    created.close()
                except Exception:
                    pass
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_pending=True)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
