from __future__ import annotations

"""Autoridades canônicas do runtime produtivo Display F3.

Os algoritmos ópticos históricos permanecem como primitivas. Este módulo define
quem possui estado e decisão no runtime por frame: tracking, presença, energia,
analyzer de CHECK e máquina de sequência.
"""

from copy import deepcopy
from types import MethodType
import time

import src.platform.display_f3_cycle_rearm_release_fix as cycle_rearm_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_physical_learning_policy as physical_policy_module
import src.platform.display_f3_power_authority as power_module
import src.platform.display_f3_power_authority_v2 as power_v2_module
import src.platform.display_f3_presence_stability_fix as presence_module
import src.platform.display_f3_runtime_contract_fix as contract_module
import src.platform.display_f3_check_transition_guard as transition_module
from src.platform.display_f3_contour_check_identity import F3TrackedRawCheckAnalyzer
from src.platform.display_f3_object_tracking import (
    F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP,
    F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS,
    get_tracking_runtime,
    reset_tracking_cycle,
)


F3_RUNTIME_AUTHORITIES_SOURCE = "f3_runtime_authorities"
F3_TRACKING_PRESENCE_SOURCE = "f3_tracking_current_lock_presence"
F3_MASK_PATTERN_PRESENCE_SOURCE = "f3_semantic_mask_pattern_presence"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _camera_frame_id_from_token(token):
    if (
        isinstance(token, (list, tuple))
        and len(token) >= 2
        and token[0] == "camera"
    ):
        try:
            return int(token[1])
        except (TypeError, ValueError):
            return None
    return None


