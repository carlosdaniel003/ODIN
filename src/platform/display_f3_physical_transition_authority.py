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
from src.platform.display_f3_contour_check_identity import (
    F3_CONTOUR_CHECK_IDENTITY_SOURCE,
    avaliar_identidade_visual_checks_por_contorno_f3,
)


F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE = (
    "f3_previous_to_current_check_physical_transition_authority"
)
F3_FIRST_CHECK_FULL_MASK_AUTHORITY_SOURCE = (
    "f3_first_check_full_mask_conformity"
)
F3_CURRENT_CHECK_FULL_MASK_TRANSITION_SOURCE = (
    "f3_current_check_full_mask_transition"
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


def _analise_completa_check_atual(
    analysis: dict | None,
    context: dict | None,
) -> dict | None:
    """Aceita somente análise atual, pronta e 100% conforme nas máscaras ativas."""
    if not isinstance(analysis, dict) or not isinstance(context, dict):
        return None
    if not bool(analysis.get("ready")) or analysis.get("approved") is not True:
        return None
    if (
        str(analysis.get("project_name") or "").strip()
        != str(context.get("project_name") or "").strip()
        or str(analysis.get("check_id") or "").strip()
        != str(context.get("check_id") or "").strip()
    ):
        return None

    try:
        active = int(analysis.get("active_mask_count", 0) or 0)
        matched = int(analysis.get("matched_mask_count", 0) or 0)
    except (TypeError, ValueError):
        active = 0
        matched = 0

    if active <= 0:
        results = [
            item
            for item in (analysis.get("mask_results") or ())
            if isinstance(item, dict)
            and str(item.get("expected") or "").strip().lower() != "ignore"
        ]
        if not results or not all(bool(item.get("matched")) for item in results):
            return None
        active = len(results)
        matched = active

    if matched != active:
        return None

    return {
        "active_mask_count": int(active),
        "matched_mask_count": int(matched),
    }


def _carregar_check_por_id(repository, project_name: str, check_id: str) -> dict | None:
    if repository is None or not str(check_id or "").strip():
        return None
    loader = getattr(repository, "carregar_check", None)
    if callable(loader):
        try:
            value = loader(project_name, check_id)
        except Exception:
            value = None
        if isinstance(value, dict):
            return value
    listar = getattr(repository, "listar_checks", None)
    if callable(listar):
        try:
            checks = listar(project_name)
        except Exception:
            checks = []
        wanted = str(check_id or "").strip().upper()
        for item in checks or ():
            if (
                isinstance(item, dict)
                and str(item.get("id") or "").strip().upper() == wanted
            ):
                return item
    return None


def _diferenca_semantica_checks_consecutivos(
    repository,
    project_name: str,
    previous_check_id: str,
    current_check_id: str,
) -> dict:
    """Prova se os dois CHECKS realmente possuem padrões ON/OFF diferentes.

    Conformidade 100% do destino só pode servir como evidência de transição se
    existir pelo menos uma máscara ativa cujo estado mudou em relação ao CHECK
    anterior. CHECKS semanticamente idênticos continuam dependendo da autoridade
    física independente.
    """
    previous = _carregar_check_por_id(
        repository,
        project_name,
        previous_check_id,
    )
    current = _carregar_check_por_id(
        repository,
        project_name,
        current_check_id,
    )
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return {
            "available": False,
            "different": False,
            "reason": "configuracao_checks_transicao_indisponivel",
            "different_mask_ids": (),
        }

    previous_states = (
        previous.get("mask_states", {})
        if isinstance(previous.get("mask_states"), dict)
        else {}
    )
    current_states = (
        current.get("mask_states", {})
        if isinstance(current.get("mask_states"), dict)
        else {}
    )
    active_states = {"on", "off"}
    mask_ids = sorted(set(previous_states).union(current_states))
    different_ids = []
    for mask_id in mask_ids:
        before = str(previous_states.get(mask_id) or "").strip().lower()
        after = str(current_states.get(mask_id) or "").strip().lower()
        if before in active_states and after in active_states and before != after:
            different_ids.append(str(mask_id))

    return {
        "available": True,
        "different": bool(different_ids),
        "reason": (
            "checks_possuem_mudanca_semantica"
            if different_ids
            else "checks_sem_mudanca_semantica"
        ),
        "different_mask_ids": tuple(different_ids),
        "different_mask_count": len(different_ids),
    }


def avaliar_entrada_fisica_check_f3(
    app,
    *,
    frame=None,
    context: dict | None = None,
    analysis: dict | None = None,
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

    # H1/primeiro CHECK não possui transição anterior. Se o analisador canônico
    # já fechou TODAS as máscaras ativas como conformes no frame atual, essa
    # evidência é suficiente: 28/28 no H1 significa CHECK OK. O contorno fica
    # como fallback de entrada enquanto a análise completa ainda não fechou.
    if index <= 0:
        current_analysis = (
            analysis
            if isinstance(analysis, dict)
            else getattr(app, "_display_auto_last_analysis", None)
        )
        conformity = _analise_completa_check_atual(current_analysis, ctx)
        if isinstance(conformity, dict):
            return {
                "source": F3_FIRST_CHECK_FULL_MASK_AUTHORITY_SOURCE,
                "available": True,
                "confirmed": True,
                "reason": "primeiro_check_conforme_por_todas_mascaras",
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                **conformity,
            }

        identity = getattr(app, "_display_f3_check_identity_status", None)
        if not isinstance(identity, dict) or not identity.get("available"):
            try:
                identity = avaliar_identidade_visual_checks_por_contorno_f3(
                    app,
                    frame=frame,
                    project_name=str((ctx or {}).get("project_name") or ""),
                )
            except Exception:
                identity = {}
        if isinstance(identity, dict) and identity.get("available"):
            identified_id = str(identity.get("best_check_id") or "")
            confirmed = bool(
                identity.get("confirmed")
                and identified_id == current_id
            )
            return {
                "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
                "available": True,
                "confirmed": confirmed,
                "reason": (
                    "primeiro_check_identificado_por_contorno"
                    if confirmed
                    else (
                        "contorno_identificou_outro_check"
                        if identity.get("confirmed") and identified_id
                        else "primeiro_check_ainda_nao_identificado_por_contorno"
                    )
                ),
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                "identity": deepcopy(identity),
            }

        # Compatibilidade fail-safe para projeto antigo sem tracking/contorno.
        return {
            "source": F3_PHYSICAL_TRANSITION_AUTHORITY_SOURCE,
            "available": True,
            "confirmed": True,
            "reason": "primeiro_check_sem_contorno_disponivel",
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

    # D-043: o padrão funcional completo do destino também é evidência física
    # da transição quando ele DIFERE semanticamente do CHECK anterior. Isso não
    # é um atalho por score global: exige análise canônica pronta, 100% conforme
    # e pelo menos uma máscara ON/OFF cujo estado mudou entre os dois CHECKS.
    # Assim BLUE 28/28 não pode ficar bloqueado por uma foto de cena inteira que
    # ainda prefira H1/OFF, enquanto 27/28 continua incapaz de liberar o gate.
    current_analysis = (
        analysis
        if isinstance(analysis, dict)
        else getattr(app, "_display_auto_last_analysis", None)
    )
    conformity = _analise_completa_check_atual(current_analysis, ctx)
    if isinstance(conformity, dict):
        project_name = str((ctx or {}).get("project_name") or "").strip()
        semantic_delta = _diferenca_semantica_checks_consecutivos(
            getattr(app, "display_project_repository", None),
            project_name,
            previous_id,
            current_id,
        )
        if bool(semantic_delta.get("available") and semantic_delta.get("different")):
            return {
                "source": F3_CURRENT_CHECK_FULL_MASK_TRANSITION_SOURCE,
                "available": True,
                "confirmed": True,
                "reason": "check_atual_100pct_confirma_transicao_semantica",
                "previous_check_id": previous_id,
                "previous_check_name": previous_name,
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                "semantic_transition": deepcopy(semantic_delta),
                **conformity,
            }

    # A identidade por contorno compara TODOS os CHECKS no mesmo espaço
    # canônico. Se ela está conclusiva, é uma evidência física mais independente
    # do que a própria análise de conformidade do CHECK esperado.
    identity = getattr(app, "_display_f3_check_identity_status", None)
    if not isinstance(identity, dict) or not identity.get("available"):
        try:
            identity = avaliar_identidade_visual_checks_por_contorno_f3(
                app,
                frame=frame,
                project_name=str((ctx or {}).get("project_name") or ""),
            )
        except Exception:
            identity = {}
    if isinstance(identity, dict) and identity.get("available") and identity.get("confirmed"):
        identified_id = str(identity.get("best_check_id") or "")
        if identified_id == current_id:
            return {
                "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
                "available": True,
                "confirmed": True,
                "reason": "check_atual_identificado_por_contorno",
                "previous_check_id": previous_id,
                "previous_check_name": previous_name,
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                "identity": deepcopy(identity),
            }
        if identified_id:
            return {
                "source": F3_CONTOUR_CHECK_IDENTITY_SOURCE,
                "available": True,
                "confirmed": False,
                "reason": "contorno_identificou_outro_check",
                "previous_check_id": previous_id,
                "previous_check_name": previous_name,
                "current_check_id": current_id,
                "current_check_name": current_name,
                "current_index": index,
                "identity": deepcopy(identity),
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
            analysis=analysis,
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
            analysis=getattr(self, "_display_auto_last_analysis", None),
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
