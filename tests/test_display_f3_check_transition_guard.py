from __future__ import annotations

import inspect
import unittest

import numpy as np

import src.platform.display_f3_check_transition_guard as transition_module
import src.platform.display_f3_operational_status as operational_module
from src.platform.display_f3_check_transition_guard import (
    F3_CHECK_TRANSITION_STABLE_FRAMES,
    F3_PHYSICAL_STATE_STABLE_FRAMES,
    _estado_fisico_estavel,
    avaliar_preferencia_transicao_referencias_f3,
    classificar_estado_fisico_referencias_f3,
    decidir_transicao_estavel_f3,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
)
from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp


class _FakeProjectStore:
    def __init__(self, references):
        self.references = dict(references)

    def get_all(self, _project_name):
        return dict(self.references)


class _FakeCheckStore:
    def __init__(self, references):
        self.references = dict(references)

    def get(self, _project_name, check_id):
        return self.references.get(check_id)


class _FakeRepository:
    def __init__(self, checks):
        self.checks = list(checks)

    def listar_checks(self, _project_name):
        return list(self.checks)


class _FakeMatcher:
    def __init__(self, *, project_references=None, check_references=None, checks=None):
        self.project_store = _FakeProjectStore(project_references or {})
        self.check_store = _FakeCheckStore(check_references or {})
        self.repository = _FakeRepository(checks or [])

    @staticmethod
    def _reference_image(metadata):
        return metadata.get("image")

    @staticmethod
    def _score(_current, metadata):
        return float(metadata.get("score", 0.0))

    @staticmethod
    def _threshold(metadata):
        return float(metadata.get("threshold", 0.72))


class _StabilityHarness:
    pass


