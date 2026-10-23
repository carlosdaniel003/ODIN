from __future__ import annotations

import unittest
from types import MethodType, SimpleNamespace

import numpy as np

from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_project_config import DisplayProjectConfigWindow
from src.platform.display_f3_zoom import (
    aplicar_zoom_software_frame_display_f3,
    calcular_recorte_zoom_software_display_f3,
    calcular_viewport_efetivo_display_f3,
    centro_camera_para_pan_tilt_display_f3,
    normalizar_centro_zoom_software_display_f3,
)


class DisplayF3ZoomTests(unittest.TestCase):
    def test_zoom_um_usa_frame_inteiro_e_centro_neutro(self):
        rect = calcular_recorte_zoom_software_display_f3(
            (100, 200, 3),
            1.0,
            0.9,
            0.1,
        )
        self.assertEqual((0, 0, 200, 100), rect[:4])
        self.assertEqual((0.5, 0.5), rect[4:])

    def test_centro_e_limitado_para_janela_nunca_sair_da_imagem(self):
        center_x, center_y = normalizar_centro_zoom_software_display_f3(
            2.0,
            1.0,
            0.0,
        )
        self.assertEqual(0.75, center_x)
        self.assertEqual(0.25, center_y)

        x0, y0, x1, y1, _x, _y = calcular_recorte_zoom_software_display_f3(
            (100, 200, 3),
            2.0,
            1.0,
            0.0,
        )
        self.assertEqual((100, 0, 200, 50), (x0, y0, x1, y1))

    def test_arrastar_centro_muda_regiao_entregue_ao_f3_sem_mudar_resolucao(self):
        frame = np.zeros((60, 120, 3), dtype=np.uint8)
        frame[:, :60] = 20
        frame[:, 60:] = 220

        left = aplicar_zoom_software_frame_display_f3(
            frame,
            2.0,
            0.25,
            0.5,
        )
        right = aplicar_zoom_software_frame_display_f3(
            frame,
            2.0,
            0.75,
            0.5,
        )

        self.assertEqual(frame.shape, left.shape)
        self.assertEqual(frame.shape, right.shape)
        self.assertLess(float(left.mean()), float(right.mean()))

    def test_viewport_combina_zoom_camera_e_odin_no_mapa_um_x(self):
        rect = calcular_viewport_efetivo_display_f3(
            (100, 200, 3),
            camera_zoom=2.0,
            software_zoom=2.0,
            camera_center_x=0.5,
            camera_center_y=0.5,
            software_center_x=0.5,
            software_center_y=0.5,
        )
        self.assertEqual((75, 38, 125, 63), rect[:4])
        self.assertAlmostEqual(0.5, rect[4], places=6)
        self.assertAlmostEqual(0.505, rect[5], places=6)
        self.assertEqual(4.0, rect[6])

    def test_pan_tilt_do_zoom_fisico_segue_centro_do_quadro_azul(self):
        pan, tilt = centro_camera_para_pan_tilt_display_f3(
            2.0,
            0.75,
            0.25,
            pan_limit=180.0,
            tilt_limit=180.0,
        )
        self.assertAlmostEqual(180.0, pan, places=6)
        self.assertAlmostEqual(180.0, tilt, places=6)

        pan, tilt = centro_camera_para_pan_tilt_display_f3(
            2.0,
            0.25,
            0.75,
            pan_limit=180.0,
            tilt_limit=180.0,
        )
        self.assertAlmostEqual(-180.0, pan, places=6)
        self.assertAlmostEqual(-180.0, tilt, places=6)

    def test_zoom_hardware_readback_igual_mantem_assinatura_valida(self):
        class Service:
            @staticmethod
            def tem_configuracoes_camera_ao_vivo_pendentes():
                return False

            @staticmethod
            def obter_valores_controles_camera_ao_vivo():
                return {"zoom": 250.0}

        self.assertTrue(
            DisplayProductionF3Mixin
            ._zoom_camera_hardware_ainda_aplicado_display_f3(
                Service(),
                enabled=True,
                value=250.0,
            )
        )

    def test_zoom_hardware_resetado_invalida_assinatura_logica(self):
        class Service:
            @staticmethod
            def tem_configuracoes_camera_ao_vivo_pendentes():
                return False

            @staticmethod
            def obter_valores_controles_camera_ao_vivo():
                return {"zoom": 100.0}

        self.assertFalse(
            DisplayProductionF3Mixin
            ._zoom_camera_hardware_ainda_aplicado_display_f3(
                Service(),
                enabled=True,
                value=250.0,
            )
        )

    def test_zoom_hardware_pendente_nao_dispara_reaplicacao_duplicada(self):
        class Service:
            @staticmethod
            def tem_configuracoes_camera_ao_vivo_pendentes():
                return True

            @staticmethod
            def obter_valores_controles_camera_ao_vivo():
                return {"zoom": 100.0}

        self.assertTrue(
            DisplayProductionF3Mixin
            ._zoom_camera_hardware_ainda_aplicado_display_f3(
                Service(),
                enabled=True,
                value=250.0,
            )
        )

    def test_zoom_cinco_no_canto_permanece_dentro_do_frame(self):
        x0, y0, x1, y1, center_x, center_y = (
            calcular_recorte_zoom_software_display_f3(
                (1080, 1920, 3),
                5.0,
                0.0,
                1.0,
            )
        )
        self.assertGreaterEqual(x0, 0)
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(x1, 1920)
        self.assertLessEqual(y1, 1080)
        self.assertAlmostEqual(0.1, center_x, places=3)
        self.assertAlmostEqual(0.9, center_y, places=3)



    def test_configuracao_mapa_e_recorte_usam_o_mesmo_frame_live(self):
        maps, crops = [], []
        window = SimpleNamespace(
            visible=True,
            zoom_source_canvas=object(),
            zoom_final_canvas=object(),
            _zoom_live_source_frame=None,
            _zoom_values=lambda: (130.0, 2.0, 0.25, 0.5),
            _zoom_visual_frame=lambda frame: frame,
            _draw_zoom_source_viewport=lambda frame: maps.append(frame.copy()),
            _render_bgr_zoom_canvas=lambda _canvas, frame, _photo: crops.append(frame.copy()),
            _update_zoom_labels=lambda: None,
        )
        window._render_zoom_final_only = MethodType(
            DisplayProjectConfigWindow._render_zoom_final_only, window,
        )
        first = np.full((60, 120, 3), 40, dtype=np.uint8)
        second = np.full((60, 120, 3), 220, dtype=np.uint8)
        DisplayProjectConfigWindow.update_live_zoom_preview(window, first)
        DisplayProjectConfigWindow.update_live_zoom_preview(window, second)

        self.assertEqual(2, len(maps))
        self.assertEqual(2, len(crops))
        self.assertEqual(40, int(maps[0].mean()))
        self.assertEqual(220, int(maps[1].mean()))
        self.assertEqual(40, int(crops[0].mean()))
        self.assertEqual(220, int(crops[1].mean()))
        self.assertIs(window._zoom_live_source_frame, second)

        # A câmera já enviou o frame com hardware zoom: o quadro azul
        # delimita apenas o software zoom na mesma imagem corrente.
        zoom, cx, cy, rectangle = DisplayProjectConfigWindow._effective_zoom_view(
            window, second.shape,
        )
        self.assertEqual(2.0, zoom)
        self.assertEqual((0, 15, 60, 45), rectangle)
        self.assertAlmostEqual(0.25, cx)
        self.assertAlmostEqual(0.5, cy)

    def test_arraste_zoom_fisico_move_camera_sem_modificar_zoom_odin(self):
        class Var:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        calls = []
        camera_x, camera_y = Var(0.5), Var(0.5)
        software_x, software_y = Var(0.5), Var(0.5)
        software_zoom = Var(1.0)
        window = SimpleNamespace(
            _zoom_drag_active=True,
            _zoom_drag_hardware_origin=(0.5, 0.5, 0.5, 0.5, 2.0),
            _zoom_pointer_normalized=lambda event: (event.x, event.y),
            _zoom_values=lambda: (200.0, software_zoom.get(), 0.5, 0.5),
            software_zoom_var=software_zoom,
            software_zoom_center_x_var=software_x,
            software_zoom_center_y_var=software_y,
            camera_zoom_center_x_var=camera_x,
            camera_zoom_center_y_var=camera_y,
            _publish_hardware_zoom_preview=lambda: calls.append("hardware"),
            _publish_software_zoom_preview=lambda: calls.append("software"),
            _update_zoom_labels=lambda: None,
            _update_zoom_viewport_overlay=lambda: None,
            _render_zoom_final_only=lambda: None,
        )
        DisplayProjectConfigWindow._on_zoom_viewport_drag(
            window, SimpleNamespace(x=0.7, y=0.4),
        )
        self.assertAlmostEqual(0.6, camera_x.get())
        self.assertAlmostEqual(0.45, camera_y.get())
        self.assertEqual(1.0, software_zoom.get())
        self.assertEqual(0.5, software_x.get())
        self.assertEqual(0.5, software_y.get())
        self.assertEqual(["hardware"], calls)


    def test_runtime_f3_entrega_raw_ao_mapa_e_zoom_ao_preview_operacional(self):
        raw = np.full((40, 80, 3), 80, dtype=np.uint8)
        cropped = np.full((40, 80, 3), 180, dtype=np.uint8)
        received = {}
        config = SimpleNamespace(
            visible=True,
            update_live_zoom_preview=lambda frame, **kwargs: received.update(
                {"map": frame, "map_rotation": kwargs.get("visual_rotation")}
            ),
        )
        operational = SimpleNamespace(
            update_camera_preview=lambda frame, **kwargs: received.update(
                {"f3": frame, "f3_rotation": kwargs.get("visual_rotation")}
            ),
        )
        app = SimpleNamespace(
            display_f3_ativo=True,
            display_f3_window=operational,
            camera_frame_atual=cropped,
            _display_f3_runtime_raw_frame=raw,
            _display_f3_ng_evidence_frozen=False,
            _display_project_config_window=config,
            _obter_rotacao_visual_display_f3=lambda: 180,
            _revalidar_zoom_camera_runtime_display_f3=lambda: None,
        )
        DisplayProductionF3Mixin._render_preview_display_f3_once(app)
        self.assertIs(received["map"], raw)
        self.assertIs(received["f3"], cropped)
        self.assertEqual(180, received["map_rotation"])
        self.assertEqual(180, received["f3_rotation"])

    def test_com_hardware_zoom_e_recorte_odin_arraste_move_so_software(self):
        class Var:
            def __init__(self, value):
                self.value = value

            def set(self, value):
                self.value = value

            def get(self):
                return self.value

        calls = []
        camera_x, software_x, software_zoom = Var(0.5), Var(0.5), Var(2.0)
        window = SimpleNamespace(
            _zoom_drag_active=True,
            _zoom_drag_hardware_origin=None,
            _zoom_pointer_normalized=lambda event: (event.x, event.y),
            _zoom_values=lambda: (130.0, software_zoom.get(), software_x.get(), 0.5),
            _zoom_drag_offset_x=0.0,
            _zoom_drag_offset_y=0.0,
            software_zoom_var=software_zoom,
            software_zoom_center_x_var=software_x,
            software_zoom_center_y_var=Var(0.5),
            camera_zoom_center_x_var=camera_x,
            camera_zoom_center_y_var=Var(0.5),
            _publish_hardware_zoom_preview=lambda: calls.append("hardware"),
            _publish_software_zoom_preview=lambda: calls.append("software"),
            _update_zoom_labels=lambda: None,
            _update_zoom_viewport_overlay=lambda: None,
            _render_zoom_final_only=lambda: None,
        )
        DisplayProjectConfigWindow._on_zoom_viewport_drag(
            window, SimpleNamespace(x=0.65, y=0.5),
        )
        self.assertEqual(["software"], calls)
        self.assertAlmostEqual(0.65, software_x.get())
        self.assertAlmostEqual(0.5, camera_x.get())
        self.assertAlmostEqual(2.0, software_zoom.get())

if __name__ == "__main__":
    unittest.main()
