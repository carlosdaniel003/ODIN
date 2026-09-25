from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import numpy as np

from src.platform.display_f3_physical_state_fix import (
    classificar_estado_fisico_hierarquico_f3,
    overlay_contexto_independente_da_analise,
)
from src.platform.desktop_production_app import DesktopProductionApp


class _Store:
    def __init__(self, values):
        self.values = values

    def get_all(self, project_name):
        return dict(self.values.get(project_name, {}))

    def get(self, project_name, key):
        return self.values.get(project_name, {}).get(key)


class _Repository:
    def __init__(self, checks, project=None):
        self.checks = checks
        self.project = project
        self.config_file = Path("/tmp/odin-display-test.json")

    def listar_checks(self, _project_name):
        return list(self.checks)

    def obter_projeto_ativo(self):
        return "DISPLAY_TESTE"

    def carregar_projeto(self, _project_name):
        return self.project


class _Matcher:
    def __init__(self, board_refs, check_refs, checks):
        self.repository = _Repository(checks)
        self.project_store = _Store({"DISPLAY_TESTE": board_refs})
        self.check_store = _Store({"DISPLAY_TESTE": check_refs})

    @staticmethod
    def _reference_image(metadata):
        return metadata.get("image")

    @staticmethod
    def _score(_current, metadata):
        return float(metadata.get("score", 0.0))

    @staticmethod
    def _threshold(metadata):
        return float(metadata.get("threshold", 0.72))


class DisplayF3PhysicalStateFixTests(unittest.TestCase):
    @staticmethod
    def _physical_images():
        empty = np.full((80, 120, 3), 20, dtype=np.uint8)
        off = empty.copy()
        off[10:72, 10:110] = 75
        off[28:54, 38:84] = 28
        powered = off.copy()
        powered[28:54, 38:84] = 220
        return empty, off, powered

    def test_placa_desligada_vence_aux_mesmo_aux_tendo_score_de_roi_maior(self):
        empty, off, aux = self._physical_images()
        board_refs = {
            "empty_support": {
                "image": empty,
                "score": 0.90,
                "threshold": 0.72,
                "roi": {"x": 0.05, "y": 0.05, "width": 0.90, "height": 0.90},
            },
            "board_off": {
                "image": off,
                "score": 0.91,
                "threshold": 0.72,
                "roi": {"x": 0.08, "y": 0.08, "width": 0.84, "height": 0.84},
            },
        }
        check_refs = {
            "CHECK_AUX": {
                "image": aux,
                # Simula exatamente o problema: ROI pequena de AUX produz um
                # percentual maior que a referência física de placa desligada.
                "score": 0.99,
                "threshold": 0.72,
                "roi": {"x": 0.31, "y": 0.34, "width": 0.40, "height": 0.34},
            }
        }
        matcher = _Matcher(
            board_refs,
            check_refs,
            [{"id": "CHECK_AUX", "name": "AUX"}],
        )

        state = classificar_estado_fisico_hierarquico_f3(
            matcher,
            off,
            "DISPLAY_TESTE",
        )

        self.assertEqual("off", state["kind"])
        self.assertEqual("PLACA NO SUPORTE • DESLIGADA", state["text"])
        self.assertFalse(state["allow_auto"])

    def test_estado_ligado_vence_off_quando_display_realmente_acende(self):
        empty, off, h1 = self._physical_images()
        board_refs = {
            "empty_support": {"image": empty, "score": 0.82, "threshold": 0.72},
            "board_off": {
                "image": off,
                # A estrutura da placa ainda deixa OFF com score alto.
                "score": 0.95,
                "threshold": 0.72,
            },
        }
        check_refs = {
            "CHECK_H1": {
                "image": h1,
                "score": 0.90,
                "threshold": 0.72,
                "roi": {"x": 0.31, "y": 0.34, "width": 0.40, "height": 0.34},
            }
        }
        matcher = _Matcher(
            board_refs,
            check_refs,
            [{"id": "CHECK_H1", "name": "H1"}],
        )

        state = classificar_estado_fisico_hierarquico_f3(
            matcher,
            h1,
            "DISPLAY_TESTE",
        )

        self.assertEqual("check", state["kind"])
        self.assertEqual("DISPLAY EM H1", state["text"])
        self.assertEqual("CHECK_H1", state["check_id"])

    def test_overlay_mantem_rois_quando_analise_automatica_esta_vazia(self):
        project = {
            "master_resolution": [120, 80],
            "masks": [
                {
                    "id": "M1",
                    "type": "circle",
                    "cx": 50,
                    "cy": 40,
                    "radius": 8,
                }
            ],
            "checks": [
                {
                    "id": "CHECK_H1",
                    "name": "H1",
                    "mask_states": {"M1": "on"},
                }
            ],
        }
        repository = _Repository(project["checks"], project=project)

        class Runtime:
            @staticmethod
            def snapshot():
                return {"current_check": {"id": "CHECK_H1", "name": "H1"}}

        class App:
            def __init__(self):
                self.display_project_repository = repository
                self.display_check_runtime = Runtime()
                self._display_auto_last_analysis = None

            def configure(self):
                return None

        class Window:
            pass

        app = App()
        window = Window()
        window.on_configure = app.configure

        context = overlay_contexto_independente_da_analise(window, 0)

        self.assertIsInstance(context, dict)
        self.assertEqual(1, len(context["masks"]))
        self.assertEqual("M1", context["masks"][0]["id"])
        self.assertEqual({}, context["classifications"])

    def test_overlay_usa_classificacao_somente_se_for_do_check_atual(self):
        project = {
            "master_resolution": [120, 80],
            "masks": [
                {"id": "M1", "type": "circle", "cx": 50, "cy": 40, "radius": 8}
            ],
            "checks": [
                {"id": "CHECK_USB", "name": "USB", "mask_states": {"M1": "on"}}
            ],
        }
        repository = _Repository(project["checks"], project=project)

        class Runtime:
            @staticmethod
            def snapshot():
                return {"current_check": {"id": "CHECK_USB", "name": "USB"}}

        class App:
            def __init__(self):
                self.display_project_repository = repository
                self.display_check_runtime = Runtime()
                self._display_auto_last_analysis = {
                    "project_name": "DISPLAY_TESTE",
                    "check_id": "CHECK_H1",
                    "mask_results": [{"mask_id": "M1", "classified": "on"}],
                }

            def configure(self):
                return None

        class Window:
            pass

        app = App()
        window = Window()
        window.on_configure = app.configure
        context = overlay_contexto_independente_da_analise(window, 0)
        self.assertEqual(1, len(context["masks"]))
        self.assertEqual({}, context["classifications"])

    def test_perfil_instala_fix_depois_da_roi_das_referencias(self):
        source = inspect.getsource(DesktopProductionApp.__init__)
        roi_position = source.index("instalar_roi_referencias_display_f3()")
        fix_position = source.index("instalar_correcao_estado_fisico_display_f3()")
        self.assertLess(roi_position, fix_position)


if __name__ == "__main__":
    unittest.main()
