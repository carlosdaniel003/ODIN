from __future__ import annotations

import unittest

import numpy as np

from src.platform.display_production_f3 import DisplayProductionF3Mixin
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


if __name__ == "__main__":
    unittest.main()
