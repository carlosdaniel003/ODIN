from __future__ import annotations

"""Autoridade final de entrada física entre CHECKS do Display F3.

Energia, presença e conformidade de máscaras respondem perguntas diferentes:

* presença: existe placa no suporte?
* energia: o display está ligado?
* conformidade: o padrão lido combina com o CHECK lógico?
* entrada física: a placa realmente saiu do CHECK anterior e chegou ao atual?

O bug corrigido aqui acontecia quando o CHECK lógico AUX era analisado/aprovado
antes de a placa física chegar em AUX. Uma leitura de máscaras 100% conforme ou
energia confirmada não podem, sozinhas, provar a transição USB -> AUX.

Esta camada usa as fotos já cadastradas dos dois CHECKS consecutivos e compara
somente as regiões que realmente mudam entre eles. Ela é instalada por último,
na instância real do F3, e também endurece o gate de entrada do runtime.
"""

from copy import deepcopy
from types import MethodType

from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_f3_check_transition_guard import (
    avaliar_transicao_fisica_checks_f3,
)


F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE = (
    "f3_previous_to_current_check_physical_transition_authority"
)


def _context(app) -> dict | None:
    try:
        value = app._display_auto_current_context()
    except Exception:
        value = None
    return value if isinstance(value, dict) else None


def _snapshot(app) -> dict:
    runtime = getattr(app, "display_check_runtime", None)
    if runtime is None:
        return {}
    try:
        value = runtime.snapshot()
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _check_id_from_row(row: dict | None) -> str:
    return str((row or {}).get("id") or "").strip()


def avaliar_entrada_fisica_check_f3(
    app,
    *,
    frame=None,
    context: dict | None = None,
) -> dict:
    """Confirma se o CHECK lógico atual já existe fisicamente no frame."""
    ctx = context if isinstance(context, dict) else _context(app)
    snapshot = _snapshot(app)
    current = snapshot.get("current_check")
    if not isinstance(current, dict):
        return {
            "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "check_atual_ausente",
        }

    try:
        index = int(snapshot.get("current_index", 0) or 0)
    except (TypeError, ValueError):
        index = 0

    current_id = str((ctx or {}).get("check_id") or _check_id_from_row(current)).strip()
    current_name = str(
        (ctx or {}).get("check_name") or current.get("name") or current_id
    ).strip().upper()

    # H1 é o referencial físico inicial do ciclo e possui seu próprio gate de
    # presença/energia. Não existe CHECK anterior para comparar.
    if index <= 0:
        return {
            "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
            "available": True,
            "confirmed": True,
            "reason": "primeiro_check_sem_transicao_anterior",
            "current_check_id": current_id,
            "current_check_name": current_name,
            "current_index": index,
        }

    checks = [
        item for item in (snapshot.get("checks") or ())
        if isinstance(item, dict)
    ]
    if index >= len(checks):
        return {
            "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
            "available": False,
            "confirmed": False,
            "reason": "indice_check_invalido",
            "current_check_id": current_id,
            "current_index": index,
        }

    previous = checks[index - 1]
    previous_id = _check_id_from_row(previous)
    previous_name = str(previous.get("name") or previous_id).strip().upper()
    if str(previous.get("state") or "") != "completed":
        return {
            "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
            "available": True,
            "confirmed": False,
            "reason": "check_anterior_ainda_nao_concluido",
            "previous_check_id": previous_id,
            "previous_check_name": previous_name,
            "current_check_id": current_id,
            "current_check_name": current_name,
            "current_index": index,
        }

    # Se a autoridade física global reconheceu literalmente o CHECK atual,
    # não precisamos de fallback relativo.
    state = getattr(app, "_display_f3_operational_state", None)
    if isinstance(state, dict):
        kind = str(state.get("kind") or "").strip().lower()
        physical_id = str(state.get("check_id") or "").strip()
        # Não confundir "CHECK promovido pelas próprias máscaras" com uma
        # identificação física independente. Esse era justamente o bypass que
        # permitia o destino lógico validar a si próprio antes da transição real.
        mask_promoted = bool(
            state.get("mask_confirmed_physical_state")
            or str(state.get("source") or "")
            == "f3_current_check_confirmed_by_live_masks"
        )
        if (
            kind == "check"
            and physical_id
            and physical_id == current_id
            and not mask_promoted
        ):
            return {
                "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
                "available": True,
                "confirmed": True,
                "reason": "estado_fisico_exato_corresponde_ao_check",
                "previous_check_id": previous_id,
                "previous_check_name": previous_name,
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                "physical_state": deepcopy(state),
            }

    project_name = str((ctx or {}).get("project_name") or "").strip()
    live_frame = frame if frame is not None else getattr(app, "camera_frame_atual", None)
    evidence = avaliar_transicao_fisica_checks_f3(
        app,
        live_frame,
        project_name,
        previous_id,
        current_id,
    )
    evidence = deepcopy(evidence) if isinstance(evidence, dict) else {}
    confirmed = bool(
        evidence.get("available")
        and evidence.get("current_preferred")
    )

    return {
        "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
        "available": bool(evidence.get("available")),
        "confirmed": confirmed,
        "reason": (
            "transicao_fisica_confirmada"
            if confirmed
            else str(evidence.get("reason") or "transicao_fisica_nao_confirmada")
        ),
        "previous_check_id": previous_id,
        "previous_check_name": previous_name,
        "current_check_id": current_id,
        "current_check_name": current_name,
        "current_index": index,
        "transition_evidence": evidence,
    }


