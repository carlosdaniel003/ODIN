from __future__ import annotations

"""Autoridades canônicas do runtime produtivo Display F3.

Os algoritmos ópticos históricos permanecem como primitivas. Este módulo define
quem possui estado e decisão no runtime por frame: tracking, presença, energia,
analyzer de CHECK e máquina de sequência.
"""

from copy import deepcopy
from types import MethodType
import time

import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_authority_v2 as power_v2_module
import src.platform.display_f3_presence_stability_fix as presence_module
import src.platform.display_f3_runtime_contract_fix as contract_module
import src.platform.display_f3_check_transition_guard as transition_module
from src.platform.display_f3_contour_check_identity import F3TrackedRawCheckAnalyzer
from src.platform.display_f3_object_tracking import get_tracking_runtime


F3_RUNTIME_AUTHORITIES_SOURCE = "f3_runtime_authorities"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


class F3TrackingAuthority:
    """Proprietário explícito da instância stateful do tracker F3."""

    def __init__(self, app) -> None:
        self.app = app
        self.runtime = get_tracking_runtime(app)

    def reset(self) -> None:
        if self.runtime is not None:
            self.runtime.reset()

    def stats(self) -> dict:
        result = getattr(self.runtime, "last_result", None) if self.runtime is not None else None
        return {
            "owner": "F3TrackingAuthority",
            "ready": bool(getattr(self.runtime, "ready", False)),
            "project": str(getattr(self.runtime, "project", "") or ""),
            "locked": bool(getattr(result, "locked", False)),
            "reference": str(getattr(result, "reference", "") or ""),
        }


class F3PresenceAuthority:
    """Única memória de estabilidade de presença do runtime canônico."""

    def __init__(self) -> None:
        self._latch: dict | None = None

    def reset(self) -> None:
        self._latch = None

    def evaluate(self, state: dict | None) -> dict:
        evidence = presence_module.avaliar_presenca_melhor_ocupado_f3(state)
        result = deepcopy(evidence)

        if result.get("empty_confirmed"):
            self._latch = None
            return result

        if result.get("board_present") and result.get("presence_confirmed"):
            self._latch = {"frames": 0, "evidence": deepcopy(result)}
            return result

        latch = self._latch
        if not isinstance(latch, dict):
            return result

        frames = int(latch.get("frames", 0) or 0) + 1
        if frames > int(presence_module.F3_PRESENCE_AMBIGUOUS_HOLD_FRAMES):
            self._latch = None
            return result

        latch["frames"] = frames
        self._latch = latch
        result.update(
            available=True,
            board_present=True,
            presence_confirmed=True,
            held_from_previous_frame=True,
            held_ambiguous_frames=frames,
            reason="presenca_mantida_durante_ambiguidade_curta",
        )
        return result


