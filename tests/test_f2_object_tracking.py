from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from src.models.led_selection import LedSelection
from src.platform.f2_object_tracking import (
    F2BoardObjectTracker,
    F2ObjectTrackingMixin,
    F2_OBJECT_TRACKING_OPTION_TEXT,
    construir_mascara_rastreamento_f2,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)


class _RepoFake:
    def __init__(self, config_file: Path, config: dict, leds=None):
        self.config_file = config_file
        self._config = config
        self._leds = list(leds or [])

    def carregar_configuracao_existente_sem_alerta(self):
        return self._config

    def carregar_leds_fixos(self, projeto=None):
        return list(self._leds)


class _ControllerFake:
    def __init__(self, repo, entries, resolution=(320, 240)):
        self.app = SimpleNamespace(config_repository=repo)
        self._entries_value = entries
        self._resolution = resolution

    def project_name(self):
        return "TESTE"

    def master_resolution(self, projeto=None):
        return self._resolution

    def _entries(self, projeto):
        return self._entries_value


class F2ObjectTrackingTests(unittest.TestCase):
    def test_opcao_deixou_de_ser_placeholder_desabilitado(self):
        self.assertEqual(
            "Ativar rastreamento automático de objetos",
            F2_OBJECT_TRACKING_OPTION_TEXT,
        )
        source = inspect.getsource(F2ObjectTrackingMixin._atualizar_preview_operacao)
        self.assertIn("not self._f2_tracking_enabled()", source)
        self.assertIn("super()._atualizar_preview_operacao()", source)
        self.assertNotIn("display_f3", inspect.getsource(F2ObjectTrackingMixin))

    def test_mascara_da_placa_exclui_regiao_do_led(self):
        shape = [
            LedSelection(
                id="BOARD",
                centro_x=160,
                centro_y=120,
                raio=2,
                tipo_roi="segmento",
                pontos_segmento_livre=[
                    (-100, -70),
                    (100, -70),
                    (100, 70),
                    (-100, 70),
                ],
            )
        ]
        leds = [LedSelection(id="LED_001", centro_x=160, centro_y=120, raio=12)]
        mask = construir_mascara_rastreamento_f2(shape, leds, 320, 240)
        self.assertIsNotNone(mask)
        self.assertEqual(0, int(mask[120, 160]))
        self.assertGreater(int(mask[90, 100]), 0)

    def test_tracker_alinha_translacao_sem_mudar_motor_f2(self):
        rng = np.random.default_rng(42)
        reference = np.zeros((240, 320, 3), dtype=np.uint8)
        reference[:] = (28, 34, 40)
        cv2.rectangle(reference, (55, 45), (265, 195), (70, 92, 112), -1)
        for _ in range(180):
            x = int(rng.integers(65, 255))
            y = int(rng.integers(55, 185))
            radius = int(rng.integers(1, 4))
            color = tuple(int(v) for v in rng.integers(80, 245, size=3))
            cv2.circle(reference, (x, y), radius, color, -1)
        cv2.line(reference, (70, 70), (245, 175), (240, 240, 240), 2)
        cv2.putText(
            reference,
            "PCB",
            (105, 135),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (250, 250, 250),
            2,
            cv2.LINE_AA,
        )

        transform = np.float32([[1.0, 0.0, 18.0], [0.0, 1.0, -11.0]])
        current = cv2.warpAffine(
            reference,
            transform,
            (320, 240),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(28, 34, 40),
        )

        board = LedSelection(
            id="BOARD",
            centro_x=160,
            centro_y=120,
            raio=2,
            tipo_roi="segmento",
            pontos_segmento_livre=[
                (-105, -75),
                (105, -75),
                (105, 75),
                (-105, 75),
            ],
        ).com_normalizacao(320, 240)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            on_path = tmp_path / "on.png"
            off_path = tmp_path / "off.png"
            cv2.imwrite(str(on_path), reference)
            cv2.imwrite(str(off_path), reference)
            config = {
                "led_projects": {
                    "TESTE": {
                        "name": "TESTE",
                        "f2_board_shape": {
                            "rois": [board.to_dict()],
                            "base_resolution": {"width": 320, "height": 240},
                            "updated_at": "2026-09-16T00:00:00Z",
                        },
                    }
                }
            }
            repo = _RepoFake(tmp_path / "config.json", config)
            entries = {
                F2_BOARD_REF_BOARD_ON: {
                    "image_path": str(on_path),
                    "updated_at": "1",
                },
                F2_BOARD_REF_BOARD_OFF: {
                    "image_path": str(off_path),
                    "updated_at": "1",
                },
            }
            controller = _ControllerFake(repo, entries)
            tracker = F2BoardObjectTracker()
            self.assertTrue(tracker.configure(controller), tracker.reason)
            result = tracker.align(current, frame_id=10)
            self.assertTrue(result.locked, result.reason)
            raw_error = float(
                np.mean(cv2.absdiff(current, reference))
            )
            aligned_error = float(
                np.mean(cv2.absdiff(result.frame, reference))
            )
            self.assertLess(aligned_error, raw_error * 0.70)
            self.assertAlmostEqual(-18.0, result.dx, delta=5.0)
            self.assertAlmostEqual(11.0, result.dy, delta=5.0)

    def test_suporte_vazio_nao_deve_ser_forcado_para_placa(self):
        tracker = F2BoardObjectTracker()
        tracker.ready = True
        tracker.width = 320
        tracker.height = 240
        tracker.reason = "ready"
        # Sem referências/descritivos válidos, o caminho deve falhar aberto e
        # devolver o frame original; assim o classificador de presença ainda pode
        # reconhecer SUPORTE VAZIO normalmente.
        blank = np.zeros((240, 320, 3), dtype=np.uint8)
        result = tracker.align(blank, frame_id=1)
        self.assertFalse(result.locked)
        self.assertIs(result.frame, blank)


if __name__ == "__main__":
    unittest.main()