def _analysis_matches_current_context(app, analysis: dict | None) -> bool:
    """A leitura pode ser OK ou NG; só precisa pertencer ao CHECK atual.

    A chegada física ao CHECK é independente da conformidade. Exigir
    analysis['approved'] == True aqui impediria um AUX realmente defeituoso de
    entrar no estado AUX e, consequentemente, de gerar NG.
    """
    if not isinstance(analysis, dict):
        return False
    ctx = _context(app)
    if not isinstance(ctx, dict):
        return False
    return bool(
        analysis.get("ready")
        and str(analysis.get("project_name") or "")
        == str(ctx.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(ctx.get("check_id") or "")
    )


def _install_manual_entry_gate() -> None:
    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_physical_transition_entry_gate", False)):
        return

    def has_manual_entry_evidence(self, analysis: dict) -> bool:
        # A análise só precisa ser uma leitura válida do CHECK atual. A decisão
        # OK/NG vem DEPOIS que a transição física foi confirmada; assim um CHECK
        # defeituoso pode entrar fisicamente e então ser reprovado corretamente.
        if not _analysis_matches_current_context(self, analysis):
            return False

        evidence = avaliar_entrada_fisica_check_f3(
            self,
            frame=getattr(self, "camera_frame_atual", None),
        )
        self._display_f3_physical_transition_authority_status = deepcopy(evidence)
        if not bool(evidence.get("confirmed")):
            target = str(evidence.get("current_check_name") or "CHECK")
            previous = str(evidence.get("previous_check_name") or "CHECK ANTERIOR")
            try:
                self._display_auto_set_preview_status(
                    f"AUTO • {target} • aguardando mudança física {previous} → {target}",
                    "#FDE68A",
                )
            except Exception:
                pass
        return bool(evidence.get("confirmed"))

    cls._display_auto_has_manual_entry_evidence = has_manual_entry_evidence
    cls._display_f3_physical_transition_entry_gate = True


def _install_instance_result_guard(app) -> None:
    if bool(getattr(app, "_display_f3_physical_transition_result_guard", False)):
        return

    previous_register = app.registrar_resultado_check_display_f3

    def guarded_register(self, aprovado: bool = True):
        context = _context(self)
        if not isinstance(context, dict):
            return previous_register(aprovado)

        evidence = avaliar_entrada_fisica_check_f3(
            self,
            frame=getattr(self, "camera_frame_atual", None),
            context=context,
        )
        self._display_f3_physical_transition_authority_status = deepcopy(evidence)

        if not bool(evidence.get("confirmed")):
            target = str(
                evidence.get("current_check_name")
                or context.get("check_name")
                or context.get("check_id")
                or "CHECK"
            ).strip().upper()
            previous = str(
                evidence.get("previous_check_name") or "CHECK ANTERIOR"
            ).strip().upper()
            try:
                self._reset_display_auto_stability(transition=False)
            except Exception:
                pass
            try:
                self._display_auto_set_preview_status(
                    f"AUTO • {target} BLOQUEADO • aguardando mudança física "
                    f"{previous} → {target}",
                    "#FDE68A",
                )
            except Exception:
                pass

            snapshot = _snapshot(self)
            return {
                "event": "physical_transition_blocked",
                "blocked_by": "physical_transition_not_confirmed",
                "approved": bool(aprovado),
                "snapshot": snapshot,
                "transition_authority": deepcopy(evidence),
            }

        return previous_register(aprovado)

    app.registrar_resultado_check_display_f3 = MethodType(guarded_register, app)
    app._display_f3_physical_transition_result_guard = True


def instalar_autoridade_transicao_fisica_checks_f3(app) -> None:
    """Instala o gate mais externo de transição física do F3."""
    _install_manual_entry_gate()
    _install_instance_result_guard(app)
