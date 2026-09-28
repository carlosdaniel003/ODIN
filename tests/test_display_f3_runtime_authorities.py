from __future__ import annotations

from types import SimpleNamespace
import inspect
import unittest
from unittest.mock import Mock, patch

import src.platform.display_f3_runtime_authorities as authorities
from src.platform.display_check_sequence_runtime import DisplayCheckSequenceRuntime
from src.platform.display_f3_object_tracking import (
    F3DisplayObjectTracker,
    get_tracking_runtime,
)


class _Repository:
    config_file = "odin_display_projects.json"


class _App:
    def __init__(self):
        self.display_project_repository = _Repository()
        self.display_check_runtime = DisplayCheckSequenceRuntime()
        self._display_f3_waiting_empty_rearm = False
        self._display_f3_waiting_new_board_after_empty = False
        self._display_f3_physical_pending_key = ""
        self._display_f3_physical_pending_frames = 0
        self._display_f3_physical_stable_key = ""
        self._display_f3_physical_stable_state = None
        self._display_f3_power_authority_status = None

    @staticmethod
    def _display_auto_frame_token(frame):
        return ("frame", id(frame))


class _Frame:
    size = 1


class DisplayF3RuntimeAuthoritiesTests(unittest.TestCase):
    def test_tracking_owner_reuses_exact_same_runtime(self):
        app = _App()
        runtime = F3DisplayObjectTracker(app.display_project_repository)
        app._display_f3_tracking_authority = SimpleNamespace(runtime=runtime)
        self.assertIs(runtime, get_tracking_runtime(app))

    def test_presence_owner_holds_only_short_ambiguity_and_resets_on_empty(self):
        owner = authorities.F3PresenceAuthority()
        present = {
            "available": True,
            "board_present": True,
            "presence_confirmed": True,
            "empty_confirmed": False,
        }
        ambiguous = {
            "available": True,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
        }
        empty = {
            "available": True,
            "board_present": False,
            "presence_confirmed": True,
            "empty_confirmed": True,
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            side_effect=[present, ambiguous, empty],
        ):
            self.assertTrue(owner.evaluate({})["board_present"])
            held = owner.evaluate({})
            self.assertTrue(held["board_present"])
            self.assertTrue(held["held_from_previous_frame"])
            self.assertTrue(owner.evaluate({})["empty_confirmed"])
        self.assertIsNone(owner._latch)

    def test_presence_owner_accepts_only_current_tracking_lock(self):
        owner = authorities.F3PresenceAuthority()
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "reason": "scores_de_presenca_indisponiveis",
        }
        current_lock = {
            "locked": True,
            "evidence_current": True,
            "reference": "check:CHECK_003",
            "reason": "locked",
        }
        held_lock = {
            "locked": True,
            "evidence_current": False,
            "reference": "check:CHECK_003",
            "reason": "lock_held",
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=ambiguous,
        ):
            present = owner.evaluate({}, current_lock)
            stale = owner.evaluate({}, held_lock)

        self.assertTrue(present["board_present"])
        self.assertTrue(present["presence_confirmed"])
        self.assertTrue(present["tracking_presence_confirmed"])
        self.assertEqual(
            authorities.F3_TRACKING_PRESENCE_SOURCE,
            present["source"],
        )
        self.assertEqual(
            "tracking_lock_atual_confirma_placa",
            present["reason"],
        )
        self.assertFalse(stale["board_present"])
        self.assertFalse(stale["presence_confirmed"])
        self.assertIsNone(owner._latch)

    def test_empty_presence_has_priority_over_current_tracking_lock(self):
        owner = authorities.F3PresenceAuthority()
        empty = {
            "available": True,
            "board_present": False,
            "presence_confirmed": True,
            "empty_confirmed": True,
            "reason": "suporte_vazio_confirmado",
        }
        current_lock = {
            "locked": True,
            "evidence_current": True,
            "reference": "check:CHECK_001",
            "reason": "locked",
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=empty,
        ):
            result = owner.evaluate({}, current_lock)

        self.assertTrue(result["empty_confirmed"])
        self.assertFalse(result["board_present"])
        self.assertNotIn("tracking_presence_confirmed", result)
        self.assertIsNone(owner._latch)

    def test_power_owner_never_lets_energy_bypass_missing_presence(self):
        app = _App()
        owner = authorities.F3PowerAuthority(app)
        result = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": False,
                "presence_confirmed": False,
                "empty_confirmed": False,
            },
            {
                "powered_confirmed": True,
                "off_confirmed": False,
                "energy_state": "powered",
            },
            project_name="P",
            context={"check_id": "C1", "check_name": "H1"},
        )
        self.assertFalse(result["allow_auto"])
        self.assertFalse(
            result[authorities.contract_module.F3_DECISION_ALLOWED_KEY]
        )
        self.assertEqual("presence:unknown", result["physical_state_key"])

    def test_state_machine_authority_delegates_to_single_runtime(self):
        runtime = DisplayCheckSequenceRuntime()
        runtime.configurar_checks(
            [
                {"id": "CHECK_001", "name": "H1"},
                {"id": "CHECK_002", "name": "BLUE"},
            ]
        )
        owner = authorities.F3StateMachineAuthority(runtime)
        event = owner.register(True)
        self.assertEqual("check_advanced", event["event"])
        self.assertIs(runtime, owner.runtime)
        self.assertEqual("BLUE", owner.snapshot()["current_check"]["name"])

    def test_operational_builder_is_cached_once_per_frame_and_context(self):
        app = _App()
        matcher = SimpleNamespace(
            check_store=SimpleNamespace(get=Mock(return_value={})),
        )
        tracking_owner = SimpleNamespace(
            stats=lambda: {"owner": "tracking"},
            presence_evidence=Mock(
                return_value={
                    "locked": False,
                    "evidence_current": False,
                    "reference": "",
                    "reason": "object_not_locked",
                }
            ),
        )
        analyzer_owner = SimpleNamespace(
            analyzer=object(),
            rebuild=Mock(return_value=object()),
        )
        with (
            patch.object(
                authorities,
                "F3TrackingAuthority",
                return_value=tracking_owner,
            ),
            patch.object(
                authorities,
                "F3CheckAnalyzerAuthority",
                return_value=analyzer_owner,
            ),
            patch.object(
                authorities.operational_module,
                "DisplayVisualReferenceMatcher",
                return_value=matcher,
            ),
        ):
            owner = authorities.F3RuntimeAuthorities(app)

        owner.presence = SimpleNamespace(
            evaluate=Mock(
                return_value={
                    "available": True,
                    "board_present": True,
                    "presence_confirmed": True,
                    "empty_confirmed": False,
                }
            ),
            reset=Mock(),
        )
        owner.power = SimpleNamespace(
            evaluate=Mock(
                return_value={
                    "powered_confirmed": True,
                    "off_confirmed": False,
                    "energy_state": "powered",
                }
            ),
            apply=Mock(
                side_effect=lambda state, presence, energy, **kwargs: {
                    **state,
                    "kind": "powered",
                    "allow_auto": True,
                    "power_evidence": energy,
                }
            ),
            reset=Mock(),
        )

        raw = {
            "kind": "unknown",
            "allow_auto": False,
            "reference_scores": {"empty": 0.2, "off": 0.8},
        }
        frame = _Frame()
        context = {"check_id": "CHECK_001", "check_name": "H1"}
        with (
            patch.object(
                authorities.transition_module,
                "classificar_estado_fisico_referencias_f3",
                return_value=raw,
            ) as classify,
            patch.object(
                authorities.physical_policy_module,
                "corrigir_falso_check_ligado_pelas_mascaras_f3",
                side_effect=lambda **kwargs: kwargs["state"],
            ),
            patch.object(
                authorities.physical_policy_module,
                "aplicar_contexto_ao_estado_fisico_f3",
                side_effect=lambda state, **kwargs: state,
            ),
            patch.object(
                authorities.live_runtime_module,
                "aplicar_gate_rearme_ciclo_f3",
                side_effect=lambda app, state: state,
            ),
        ):
            first = owner.build_operational_state(frame, "P", context)
            second = owner.build_operational_state(frame, "P", context)

        self.assertEqual("powered", first["kind"])
        self.assertEqual(first, second)
        self.assertEqual(1, classify.call_count)
        self.assertEqual(1, owner.power.evaluate.call_count)
        self.assertEqual(1, owner.build_count)
        self.assertEqual(1, owner.cache_hits)
        self.assertEqual(
            authorities.F3_RUNTIME_AUTHORITIES_SOURCE,
            first["runtime_authority_owner"],
        )

    def test_same_frame_rebuilds_when_current_tracking_lock_confirms_presence(self):
        app = _App()
        matcher = SimpleNamespace(
            check_store=SimpleNamespace(get=Mock(return_value={})),
        )
        tracking_state = {
            "locked": False,
            "evidence_current": False,
            "reference": "",
            "reason": "object_not_locked",
        }
        tracking_owner = SimpleNamespace(
            stats=lambda: {"owner": "tracking"},
            presence_evidence=Mock(side_effect=lambda: dict(tracking_state)),
        )
        analyzer_owner = SimpleNamespace(
            analyzer=object(),
            rebuild=Mock(return_value=object()),
        )
        with (
            patch.object(
                authorities,
                "F3TrackingAuthority",
                return_value=tracking_owner,
            ),
            patch.object(
                authorities,
                "F3CheckAnalyzerAuthority",
                return_value=analyzer_owner,
            ),
            patch.object(
                authorities.operational_module,
                "DisplayVisualReferenceMatcher",
                return_value=matcher,
            ),
        ):
            owner = authorities.F3RuntimeAuthorities(app)

        owner.power.evaluate = Mock(
            return_value={
                "powered_confirmed": True,
                "off_confirmed": False,
                "energy_state": "powered",
            }
        )
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "reason": "scores_de_presenca_indisponiveis",
        }
        raw = {
            "kind": "unknown",
            "allow_auto": False,
            "reference_scores": {},
        }
        frame = _Frame()
        context = {"check_id": "CHECK_001", "check_name": "H1"}

        with (
            patch.object(
                authorities.transition_module,
                "classificar_estado_fisico_referencias_f3",
                return_value=raw,
            ),
            patch.object(
                authorities.physical_policy_module,
                "corrigir_falso_check_ligado_pelas_mascaras_f3",
                side_effect=lambda **kwargs: kwargs["state"],
            ),
            patch.object(
                authorities.physical_policy_module,
                "aplicar_contexto_ao_estado_fisico_f3",
                side_effect=lambda state, **kwargs: state,
            ),
            patch.object(
                authorities.presence_module,
                "avaliar_presenca_melhor_ocupado_f3",
                return_value=ambiguous,
            ),
            patch.object(
                authorities.live_runtime_module,
                "aplicar_gate_rearme_ciclo_f3",
                side_effect=lambda app, state: state,
            ),
        ):
            before_lock = owner.build_operational_state(frame, "P", context)
            tracking_state.update(
                locked=True,
                evidence_current=True,
                reference="check:CHECK_003",
                reason="locked",
            )
            after_lock = owner.build_operational_state(frame, "P", context)

        self.assertEqual("unknown", before_lock["kind"])
        self.assertEqual("powered", after_lock["kind"])
        self.assertTrue(
            after_lock["board_presence_evidence"]["tracking_presence_confirmed"]
        )
        self.assertEqual(1, owner.power.evaluate.call_count)
        self.assertEqual(2, owner.build_count)

    def test_authority_module_owns_no_timer_or_thread(self):
        source = inspect.getsource(authorities)
        self.assertNotIn("threading.Thread(", source)
        self.assertNotIn("root.after(", source)

    def test_product_bootstrap_installs_authorities_before_coordinator(self):
        source = open("main_desktop.py", encoding="utf-8").read()
        authority_pos = source.index("instalar_autoridades_runtime_display_f3(app)")
        coordinator_pos = source.index("instalar_coordenador_runtime_display_f3(app)")
        transition_pos = source.index(
            "instalar_autoridade_transicao_fisica_checks_f3(app)"
        )
        self.assertLess(transition_pos, authority_pos)
        self.assertLess(authority_pos, coordinator_pos)

    def test_sequence_entrypoints_prefer_state_machine_authority(self):
        source = open(
            "src/platform/display_production_f3.py",
            encoding="utf-8",
        ).read()
        self.assertIn(
            'getattr(self, "_display_f3_state_machine_authority", None)',
            source,
        )
        self.assertIn("authority.register(aprovado)", source)
        self.assertIn("authority.discard()", source)


if __name__ == "__main__":
    unittest.main()
