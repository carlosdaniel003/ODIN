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
    def test_drag_real_tk_preserva_zoom_odin_em_dois_x(self):
        instalar_status_referencias_visuais_display()
        instalar_roi_referencias_display_f3()
        instalar_gate_rapido_check_esperado_display_f3()
        instalar_ui_rastreamento_objetos_display_f3()

        root = tk.Tk()
        root.withdraw()
        created = None
        executor = F3HeavyVisionExecutor()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                repository = DisplayProjectRepository(
                    Path(temp_dir) / "display_projects.json"
                )
                repository.adicionar_projeto(
                    "CM_500_L",
                    (1920, 1080),
                )
                repository.definir_projeto_ativo("CM_500_L")

                frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
                frame[:, :960] = (20, 20, 20)
                frame[:, 960:] = (220, 220, 220)
                software_calls = []

                created = production_module.DisplayProjectConfigWindow(
                    root=root,
                    repository=repository,
                    frame_provider=lambda: frame,
                    source_frame_provider=lambda: frame,
                    on_camera_zoom_preview=lambda *_args: None,
                    on_software_zoom_preview=lambda zoom, x, y: (
                        software_calls.append(
                            (float(zoom), float(x), float(y))
                        )
                    ),
                    heavy_executor=executor,
                    on_change=lambda: None,
                    on_close=lambda: None,
                )
                created.refresh("CM_500_L")
                root.update_idletasks()
                root.update()

                created.software_zoom_var.set(2.0)
                created._on_software_zoom_changed()
                created.update_live_zoom_preview(frame)
                root.update_idletasks()
                root.update()

                self.assertAlmostEqual(
                    2.0,
                    float(created.software_zoom_var.get()),
                    places=6,
                )

                canvas = created.zoom_source_canvas
                canvas.update_idletasks()
                mapping = created._zoom_source_mapping
                self.assertIsInstance(mapping, dict)

                center_x = int(
                    round(
                        float(mapping["offset_x"])
                        + float(mapping["render_width"]) * 0.50
                    )
                )
                center_y = int(
                    round(
                        float(mapping["offset_y"])
                        + float(mapping["render_height"]) * 0.50
                    )
                )
                target_x = int(
                    round(
                        float(mapping["offset_x"])
                        + float(mapping["render_width"]) * 0.65
                    )
                )

                canvas.event_generate(
                    "<Button-1>",
                    x=center_x,
                    y=center_y,
                )
                root.update_idletasks()
                root.update()
                zoom_after_press = float(created.software_zoom_var.get())

                canvas.event_generate(
                    "<B1-Motion>",
                    x=target_x,
                    y=center_y,
                )
                root.update_idletasks()
                root.update()
                zoom_after_motion = float(created.software_zoom_var.get())

                canvas.event_generate(
                    "<ButtonRelease-1>",
                    x=target_x,
                    y=center_y,
                )
                root.update_idletasks()
                root.update()
                zoom_after_release = float(created.software_zoom_var.get())

                self.assertAlmostEqual(2.0, zoom_after_press, places=6)
                self.assertAlmostEqual(2.0, zoom_after_motion, places=6)
                self.assertAlmostEqual(2.0, zoom_after_release, places=6)
                self.assertGreater(
                    float(created.software_zoom_center_x_var.get()),
                    0.5,
                )
                self.assertTrue(software_calls)
                self.assertTrue(
                    all(
                        abs(float(call[0]) - 2.0) < 1e-6
                        for call in software_calls
                    ),
                    msg=f"software zoom callbacks: {software_calls!r}",
                )
        finally:
            if created is not None:
                try:
                    created.close()
                except Exception:
                    pass
            try:
                executor.shutdown(wait=False, cancel_pending=True)
            except Exception:
                pass
            try:
                root.update_idletasks()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass

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
                # Selecione o projeto explicitamente para validar os callbacks
                # sem depender do relógio do runner/Xvfb.
                created.refresh("CM_500_L")
                root.update_idletasks()

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
