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

    def test_semantic_mask_pattern_confirms_presence_when_scene_is_ambiguous(self):
        repository = SimpleNamespace(
            listar_checks=Mock(
                return_value=[
                    {
                        "id": "CHECK_001",
                        "name": "H1",
                        "mask_states": {
                            "MASK_008": "on",
                            "MASK_009": "on",
                            "MASK_011": "on",
                            "MASK_012": "on",
                            "MASK_013": "on",
                            "MASK_017": "on",
                            "MASK_020": "on",
                            "MASK_001": "off",
                            "MASK_002": "off",
                        },
                    }
                ]
            )
        )
        owner = authorities.F3PresenceAuthority(repository)
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "reason": "separacao_ocupado_vs_empty_insuficiente",
        }
        details = [
            {"mask_id": mask_id, "winner": "powered", "classified": "on"}
            for mask_id in (
                "MASK_008",
                "MASK_009",
                "MASK_011",
                "MASK_012",
                "MASK_013",
                "MASK_017",
                "MASK_020",
            )
        ] + [
            {"mask_id": "MASK_001", "winner": "off", "classified": "off"},
            {"mask_id": "MASK_002", "winner": "off", "classified": "off"},
        ]
        energy = {
            "available": True,
            "powered_confirmed": True,
            "off_confirmed": False,
            "details": details,
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=ambiguous,
        ):
            result = owner.evaluate(
                {},
                energy=energy,
                project_name="CM_500_L",
            )

        self.assertTrue(result["board_present"])
        self.assertTrue(result["presence_confirmed"])
        self.assertTrue(result["semantic_mask_presence_confirmed"])
        self.assertEqual(
            authorities.F3_MASK_PATTERN_PRESENCE_SOURCE,
            result["source"],
        )
        self.assertEqual(["CHECK_001"], result["semantic_mask_matched_check_ids"])

    def test_semantic_mask_pattern_never_overrides_confirmed_empty(self):
        repository = SimpleNamespace(
            listar_checks=Mock(
                return_value=[
                    {
                        "id": "CHECK_001",
                        "name": "H1",
                        "mask_states": {"MASK_008": "on"},
                    }
                ]
            )
        )
        owner = authorities.F3PresenceAuthority(repository)
        empty = {
            "available": True,
            "board_present": False,
            "presence_confirmed": True,
            "empty_confirmed": True,
            "reason": "suporte_vazio_confirmado",
        }
        energy = {
            "available": True,
            "powered_confirmed": True,
            "off_confirmed": False,
            "details": [
                {"mask_id": "MASK_008", "winner": "powered", "classified": "on"}
            ],
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=empty,
        ):
            result = owner.evaluate(
                {},
                energy=energy,
                project_name="CM_500_L",
            )

        self.assertTrue(result["empty_confirmed"])
        self.assertFalse(result["board_present"])
        self.assertNotIn("semantic_mask_presence_confirmed", result)

    def test_semantic_presence_accepts_powered_divergent_check_as_occupancy(self):
        repository = SimpleNamespace(
            listar_checks=Mock(
                return_value=[
                    {
                        "id": "CHECK_002",
                        "name": "BLUE",
                        "mask_states": {
                            "MASK_001": "on",
                            "MASK_024": "on",
                            "MASK_002": "off",
                        },
                    }
                ]
            )
        )
        owner = authorities.F3PresenceAuthority(repository)
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "reason": "separacao_ocupado_vs_empty_insuficiente",
        }
        # BLUE energizado, porém MASK_024 ficou APAGADO. Não existe CHECK
        # completo, mas isso não pode transformar uma placa NG em placa ausente.
        energy = {
            "available": True,
            "powered_confirmed": True,
            "off_confirmed": False,
            "powered_votes": 17,
            "off_votes": 1,
            "tie_votes": 0,
            "required_powered_votes": 4,
            "details": [
                {"mask_id": "MASK_001", "winner": "powered", "classified": "on"},
                {"mask_id": "MASK_024", "winner": "off", "classified": "off"},
                {"mask_id": "MASK_002", "winner": "off", "classified": "off"},
            ],
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=ambiguous,
        ):
            result = owner.evaluate(
                {},
                energy=energy,
                project_name="CM_500_L",
            )

        self.assertTrue(result["board_present"])
        self.assertTrue(result["presence_confirmed"])
        self.assertTrue(result["semantic_mask_presence_confirmed"])
        self.assertEqual([], result["semantic_mask_matched_check_ids"])
        self.assertEqual(
            "emissao_semantica_confirma_placa_com_check_divergente",
            result["reason"],
        )
        diagnostic = result["semantic_mask_presence_diagnostic"]
        self.assertEqual([], diagnostic["matched_check_ids"])
        self.assertEqual(17, diagnostic["powered_votes"])
        self.assertEqual(1, diagnostic["off_votes"])

    def test_semantic_presence_rejects_divergent_pattern_without_confirmed_power(self):
        repository = SimpleNamespace(
            listar_checks=Mock(
                return_value=[
                    {
                        "id": "CHECK_002",
                        "name": "BLUE",
                        "mask_states": {
                            "MASK_001": "on",
                            "MASK_024": "on",
                        },
                    }
                ]
            )
        )
        owner = authorities.F3PresenceAuthority(repository)
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
        }
        energy = {
            "available": True,
            "powered_confirmed": False,
            "off_confirmed": False,
            "powered_votes": 1,
            "off_votes": 1,
            "details": [
                {"mask_id": "MASK_001", "winner": "powered", "classified": "on"},
                {"mask_id": "MASK_024", "winner": "off", "classified": "off"},
            ],
        }

        with patch.object(
            authorities.presence_module,
            "avaliar_presenca_melhor_ocupado_f3",
            return_value=ambiguous,
        ):
            result = owner.evaluate(
                {},
                energy=energy,
                project_name="CM_500_L",
            )

        self.assertFalse(result["board_present"])
        self.assertFalse(result["presence_confirmed"])
        self.assertEqual(
            "mascaras_nao_confirmam_padrao_energizado",
            result["semantic_mask_presence_diagnostic"]["reason"],
        )

    def test_builder_breaks_presence_energy_deadlock_with_known_h1_pattern(self):
        app = _App()
        repository = SimpleNamespace(
            config_file="odin_display_projects.json",
            listar_checks=Mock(
                return_value=[
                    {
                        "id": "CHECK_001",
                        "name": "H1",
                        "mask_states": {
                            "MASK_008": "on",
                            "MASK_009": "on",
                            "MASK_001": "off",
                        },
                    }
                ]
            ),
        )
        app.display_project_repository = repository
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
            patch.object(authorities, "F3TrackingAuthority", return_value=tracking_owner),
            patch.object(authorities, "F3CheckAnalyzerAuthority", return_value=analyzer_owner),
            patch.object(
                authorities.operational_module,
                "DisplayVisualReferenceMatcher",
                return_value=matcher,
            ),
        ):
            owner = authorities.F3RuntimeAuthorities(app)

        owner.power.evaluate = Mock(
            return_value={
                "available": True,
                "powered_confirmed": True,
                "off_confirmed": False,
                "energy_state": "powered",
                "details": [
                    {"mask_id": "MASK_008", "winner": "powered", "classified": "on"},
                    {"mask_id": "MASK_009", "winner": "powered", "classified": "on"},
                    {"mask_id": "MASK_001", "winner": "off", "classified": "off"},
                ],
            }
        )
        ambiguous = {
            "available": False,
            "board_present": False,
            "presence_confirmed": False,
            "empty_confirmed": False,
            "reason": "separacao_ocupado_vs_empty_insuficiente",
        }
        raw = {
            "kind": "unknown",
            "allow_auto": False,
            "reference_scores": {
                "off": 0.3689,
                "check:CHECK_001": 0.3033,
                "empty": 0.1779,
            },
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
            result = owner.build_operational_state(frame, "CM_500_L", context)

        self.assertEqual("powered", result["kind"])
        self.assertTrue(result["allow_auto"])
        self.assertTrue(
            result[authorities.contract_module.F3_DECISION_ALLOWED_KEY]
        )
        self.assertTrue(
            result["board_presence_evidence"]["semantic_mask_presence_confirmed"]
        )
        self.assertEqual(
            ["CHECK_001"],
            result["board_presence_evidence"]["semantic_mask_matched_check_ids"],
        )
        owner.power.evaluate.assert_called_once_with(frame, "CM_500_L", context)

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

    def test_energia_confirmada_sem_alinhamento_nao_libera_ok_ng(self):
        app = _App()
        owner = authorities.F3PowerAuthority(app)
        result = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
            {
                "powered_confirmed": True,
                "off_confirmed": False,
                "energy_state": "powered",
                "spatial_alignment_ready": False,
                "coarse_luminous_emission_confirmed": True,
            },
            project_name="CM_500_L",
            context={"check_id": "CHECK_001", "check_name": "H1"},
        )

        self.assertEqual("powered", result["kind"])
        self.assertTrue(result["powered_board_confirmed"])
        self.assertFalse(result["allow_auto"])
        self.assertFalse(
            result[authorities.contract_module.F3_DECISION_ALLOWED_KEY]
        )
        self.assertTrue(result["power_gate_blocked"])
        self.assertEqual(
            "energia_confirmada_aguardando_alinhamento_segmentos",
            result["power_gate_reason"],
        )
        self.assertIn("ALINHANDO H1", result["text"])

    def test_usb_power_gate_aceita_lock_luminoso_atual_do_mesmo_check(self):
        app = _App()
        owner = authorities.F3PowerAuthority(app)
        energy = {
            "powered_confirmed": True,
            "off_confirmed": False,
            "energy_state": "powered",
            "spatial_alignment_required": True,
            "spatial_alignment_ready": False,
            "spatial_alignment_source": "structural_only",
            "frame_token": ("camera", 949),
        }
        tracking = {
            "locked": True,
            "evidence_current": True,
            "reference": "luminous:CHECK_004",
            "reason": "locked_luminous_segments_refined",
            "source_type": "luminous_segment_grid",
            "frame_id": 942,
            "verified_age_ms": 320.0,
            "luminous_validated_mask_ids": [
                "MASK_008",
                "MASK_009",
                "MASK_010",
            ],
        }

        result = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
            energy,
            project_name="CM_500_L",
            context={"check_id": "CHECK_004", "check_name": "USB"},
            tracking=tracking,
        )

        self.assertTrue(result["allow_auto"])
        self.assertTrue(
            result[authorities.contract_module.F3_DECISION_ALLOWED_KEY]
        )
        self.assertFalse(result["power_gate_blocked"])
        self.assertEqual(
            "presenca_estavel_e_energia_confirmada",
            result["power_gate_reason"],
        )
        self.assertTrue(
            result["power_evidence"][
                "spatial_alignment_reconciled_from_tracking"
            ]
        )
        self.assertEqual(
            "runtime_current_luminous_tracking",
            result["power_evidence"]["spatial_alignment_source"],
        )
        self.assertEqual(
            942,
            result["power_evidence"]["spatial_alignment_tracking_frame_id"],
        )

    def test_lock_luminoso_stale_ou_de_outro_check_nao_libera_gate(self):
        app = _App()
        owner = authorities.F3PowerAuthority(app)
        energy = {
            "powered_confirmed": True,
            "off_confirmed": False,
            "energy_state": "powered",
            "spatial_alignment_required": True,
            "spatial_alignment_ready": False,
            "frame_token": ("camera", 949),
        }
        base_tracking = {
            "locked": True,
            "evidence_current": True,
            "source_type": "luminous_segment_grid",
            "frame_id": 942,
            "verified_age_ms": 320.0,
            "luminous_validated_mask_ids": ["MASK_008"],
        }

        wrong_check = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
            energy,
            project_name="CM_500_L",
            context={"check_id": "CHECK_004", "check_name": "USB"},
            tracking={
                **base_tracking,
                "reference": "luminous:CHECK_002",
            },
        )
        self.assertFalse(wrong_check["allow_auto"])

        stale = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
            energy,
            project_name="CM_500_L",
            context={"check_id": "CHECK_004", "check_name": "USB"},
            tracking={
                **base_tracking,
                "reference": "luminous:CHECK_004",
                "verified_age_ms": (
                    authorities.F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS
                    + 1.0
                ),
            },
        )
        self.assertFalse(stale["allow_auto"])

        far_frame = owner.apply(
            {"kind": "unknown"},
            {
                "board_present": True,
                "presence_confirmed": True,
                "empty_confirmed": False,
            },
            energy,
            project_name="CM_500_L",
            context={"check_id": "CHECK_004", "check_name": "USB"},
            tracking={
                **base_tracking,
                "reference": "luminous:CHECK_004",
                "frame_id": (
                    949
                    - authorities.F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP
                    - 1
                ),
            },
        )
        self.assertFalse(far_frame["allow_auto"])

    def test_cycle_reset_clears_tracking_orientation_for_next_board(self):
        owner = authorities.F3RuntimeAuthorities.__new__(
            authorities.F3RuntimeAuthorities
        )
        owner.app = _App()
        owner.tracking = Mock()
        owner.presence = Mock()
        owner.power = Mock()
        owner._stable_key = "check:powered"
        owner._stable_state = {"kind": "powered"}
        owner._pending_key = "check:powered"
        owner._pending_frames = 2
        owner._cache_key = ("frame", 1)
        owner._cache_value = {"kind": "powered"}

        with patch.object(
            authorities,
            "reset_tracking_cycle",
        ) as reset_tracking:
            owner.reset_cycle_state()

        reset_tracking.assert_called_once_with(owner.app)
        owner.presence.reset.assert_called_once_with()
        owner.power.reset.assert_called_once_with()
        self.assertEqual("", owner._stable_key)
        self.assertIsNone(owner._cache_key)

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
        self.assertIn("tracking", owner.power.apply.call_args.kwargs)
        self.assertEqual(
            tracking_owner.presence_evidence.return_value,
            owner.power.apply.call_args.kwargs["tracking"],
        )
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
        # D-042 calcula a observação semântica das máscaras antes do gate final
        # de presença. O segundo build existe porque o tracking mudou a assinatura.
        self.assertEqual(2, owner.power.evaluate.call_count)
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
