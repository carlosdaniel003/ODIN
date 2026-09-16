from __future__ import annotations

import inspect
import unittest

import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_board_presence_mask_preview_native import (
    _carregar_rois_do_projeto,
    desenhar_rois_na_referencia_f2,
    instalar_renderer_nativo_mascaras_previews_presenca_f2,
)
from src.platform.f2_board_presence_references import (
    F2BoardPresenceReferenceController,
)


class _RepositoryFake:
    def __init__(self, leds):
        self.leds = leds
        self.calls = []

    def carregar_leds_fixos(self, projeto=None):
        self.calls.append(projeto)
        return list(self.leds)


class _AppFake:
    def __init__(self, repository):
        self.config_repository = repository


class _ControllerFake:
    def __init__(self, repository):
        self.app = _AppFake(repository)


class F2BoardPresenceMaskPreviewNativeTests(unittest.TestCase):
    def test_uses_same_project_repository_source_as_led_manager(self):
        led = LedSelection(id="LED_001", centro_x=320, centro_y=240, raio=18)
        repository = _RepositoryFake([led])
        controller = _ControllerFake(repository)

        loaded = _carregar_rois_do_projeto(controller, "TESTE_PCI_DISPLAY_0")

        self.assertEqual([led], loaded)
        self.assertEqual(["TESTE_PCI_DISPLAY_0"], repository.calls)

    def test_overlay_draws_yellow_roi_without_mutating_reference(self):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        original = image.copy()
        led = LedSelection(id="LED_001", centro_x=320, centro_y=240, raio=24)

        annotated, count = desenhar_rois_na_referencia_f2(image, [led])

        self.assertEqual(1, count)
        self.assertTrue(np.array_equal(image, original))
        self.assertFalse(np.array_equal(annotated, original))
        self.assertGreater(int(np.max(annotated[210:270, 290:350])), 0)

    def test_overlay_adapts_old_base_resolution_to_640x480_reference(self):
        led = LedSelection(
            id="LED_OLD",
            centro_x=581,
            centro_y=390,
            raio=20,
            centro_x_normalizado=0.5,
            centro_y_normalizado=0.5,
            raio_normalizado=20 / 1163,
            largura_base=1163,
            altura_base=780,
        )
        image = np.zeros((480, 640, 3), dtype=np.uint8)

        annotated, count = desenhar_rois_na_referencia_f2(image, [led])

        self.assertEqual(1, count)
        self.assertGreater(int(np.max(annotated[220:260, 300:340])), 0)

    def test_installer_replaces_controller_renderer_directly(self):
        instalar_renderer_nativo_mascaras_previews_presenca_f2()
        current = F2BoardPresenceReferenceController.render_settings
        self.assertTrue(getattr(current, "_odin_f2_native_mask_preview", False))

    def test_native_renderer_contains_no_delayed_widget_search(self):
        import src.platform.f2_board_presence_mask_preview_native as module

        source = inspect.getsource(module)
        self.assertNotIn("window.after", source)
        self.assertNotIn("winfo_children", source)
        self.assertIn("carregar_leds_fixos", source)
        self.assertIn("F2_BOARD_REF_BOARD_ON", source)
        self.assertIn("F2_BOARD_REF_BOARD_OFF", source)
        self.assertIn("F2_BOARD_REF_EMPTY", source)


if __name__ == "__main__":
    unittest.main()
