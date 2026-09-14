from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import numpy as np

import src.platform.display_f3_mask_visibility_ui as visibility


class DisplayF3MaskVisibilityUiTests(unittest.TestCase):
    def test_inicio_f3_mostra_contorno_sem_pintar_estado(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        mask = {
            "id": "MASK_001",
            "type": "segment",
            "cx": 50,
            "cy": 50,
            "width": 30,
            "height": 12,
            "angle": 0.0,
        }
        rendered = visibility.renderizar_preview_com_guias_inicio_f3(
            frame,
            {
                "resolution": (100, 100),
                "masks": (mask,),
                "classifications": {"MASK_001": "off"},
                "expected_states": {"MASK_001": "on"},
                "has_any_on": False,
            },
        )

        # A ROI aparece desde o primeiro frame, mas o interior não é preenchido
        # de vermelho/amarelo enquanto a placa ainda não mostrou nenhum ON.
        self.assertGreater(int(rendered.sum()), 0)
        self.assertEqual(0, int(rendered[50, 50].sum()))

    def test_sem_classificacao_a_geometria_tambem_permanece_visivel(self):
        frame = np.zeros((80, 80, 3), dtype=np.uint8)
        rendered = visibility.renderizar_preview_com_guias_inicio_f3(
            frame,
            {
                "resolution": (80, 80),
                "masks": (
                    {
                        "id": "MASK_002",
                        "type": "circle",
                        "cx": 40,
                        "cy": 40,
                        "radius": 12,
                    },
                ),
                "classifications": {},
                "expected_states": {"MASK_002": "off"},
                "has_any_on": False,
            },
        )

        self.assertGreater(int(rendered.sum()), 0)
        self.assertEqual(0, int(rendered[40, 40].sum()))

    def test_numero_visual_remove_prefixo_e_zeros(self):
        self.assertEqual("1", visibility.numero_visual_mascara_display_f3({"id": "MASK_001"}))
        self.assertEqual("26", visibility.numero_visual_mascara_display_f3({"id": "MASK_026"}))
        self.assertEqual("104", visibility.numero_visual_mascara_display_f3({"id": "SEGMENT_104"}))

    def test_id_sem_numero_continua_identificavel(self):
        self.assertEqual(
            "DISPLAY_LEFT",
            visibility.numero_visual_mascara_display_f3({"id": "DISPLAY_LEFT"}),
        )

    def test_centro_do_rotulo_usa_geometria_real_da_mascara(self):
        center = visibility.centro_visual_mascara_display_f3(
            {
                "id": "MASK_007",
                "type": "segment",
                "cx": 150,
                "cy": 90,
                "width": 60,
                "height": 14,
                "angle": 0.0,
            }
        )
        self.assertEqual((150.0, 90.0), center)

    def test_editor_desenha_numero_com_sombra_sem_badge(self):
        source = inspect.getsource(visibility.instalar_numeros_editor_mascaras_display_f3)
        self.assertIn("create_text", source)
        self.assertIn("display-mask-number", source)
        self.assertNotIn("create_rectangle", source)
        self.assertNotIn("create_oval", source)

    def test_bootstrap_reafirma_guia_apos_construcao_do_app(self):
        source = Path("main_rpi.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count("instalar_guias_mascaras_inicio_display_f3()"),
            2,
        )
        self.assertIn("instalar_numeros_editor_mascaras_display_f3()", source)

    def test_modulo_permanece_isolado_de_f2(self):
        source = inspect.getsource(visibility)
        self.assertNotIn("src.platform.f2_", source)
        self.assertNotIn("F2Automatic", source)


if __name__ == "__main__":
    unittest.main()