class F3PowerAuthority:
    """Autoridade de energia; presença é entrada, nunca inferida aqui."""

    def __init__(self, app) -> None:
        self.app = app
        self._intermittent_latch: dict | None = None

    def reset(self) -> None:
        self._intermittent_latch = None

    def evaluate(self, frame, project_name: str, context: dict | None) -> dict:
        return power_v2_module.avaliar_evidencia_energia_unificada_display_f3(
            self.app,
            frame,
            project_name,
            context,
        )

    def apply(
        self,
        state: dict,
        presence: dict,
        energy: dict,
        *,
        project_name: str,
        context: dict | None,
    ) -> dict:
        output = deepcopy(state)
        output["board_presence_evidence"] = deepcopy(presence)
        check_id = str((context or {}).get("check_id") or "")
        check_name = str(
            (context or {}).get("check_name") or check_id or "CHECK"
        ).strip().upper()

        if bool(presence.get("empty_confirmed")):
            self._intermittent_latch = None
            output.update(
                kind="empty",
                text="PLACA FORA DO SUPORTE",
                color=operational_module.F3_OPERATIONAL_STATUS_COLORS["empty"],
                allow_auto=False,
                physical_state_key="empty:runtime_authority",
                powered_board_confirmed=False,
                power_gate_blocked=True,
                power_gate_reason="suporte_vazio_confirmado",
                power_authority_source=F3_RUNTIME_AUTHORITIES_SOURCE,
            )
            decision_allowed = False
            energy_for_status = None
        elif not bool(presence.get("board_present")):
            self._intermittent_latch = None
            output.update(
                kind="unknown",
                text="IDENTIFICANDO PRESENÇA DA PLACA...",
                color=operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                allow_auto=False,
                physical_state_key="presence:unknown",
                powered_board_confirmed=False,
                power_gate_blocked=True,
                power_gate_reason="placa_nao_confirmada_no_suporte",
                power_authority_source=F3_RUNTIME_AUTHORITIES_SOURCE,
            )
            decision_allowed = False
            energy_for_status = None
        else:
            evidence = deepcopy(energy) if isinstance(energy, dict) else {}
            intermittent = bool((context or {}).get("intermittent", False))
            signature = (str(project_name or ""), check_id)
            now = time.monotonic()

            if evidence.get("powered_confirmed"):
                if intermittent:
                    self._intermittent_latch = {
                        "signature": signature,
                        "powered_at_s": now,
                        "evidence": deepcopy(evidence),
                    }
            elif intermittent:
                latch = self._intermittent_latch
                if isinstance(latch, dict) and tuple(latch.get("signature") or ()) == signature:
                    age = now - float(latch.get("powered_at_s", 0.0) or 0.0)
                    if 0.0 <= age <= float(presence_module.F3_INTERMITTENT_POWER_HOLD_S):
                        evidence.update(
                            intermittent_phase_hold=True,
                            intermittent_live_energy_state=str(
                                evidence.get("energy_state") or "unconfirmed"
                            ),
                            intermittent_hold_age_ms=int(round(age * 1000.0)),
                            energy_state=power_module.F3_POWER_STATE_POWERED,
                            powered_confirmed=True,
                            off_confirmed=False,
                        )
                    elif age > float(presence_module.F3_INTERMITTENT_POWER_HOLD_S):
                        self._intermittent_latch = None
            else:
                self._intermittent_latch = None

            if evidence.get("powered_confirmed"):
                output.update(
                    kind="powered",
                    text=(
                        f"PLACA NO SUPORTE • LIGADA • {check_name} • FASE OFF INTERMITENTE"
                        if bool(evidence.get("intermittent_phase_hold"))
                        else f"PLACA NO SUPORTE • LIGADA • ANALISANDO {check_name}"
                    ),
                    color=operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
                    allow_auto=True,
                    physical_state_key="check:powered_by_runtime_authority",
                    expected_check_id=check_id,
                    powered_board_confirmed=True,
                    power_gate_blocked=False,
                    power_gate_reason="presenca_estavel_e_energia_confirmada",
                    power_authority_source=F3_RUNTIME_AUTHORITIES_SOURCE,
                    power_evidence=deepcopy(evidence),
                )
                decision_allowed = True
            else:
                is_off = bool(evidence.get("off_confirmed"))
                output.update(
                    kind="off" if is_off else "unknown",
                    text=(
                        "PLACA NO SUPORTE • DESLIGADA • AGUARDANDO DISPLAY LIGADO"
                        if is_off
                        else "PLACA NO SUPORTE • ENERGIA DO DISPLAY NÃO CONFIRMADA"
                    ),
                    color=operational_module.F3_OPERATIONAL_STATUS_COLORS[
                        "off" if is_off else "unknown"
                    ],
                    allow_auto=False,
                    physical_state_key=(
                        "off:runtime_authority" if is_off else "power:unconfirmed"
                    ),
                    powered_board_confirmed=False,
                    power_gate_blocked=True,
                    power_gate_reason=(
                        "placa_presente_e_energia_off_confirmada"
                        if is_off
                        else "placa_presente_mas_energia_nao_confirmada"
                    ),
                    power_authority_source=F3_RUNTIME_AUTHORITIES_SOURCE,
                    power_evidence=deepcopy(evidence),
                )
                decision_allowed = False
            energy_for_status = deepcopy(evidence)

        output[contract_module.F3_DECISION_ALLOWED_KEY] = decision_allowed
        output[contract_module.F3_MASK_LIVE_KEY] = True
        self.app._display_f3_power_authority_status = {
            "source": F3_RUNTIME_AUTHORITIES_SOURCE,
            "board_present": bool(presence.get("board_present")),
            "empty_confirmed": bool(presence.get("empty_confirmed")),
            "presence": deepcopy(presence),
            "energy": energy_for_status,
            "decision_allowed": decision_allowed,
            "reason": str(output.get("power_gate_reason") or ""),
        }
        return output


class F3CheckAnalyzerAuthority:
    """Uma instância de analyzer/cache para toda a sessão F3."""

    def __init__(self, app) -> None:
        self.app = app
        self.repository = app.display_project_repository
        self.analyzer = F3TrackedRawCheckAnalyzer(self.repository, app)

    def rebuild(self):
        try:
            self.analyzer.invalidate_learning_cache()
        except Exception:
            pass
        self.analyzer = F3TrackedRawCheckAnalyzer(self.repository, self.app)
        self.app._display_f3_generic_power_analyzer = self.analyzer.semantic
        return self.analyzer