class DisplayF3CheckTransitionGuardTests(unittest.TestCase):
    @staticmethod
    def _references():
        blue = np.full((80, 120, 3), 35, dtype=np.uint8)
        usb = blue.copy()
        blue[20:60, 18:48] = 220
        usb[20:60, 72:102] = 220
        return blue, usb

    @staticmethod
    def _physical_references():
        empty = np.full((80, 120, 3), 15, dtype=np.uint8)
        off = np.full((80, 120, 3), 55, dtype=np.uint8)
        h1 = off.copy()
        blue = off.copy()
        usb = off.copy()
        h1[24:56, 42:78] = 210
        blue[20:60, 18:48] = 220
        usb[20:60, 72:102] = 220
        return empty, off, h1, blue, usb

    @staticmethod
    def _metadata(image, score):
        return {"image": image, "score": score, "threshold": 0.72}

    def _physical_matcher(self):
        empty, off, h1, blue, usb = self._physical_references()
        matcher = _FakeMatcher(
            project_references={
                DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT: self._metadata(empty, 0.90),
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF: self._metadata(off, 0.90),
            },
            check_references={
                "H1": self._metadata(h1, 0.96),
                "BLUE": self._metadata(blue, 0.96),
                "USB": self._metadata(usb, 0.96),
            },
            checks=[
                {"id": "H1", "name": "H1"},
                {"id": "BLUE", "name": "BLUE"},
                {"id": "USB", "name": "USB"},
            ],
        )
        return matcher, (empty, off, h1, blue, usb)

    def test_placa_desligada_vence_h1_mesmo_h1_tendo_score_global_maior(self):
        matcher, (_, off, _, _, _) = self._physical_matcher()
        state = classificar_estado_fisico_referencias_f3(matcher, off, "PROJETO")
        self.assertEqual("off", state["kind"])
        self.assertEqual("PLACA NO SUPORTE • DESLIGADA", state["text"])
        self.assertFalse(state["allow_auto"])

    def test_h1_e_identificado_pelo_fisico_sem_depender_do_check_esperado(self):
        matcher, (_, _, h1, _, _) = self._physical_matcher()
        state = classificar_estado_fisico_referencias_f3(matcher, h1, "PROJETO")
        self.assertEqual("check", state["kind"])
        self.assertEqual("H1", state["check_id"])
        self.assertEqual("DISPLAY EM H1", state["text"])

    def test_blue_permanece_estado_fisico_mesmo_se_fluxo_ja_estiver_em_usb(self):
        matcher, (_, _, _, blue, _) = self._physical_matcher()
        state = classificar_estado_fisico_referencias_f3(matcher, blue, "PROJETO")
        self.assertEqual("check", state["kind"])
        self.assertEqual("BLUE", state["check_id"])
        self.assertEqual("DISPLAY EM BLUE", state["text"])

    def test_usb_so_aparece_quando_imagem_fisica_e_usb(self):
        matcher, (_, _, _, _, usb) = self._physical_matcher()
        state = classificar_estado_fisico_referencias_f3(matcher, usb, "PROJETO")
        self.assertEqual("check", state["kind"])
        self.assertEqual("USB", state["check_id"])
        self.assertEqual("DISPLAY EM USB", state["text"])

    def test_status_fisico_exige_estabilidade_e_nao_exibe_estado_antigo_na_transicao(self):
        harness = _StabilityHarness()
        raw = {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "color": "#FBBF24",
            "allow_auto": False,
            "physical_state_key": "off",
            "board_references_complete": True,
        }
        for index in range(1, F3_PHYSICAL_STATE_STABLE_FRAMES + 1):
            state = _estado_fisico_estavel(harness, raw)
            if index < F3_PHYSICAL_STATE_STABLE_FRAMES:
                self.assertEqual("unknown", state["kind"])
                self.assertEqual("IDENTIFICANDO...", state["text"])
            else:
                self.assertEqual("off", state["kind"])

    def test_blue_permanece_quando_frame_ainda_e_blue_mesmo_usb_passando_threshold(self):
        blue, usb = self._references()
        matcher = _FakeMatcher()
        evidence = avaliar_preferencia_transicao_referencias_f3(
            matcher,
            blue,
            {"image": blue, "score": 0.96, "threshold": 0.72},
            {"image": usb, "score": 0.93, "threshold": 0.72},
        )
        self.assertTrue(evidence["available"])
        self.assertEqual("difference_mask", evidence["mode"])
        self.assertFalse(evidence["current_preferred"])
        self.assertLess(evidence["last_error"], evidence["current_error"])

    def test_usb_so_e_preferido_quando_frame_realmente_muda_para_usb(self):
        blue, usb = self._references()
        matcher = _FakeMatcher()
        evidence = avaliar_preferencia_transicao_referencias_f3(
            matcher,
            usb,
            {"image": blue, "score": 0.90, "threshold": 0.72},
            {"image": usb, "score": 0.97, "threshold": 0.72},
        )
        self.assertTrue(evidence["current_preferred"])
        self.assertLess(evidence["current_error"], evidence["last_error"])

    def test_transicao_relativa_funciona_mesmo_com_scores_absolutos_abaixo_do_threshold(self):
        blue, usb = self._references()
        matcher = _FakeMatcher()

        evidence = avaliar_preferencia_transicao_referencias_f3(
            matcher,
            usb,
            {"image": blue, "score": 0.65, "threshold": 0.72},
            {"image": usb, "score": 0.61, "threshold": 0.72},
        )

        self.assertTrue(evidence["available"])
        self.assertFalse(evidence["current_matched"])
        self.assertTrue(evidence["relative_preferred"])
        self.assertTrue(evidence["current_preferred"])
        self.assertLess(evidence["current_error"], evidence["last_error"])

    def test_frame_ainda_no_check_anterior_bloqueia_destino_mesmo_com_score_proximo(self):
        blue, usb = self._references()
        matcher = _FakeMatcher()

        evidence = avaliar_preferencia_transicao_referencias_f3(
            matcher,
            blue,
            {"image": blue, "score": 0.65, "threshold": 0.72},
            {"image": usb, "score": 0.64, "threshold": 0.72},
        )

        self.assertTrue(evidence["available"])
        self.assertFalse(evidence["current_preferred"])
        self.assertGreater(evidence["current_error"], evidence["last_error"])

    def test_transicao_exige_frames_consecutivos_antes_de_promover(self):
        pending_id = ""
        pending_frames = 0
        for index in range(1, F3_CHECK_TRANSITION_STABLE_FRAMES + 1):
            transition = decidir_transicao_estavel_f3(
                current_check_id="CHECK_USB",
                preferred=True,
                pending_check_id=pending_id,
                pending_frames=pending_frames,
            )
            pending_id = transition["pending_check_id"]
            pending_frames = transition["pending_frames"]
            self.assertEqual(index, pending_frames)
            if index < F3_CHECK_TRANSITION_STABLE_FRAMES:
                self.assertFalse(transition["promote"])
            else:
                self.assertTrue(transition["promote"])

    def test_um_frame_incorreto_zera_confirmacao_da_transicao(self):
        transition = decidir_transicao_estavel_f3(
            current_check_id="CHECK_USB",
            preferred=True,
            pending_check_id="CHECK_USB",
            pending_frames=2,
        )
        self.assertEqual(3, transition["pending_frames"])
        reset = decidir_transicao_estavel_f3(
            current_check_id="CHECK_USB",
            preferred=False,
            pending_check_id=transition["pending_check_id"],
            pending_frames=transition["pending_frames"],
        )
        self.assertFalse(reset["promote"])
        self.assertEqual("", reset["pending_check_id"])
        self.assertEqual(0, reset["pending_frames"])

    def test_guard_nao_usa_check_atual_para_escolher_estado_fisico(self):
        source = inspect.getsource(transition_module._install_transition_guard)
        classifier_call = source.index("classificar_estado_fisico_referencias_f3")
        expected_check = source.index("current_check_id =")
        self.assertLess(classifier_call, expected_check)
        self.assertIn("physical_check_id == current_check_id", source)

    def test_estado_fisico_nao_decide_o_check_operacional(self):
        source = inspect.getsource(operational_module._install_operational_auto_gate)
        self.assertIn("return original_process(self)", source)
        self.assertNotIn('kind == "check" and not allow_auto', source)
        self.assertNotIn('kind in {"empty", "off"}', source)
        self.assertIn("máscaras", source)

    def test_perfil_final_instala_guard_depois_do_status_operacional(self):
        source = inspect.getsource(RaspberryPi3ProductionApp.__init__)
        operational = source.index("instalar_status_operacional_display_f3()")
        transition = source.index("instalar_guard_transicao_check_display_f3()")
        self.assertLess(operational, transition)


if __name__ == "__main__":
    unittest.main()