def _current_luminous_alignment_for_check(
    tracking: dict | None,
    energy: dict | None,
    check_id: str,
) -> bool:
    """Reconcilia a latência normal entre tracking HIGH e energia do frame live.

    A geometria luminosa continua pertencendo ao tracker. A autoridade de energia
    pode apenas consumir esse lock quando ele é atual, pertence ao mesmo CHECK e
    ainda está dentro dos mesmos limites de frescor usados pelo pipeline pesado.
    """
    data = tracking if isinstance(tracking, dict) else {}
    evidence = energy if isinstance(energy, dict) else {}
    expected_reference = f"luminous:{str(check_id or '')}"

    if not (
        bool(data.get("locked"))
        and bool(data.get("evidence_current"))
        and str(data.get("source_type") or "") == "luminous_segment_grid"
        and str(data.get("reference") or "") == expected_reference
        and bool(data.get("luminous_validated_mask_ids"))
    ):
        return False

    try:
        age_ms = float(data.get("verified_age_ms", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    if (
        age_ms < 0.0
        or age_ms > float(F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS)
    ):
        return False

    tracking_frame_id = data.get("frame_id")
    try:
        tracking_frame_id = (
            int(tracking_frame_id)
            if tracking_frame_id is not None
            else None
        )
    except (TypeError, ValueError):
        return False
    energy_frame_id = _camera_frame_id_from_token(evidence.get("frame_token"))
    if (
        tracking_frame_id is not None
        and energy_frame_id is not None
        and abs(energy_frame_id - tracking_frame_id)
        > int(F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP)
    ):
        return False

    return True


def _semantic_mask_pattern_presence_evidence(
    repository,
    project_name: str,
    energy: dict | None,
) -> dict:
    """Transforma padrão luminoso conhecido em evidência positiva de ocupação.

    Não aprova CHECK. A função somente produz evidência para a autoridade de
    presença. EMPTY confirmado continua tendo precedência absoluta.
    """
    data = energy if isinstance(energy, dict) else {}
    result = {
        "available": False,
        "source": F3_MASK_PATTERN_PRESENCE_SOURCE,
        "board_present": False,
        "presence_confirmed": False,
        "empty_confirmed": False,
        "powered_confirmed": bool(data.get("powered_confirmed")),
        "matched_check_ids": [],
        "matched_check_names": [],
        "reason": "evidencia_semantica_mascaras_indisponivel",
    }

    if not (
        bool(data.get("available"))
        and bool(data.get("powered_confirmed"))
        and not bool(data.get("off_confirmed"))
    ):
        result["reason"] = "mascaras_nao_confirmam_padrao_energizado"
        return result

    details = [
        item
        for item in (data.get("details") or ())
        if isinstance(item, dict) and str(item.get("mask_id") or "")
    ]
    if not details:
        result["reason"] = "mascaras_sem_detalhes_semanticos"
        return result

    observed: dict[str, str] = {}
    uncertain_ids: list[str] = []
    for item in details:
        mask_id = str(item.get("mask_id") or "")
        winner = str(item.get("winner") or "").strip().lower()
        classified = str(item.get("classified") or "").strip().lower()
        if winner == "powered" and classified in {"on", "low_light"}:
            observed[mask_id] = "on"
        elif winner == "off" and classified == "off":
            observed[mask_id] = "off"
        else:
            uncertain_ids.append(mask_id)

    if not observed:
        result["reason"] = "nenhuma_mascara_com_estado_confiavel"
        result["uncertain_mask_ids"] = uncertain_ids
        return result

    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []

    matched_ids: list[str] = []
    matched_names: list[str] = []
    matched_expected_on_counts: dict[str, int] = {}
    contradictions_by_check: dict[str, list[str]] = {}

    for check in checks or ():
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        if not check_id:
            continue
        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        expected_on_ids = [
            str(mask_id)
            for mask_id, state in states.items()
            if str(state or "").strip().lower() == "on"
        ]
        if not expected_on_ids:
            continue

        # Presença positiva exige o núcleo ON completo do estado aprendido.
        if any(observed.get(mask_id) != "on" for mask_id in expected_on_ids):
            continue

        contradictions = []
        for mask_id, physical_state in observed.items():
            expected = str(states.get(mask_id) or "").strip().lower()
            if expected not in {"on", "off"}:
                continue
            if physical_state != expected:
                contradictions.append(mask_id)
        if contradictions:
            contradictions_by_check[check_id] = contradictions
            continue

        matched_ids.append(check_id)
        matched_names.append(str(check.get("name") or check_id).strip().upper())
        matched_expected_on_counts[check_id] = len(expected_on_ids)

    result.update(
        available=True,
        confident_observed_mask_count=len(observed),
        uncertain_mask_ids=uncertain_ids,
        matched_check_ids=matched_ids,
        matched_check_names=matched_names,
        matched_expected_on_counts=matched_expected_on_counts,
        contradictions_by_check=contradictions_by_check,
    )
    if not matched_ids:
        # D-044: presença física não pode depender de o produto estar BOM.
        # A autoridade global de energia já exige votação multi-máscara
        # discriminante para publicar powered_confirmed. Se essa emissão existe,
        # existe uma placa/display energizado no suporte mesmo quando UMA ou mais
        # máscaras divergem do CHECK e, portanto, nenhum padrão configurado fica
        # 100% conforme. Isso confirma somente OCUPAÇÃO; não identifica CHECK e
        # não concede OK/NG por conta própria.
        result.update(
            board_present=True,
            presence_confirmed=True,
            empty_confirmed=False,
            presence_mode="powered_semantic_energy_without_check_identity",
            powered_votes=int(data.get("powered_votes", 0) or 0),
            off_votes=int(data.get("off_votes", 0) or 0),
            tie_votes=int(data.get("tie_votes", 0) or 0),
            required_powered_votes=int(
                data.get("required_powered_votes", 0)
                or data.get("required_consensus_votes", 0)
                or 0
            ),
            reason="emissao_semantica_confirma_placa_com_check_divergente",
        )
        return result

    result.update(
        board_present=True,
        presence_confirmed=True,
        empty_confirmed=False,
        presence_mode="complete_configured_check_pattern",
        reason="padrao_semantico_energizado_confirma_placa",
    )
    return result


class F3TrackingAuthority:
    """Proprietário explícito da instância stateful do tracker F3."""

    def __init__(self, app) -> None:
        self.app = app
        self.runtime = get_tracking_runtime(app)

    def reset(self) -> None:
        if self.runtime is not None:
            self.runtime.reset()

    def presence_evidence(self) -> dict:
        """Expõe somente evidência óptica atual que pode provar presença física."""
        result = (
            getattr(self.runtime, "last_result", None)
            if self.runtime is not None
            else None
        )
        last_verified_s = float(
            getattr(self.runtime, "last_verified_s", 0.0) or 0.0
        ) if self.runtime is not None else 0.0
        verified_age_ms = (
            max(0.0, (time.monotonic() - last_verified_s) * 1000.0)
            if last_verified_s > 0.0
            else float("inf")
        )
        return {
            "available": result is not None,
            "source": F3_TRACKING_PRESENCE_SOURCE,
            "locked": bool(getattr(result, "locked", False)),
            "evidence_current": bool(
                getattr(result, "evidence_current", False)
            ),
            "reference": str(getattr(result, "reference", "") or ""),
            "reason": str(getattr(result, "reason", "") or ""),
            "source_type": str(getattr(result, "source_type", "") or ""),
            "frame_id": (
                getattr(self.runtime, "last_frame_id", None)
                if self.runtime is not None
                else None
            ),
            "verified_age_ms": round(float(verified_age_ms), 2),
            "luminous_validated_mask_ids": list(
                getattr(result, "luminous_validated_mask_ids", ()) or ()
            ),
            "luminous_alignment_mode": str(
                getattr(result, "luminous_alignment_mode", "") or ""
            ),
        }

    def stats(self) -> dict:
        evidence = self.presence_evidence()
        return {
            "owner": "F3TrackingAuthority",
            "ready": bool(getattr(self.runtime, "ready", False)),
            "project": str(getattr(self.runtime, "project", "") or ""),
            "locked": bool(evidence.get("locked")),
            "evidence_current": bool(evidence.get("evidence_current")),
            "reference": str(evidence.get("reference") or ""),
            "reason": str(evidence.get("reason") or ""),
        }


class F3PresenceAuthority:
    """Única memória de estabilidade e decisão de presença do runtime canônico."""

    def __init__(self, repository=None) -> None:
        self.repository = repository
        self._latch: dict | None = None

    def reset(self) -> None:
        self._latch = None

    def evaluate(
        self,
        state: dict | None,
        tracking: dict | None = None,
        *,
        energy: dict | None = None,
        project_name: str = "",
    ) -> dict:
        evidence = presence_module.avaliar_presenca_melhor_ocupado_f3(state)
        result = deepcopy(evidence)

        # EMPTY confirmado tem precedência sobre qualquer pose do tracker. O
        # rearme físico nunca pode ser mascarado por geometria residual.
        if result.get("empty_confirmed"):
            self._latch = None
            return result

        # A presença visual explícita continua válida e alimenta somente a
        # memória curta já existente para ambiguidade entre frames.
        if result.get("board_present") and result.get("presence_confirmed"):
            self._latch = {"frames": 0, "evidence": deepcopy(result)}
            return result

        # O filtro/display já localizado pelo tracker é evidência física positiva
        # de placa no suporte. Somente lock confirmado no frame atual possui
        # autoridade: lock mantido por grace period (evidence_current=False) não
        # promove presença e não alimenta o latch visual.
        tracking_evidence = tracking if isinstance(tracking, dict) else {}
        if (
            bool(tracking_evidence.get("locked"))
            and bool(tracking_evidence.get("evidence_current"))
        ):
            result.update(
                available=True,
                source=F3_TRACKING_PRESENCE_SOURCE,
                board_present=True,
                presence_confirmed=True,
                empty_confirmed=False,
                tracking_presence_confirmed=True,
                tracking_reference=str(
                    tracking_evidence.get("reference") or ""
                ),
                tracking_reason=str(tracking_evidence.get("reason") or ""),
                reason="tracking_lock_atual_confirma_placa",
            )
            return result

        # D-042: se a cena global não separa PLACA x EMPTY, a memória
        # semântica das máscaras pode provar ocupação. A energia só fornece a
        # observação; esta autoridade continua sendo a única que promove presença.
        semantic = _semantic_mask_pattern_presence_evidence(
            self.repository,
            str(project_name or ""),
            energy,
        )
        result["semantic_mask_presence_diagnostic"] = deepcopy(semantic)
        if bool(semantic.get("presence_confirmed")):
            result.update(
                available=True,
                source=F3_MASK_PATTERN_PRESENCE_SOURCE,
                board_present=True,
                presence_confirmed=True,
                empty_confirmed=False,
                semantic_mask_presence_confirmed=True,
                semantic_mask_matched_check_ids=list(
                    semantic.get("matched_check_ids") or ()
                ),
                semantic_mask_matched_check_names=list(
                    semantic.get("matched_check_names") or ()
                ),
                semantic_mask_presence_mode=str(
                    semantic.get("presence_mode") or ""
                ),
                reason=str(
                    semantic.get("reason")
                    or "padrao_semantico_energizado_confirma_placa"
                ),
            )
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
        tracking: dict | None = None,
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

            # O worker de tracking e a leitura física de energia terminam em
            # instantes diferentes. Se a energia do frame live está confirmada,
            # aceite o lock luminoso ATUAL do proprietário canônico do tracking
            # para o mesmo CHECK em vez de bloquear um 28/28 correto só porque
            # a geometria publicada no frame de energia ainda era estrutural.
            if (
                evidence.get("powered_confirmed")
                and evidence.get("spatial_alignment_required") is True
                and evidence.get("spatial_alignment_ready") is not True
                and _current_luminous_alignment_for_check(
                    tracking,
                    evidence,
                    check_id,
                )
            ):
                tracking_data = tracking if isinstance(tracking, dict) else {}
                evidence.update(
                    spatial_alignment_ready=True,
                    spatial_alignment_source="runtime_current_luminous_tracking",
                    spatial_alignment_reconciled_from_tracking=True,
                    spatial_alignment_tracking_reference=str(
                        tracking_data.get("reference") or ""
                    ),
                    spatial_alignment_tracking_frame_id=(
                        tracking_data.get("frame_id")
                    ),
                    spatial_alignment_tracking_age_ms=(
                        tracking_data.get("verified_age_ms")
                    ),
                    spatial_alignment_luminous_mask_ids=list(
                        tracking_data.get("luminous_validated_mask_ids") or ()
                    ),
                )

            spatial_ready = evidence.get("spatial_alignment_ready") is not False
            if evidence.get("powered_confirmed"):
                if intermittent and spatial_ready:
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
                        held_evidence = (
                            latch.get("evidence")
                            if isinstance(latch.get("evidence"), dict)
                            else {}
                        )
                        evidence.update(
                            intermittent_phase_hold=True,
                            intermittent_live_energy_state=str(
                                evidence.get("energy_state") or "unconfirmed"
                            ),
                            intermittent_hold_age_ms=int(round(age * 1000.0)),
                            energy_state=power_module.F3_POWER_STATE_POWERED,
                            powered_confirmed=True,
                            off_confirmed=False,
                            spatial_alignment_ready=(
                                held_evidence.get("spatial_alignment_ready")
                                is not False
                            ),
                        )
                    elif age > float(presence_module.F3_INTERMITTENT_POWER_HOLD_S):
                        self._intermittent_latch = None
            else:
                self._intermittent_latch = None

            if evidence.get("powered_confirmed"):
                spatial_ready = (
                    evidence.get("spatial_alignment_ready") is not False
                )
                output.update(
                    kind="powered",
                    text=(
                        f"PLACA NO SUPORTE • LIGADA • {check_name} • FASE OFF INTERMITENTE"
                        if bool(evidence.get("intermittent_phase_hold"))
                        and spatial_ready
                        else (
                            f"PLACA NO SUPORTE • LIGADA • ANALISANDO {check_name}"
                            if spatial_ready
                            else f"PLACA NO SUPORTE • LIGADA • ALINHANDO {check_name}"
                        )
                    ),
                    color=operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
                    allow_auto=bool(spatial_ready),
                    physical_state_key=(
                        "check:powered_by_runtime_authority"
                        if spatial_ready
                        else "check:powered_waiting_luminous_alignment"
                    ),
                    expected_check_id=check_id,
                    powered_board_confirmed=True,
                    power_gate_blocked=not bool(spatial_ready),
                    power_gate_reason=(
                        "presenca_estavel_e_energia_confirmada"
                        if spatial_ready
                        else "energia_confirmada_aguardando_alinhamento_segmentos"
                    ),
                    power_authority_source=F3_RUNTIME_AUTHORITIES_SOURCE,
                    power_evidence=deepcopy(evidence),
                )
                decision_allowed = bool(spatial_ready)
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

    def configure(self, checks, *, reset: bool = False) -> bool:
        return self.runtime.configurar_checks(checks, reiniciar=bool(reset))

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
        self.presence = F3PresenceAuthority(self.repository)
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
        # EMPTY encerra a identidade física da placa anterior. Além dos latches
        # de presença/energia, descarte a pose e o anchor angular para que a
        # próxima placa possa ser adquirida novamente sem herdar geometria.
        try:
            reset_tracking_cycle(self.app)
        except Exception:
            self.tracking.reset()
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

    def _cache_signature(
        self,
        frame,
        project_name: str,
        context: dict | None,
        tracking: dict | None,
    ):
        tracking_evidence = tracking if isinstance(tracking, dict) else {}
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
            bool(tracking_evidence.get("locked")),
            bool(tracking_evidence.get("evidence_current")),
            str(tracking_evidence.get("reference") or ""),
            str(tracking_evidence.get("reason") or ""),
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

        tracking_evidence = self.tracking.presence_evidence()
        signature = self._cache_signature(
            frame,
            project_name,
            context,
            tracking_evidence,
        )
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

        # A leitura das máscaras é uma observação do mesmo frame e pode existir
        # antes do gate final de presença. Isso remove a dependência circular
        # sem dar à energia autoridade para declarar presença por conta própria.
        energy = (
            self.power.evaluate(frame, project_name, context)
            if str(state.get("kind") or "").strip().lower() != "empty"
            else {}
        )
        presence = self.presence.evaluate(
            state,
            tracking_evidence,
            energy=energy,
            project_name=project_name,
        )
        if bool(presence.get("empty_confirmed")):
            energy = {}
        state = self.power.apply(
            state,
            presence,
            energy,
            project_name=project_name,
            context=context,
            tracking=tracking_evidence,
        )
        rearm_pending = bool(
            getattr(self.app, "_display_f3_waiting_empty_rearm", False)
            or getattr(
                self.app,
                "_display_f3_waiting_new_board_after_empty",
                False,
            )
        )
        if rearm_pending:
            # A autoridade canônica é instalada por último e substitui o builder
            # histórico. Portanto o handoff físico também precisa viver aqui:
            # durante rearme, use o detector dedicado EMPTY x placa, com debounce
            # próprio e fase explícita de nova placa. O gate simples sozinho
            # depende do classificador geral chamar a cena de "empty" e pode ficar
            # preso em um CHECK antigo mesmo com o suporte fisicamente vazio.
            state = cycle_rearm_module.aplicar_rearme_fisico_dedicado_f3(
                self.app,
                self._matcher,
                frame,
                project_name,
                state,
            )
        else:
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