class F3StateMachineAuthority:
    """Facade única da máquina de sequência pura e isolada do F3."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def snapshot(self) -> dict:
        return self.runtime.snapshot()

    def register(self, approved: bool) -> dict:
        return self.runtime.registrar_resultado_check(bool(approved))

    def discard(self) -> dict:
        return self.runtime.descartar_placa()

    def reset_plate(self) -> None:
        self.runtime.reiniciar_placa()


class F3RuntimeAuthorities:
    """Composição canônica das autoridades do ciclo F3."""

    def __init__(self, app) -> None:
        self.app = app
        self.repository = app.display_project_repository
        self.tracking = F3TrackingAuthority(app)
        self.presence = F3PresenceAuthority()
        self.power = F3PowerAuthority(app)
        self.check_analyzer = F3CheckAnalyzerAuthority(app)
        self.state_machine = F3StateMachineAuthority(app.display_check_runtime)
        self._matcher = operational_module.DisplayVisualReferenceMatcher(
            self.repository
        )
        self._stable_key = ""
        self._stable_state: dict | None = None
        self._pending_key = ""
        self._pending_frames = 0
        self._cache_key = None
        self._cache_value: dict | None = None
        self.build_count = 0
        self.cache_hits = 0

    def reset_cycle_state(self) -> None:
        self.presence.reset()
        self.power.reset()
        self._stable_key = ""
        self._stable_state = None
        self._pending_key = ""
        self._pending_frames = 0
        self._cache_key = None
        self._cache_value = None

    def _frame_token(self, frame):
        token_fn = getattr(self.app, "_display_auto_frame_token", None)
        if callable(token_fn):
            try:
                return token_fn(frame)
            except Exception:
                pass
        return ("object", id(frame))

    def _stabilize_physical_state(self, raw_state: dict) -> dict:
        kind = str(raw_state.get("kind") or "unknown")
        if kind in {"unknown", "unavailable"}:
            self._pending_key = ""
            self._pending_frames = 0
            return deepcopy(raw_state)

        key = str(raw_state.get("physical_state_key") or kind)
        if key == self._stable_key:
            self._pending_key = ""
            self._pending_frames = 0
            self._stable_state = deepcopy(raw_state)
            return deepcopy(raw_state)

        self._pending_frames = (
            self._pending_frames + 1
            if self._pending_key == key
            else 1
        )
        self._pending_key = key

        self.app._display_f3_physical_pending_key = self._pending_key
        self.app._display_f3_physical_pending_frames = self._pending_frames

        required = int(transition_module.F3_PHYSICAL_STATE_STABLE_FRAMES)
        if self._pending_frames < required:
            return {
                "kind": "unknown",
                "text": "IDENTIFICANDO...",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unknown"],
                "allow_auto": False,
                "board_references_complete": bool(
                    raw_state.get("board_references_complete")
                ),
                "reference_scores": deepcopy(
                    raw_state.get("reference_scores") or {}
                ),
                "physical_transition_pending": True,
                "pending_physical_state_key": key,
            }

        self._stable_key = key
        self._stable_state = deepcopy(raw_state)
        self._pending_key = ""
        self._pending_frames = 0
        self.app._display_f3_physical_stable_key = self._stable_key
        self.app._display_f3_physical_stable_state = deepcopy(self._stable_state)
        self.app._display_f3_physical_pending_key = ""
        self.app._display_f3_physical_pending_frames = 0
        return deepcopy(raw_state)

    def _cache_signature(self, frame, project_name: str, context: dict | None):
        return (
            self._frame_token(frame),
            str(project_name or ""),
            str((context or {}).get("check_id") or ""),
            bool(getattr(self.app, "_display_f3_waiting_empty_rearm", False)),
            bool(
                getattr(
                    self.app,
                    "_display_f3_waiting_new_board_after_empty",
                    False,
                )
            ),
        )

    def build_operational_state(
        self,
        frame,
        project_name: str,
        context: dict | None,
    ) -> dict:
        if not _valid_frame(frame):
            return {
                "kind": "unknown",
                "text": "AGUARDANDO CÂMERA",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
                "allow_auto": False,
                contract_module.F3_DECISION_ALLOWED_KEY: False,
                contract_module.F3_MASK_LIVE_KEY: True,
                "source": F3_RUNTIME_AUTHORITIES_SOURCE,
            }

        signature = self._cache_signature(frame, project_name, context)
        if signature == self._cache_key and isinstance(self._cache_value, dict):
            self.cache_hits += 1
            return deepcopy(self._cache_value)

        raw_state = transition_module.classificar_estado_fisico_referencias_f3(
            self._matcher,
            frame,
            project_name,
        )
        raw_state = physical_policy_module.corrigir_falso_check_ligado_pelas_mascaras_f3(
            repository=self.repository,
            matcher=self._matcher,
            frame=frame,
            project_name=project_name,
            state=raw_state,
        )
        state = self._stabilize_physical_state(raw_state)
        current_check_id = str((context or {}).get("check_id") or "")
        state = physical_policy_module.aplicar_contexto_ao_estado_fisico_f3(
            state,
            current_check_id=current_check_id,
        )
        try:
            current_metadata = (
                self._matcher.check_store.get(project_name, current_check_id)
                if current_check_id
                else None
            )
        except Exception:
            current_metadata = None
        state["current_check_reference_configured"] = isinstance(
            current_metadata,
            dict,
        )

        presence = self.presence.evaluate(state)
        energy = (
            self.power.evaluate(frame, project_name, context)
            if bool(presence.get("board_present"))
            else {}
        )
        state = self.power.apply(
            state,
            presence,
            energy,
            project_name=project_name,
            context=context,
        )
        state = live_runtime_module.aplicar_gate_rearme_ciclo_f3(
            self.app,
            state,
        )
        state.setdefault("source", F3_RUNTIME_AUTHORITIES_SOURCE)
        state["runtime_authority_owner"] = F3_RUNTIME_AUTHORITIES_SOURCE
        cycle_rearmed = bool(state.get("cycle_rearmed"))

        self._cache_key = signature
        self._cache_value = deepcopy(state)
        self.build_count += 1
        self.app._display_f3_operational_state = deepcopy(state)
        self.app._display_f3_runtime_authority_stats = self.stats()
        result = deepcopy(state)
        if cycle_rearmed:
            # O frame EMPTY atual continua publicado, mas nenhuma memória física
            # da placa anterior atravessa para o próximo frame/placa.
            self.reset_cycle_state()
        return result

    def stats(self) -> dict:
        return {
            "source": F3_RUNTIME_AUTHORITIES_SOURCE,
            "build_count": int(self.build_count),
            "cache_hits": int(self.cache_hits),
            "tracking": self.tracking.stats(),
            "presence_owner": "F3PresenceAuthority",
            "power_owner": "F3PowerAuthority",
            "check_analyzer_owner": "F3CheckAnalyzerAuthority",
            "state_machine_owner": "F3StateMachineAuthority",
        }


def instalar_autoridades_runtime_display_f3(app) -> F3RuntimeAuthorities | None:
    """Instala autoridades finais depois das camadas históricas de compatibilidade."""
    if app is None:
        return None
    existing = getattr(app, "_display_f3_runtime_authorities", None)
    if isinstance(existing, F3RuntimeAuthorities):
        return existing

    authorities = F3RuntimeAuthorities(app)
    app._display_f3_runtime_authorities = authorities
    app._display_f3_tracking_authority = authorities.tracking
    app._display_f3_presence_authority = authorities.presence
    app._display_f3_power_authority = authorities.power
    app._display_f3_check_analyzer_authority = authorities.check_analyzer
    app._display_f3_state_machine_authority = authorities.state_machine

    authorities.check_analyzer.rebuild()
    app._display_auto_analyzer = authorities.check_analyzer.analyzer

    previous_rebuild = app._rebuild_display_auto_analyzer

    def rebuild(self):
        try:
            previous_rebuild()
        except Exception:
            pass
        owner = getattr(self, "_display_f3_runtime_authorities", None)
        if isinstance(owner, F3RuntimeAuthorities):
            self._display_auto_analyzer = owner.check_analyzer.rebuild()
        return self._display_auto_analyzer

    app._rebuild_display_auto_analyzer = MethodType(rebuild, app)

    def canonical_builder(self, frame, project_name: str, context: dict | None):
        owner = getattr(self, "_display_f3_runtime_authorities", None)
        if not isinstance(owner, F3RuntimeAuthorities):
            return {
                "kind": "unavailable",
                "text": "AUTORIDADE F3 INDISPONÍVEL",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
                "allow_auto": False,
            }
        return owner.build_operational_state(
            frame,
            str(project_name or ""),
            context,
        )

    physical_policy_module._build_physical_operational_state = canonical_builder
    operational_module._build_operational_state = canonical_builder
    physical_policy_module._display_f3_runtime_authorities_owner = True
    operational_module._display_f3_runtime_authorities_owner = True
    app._display_f3_runtime_authorities_installed = True
    return authorities
