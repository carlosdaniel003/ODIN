from __future__ import annotations

import tkinter as tk

import src.platform.display_visual_reference_status as visual_status_module
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_TYPES,
    DisplayVisualReferenceMatcher,
)


F3_OPERATIONAL_PHYSICAL_MARGIN = 0.03
F3_OPERATIONAL_STATUS_COLORS = {
    "empty": "#CBD5E1",
    "off": "#FBBF24",
    "check": "#7DD3FC",
    "unknown": "#FDE68A",
    "unavailable": "#94A3B8",
}


def _score_candidate(matcher, current_small, metadata: dict | None) -> dict | None:
    if not isinstance(metadata, dict):
        return None
    score = matcher._score(current_small, metadata)
    if score is None:
        return None
    threshold = matcher._threshold(metadata)
    return {
        "score": float(score),
        "threshold": float(threshold),
        "matched": float(score) >= float(threshold),
    }


def resolver_estado_operacional_f3(
    *,
    empty_candidate: dict | None,
    off_candidate: dict | None,
    current_check_candidate: dict | None,
    current_check_name: str = "",
    current_check_id: str = "",
    last_check_candidate: dict | None = None,
    last_check_name: str = "",
    last_check_id: str = "",
    board_references_complete: bool = False,
) -> dict:
    """Resolve o estado legado; o perfil final recebe o classificador físico."""

    def matched(candidate: dict | None) -> bool:
        return bool(isinstance(candidate, dict) and candidate.get("matched"))

    def score(candidate: dict | None) -> float:
        try:
            return float((candidate or {}).get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    check_candidate = None
    check_name = ""
    check_id = ""

    current_ok = matched(current_check_candidate)
    last_ok = matched(last_check_candidate)
    if current_ok and last_ok:
        current_score = score(current_check_candidate)
        last_score = score(last_check_candidate)
        if current_score >= last_score:
            check_candidate = current_check_candidate
            check_name = str(current_check_name or current_check_id or "CHECK")
            check_id = str(current_check_id or "")
        else:
            check_candidate = last_check_candidate
            check_name = str(last_check_name or last_check_id or "CHECK")
            check_id = str(last_check_id or "")
    elif current_ok:
        check_candidate = current_check_candidate
        check_name = str(current_check_name or current_check_id or "CHECK")
        check_id = str(current_check_id or "")
    elif last_ok:
        check_candidate = last_check_candidate
        check_name = str(last_check_name or last_check_id or "CHECK")
        check_id = str(last_check_id or "")

    check_score = score(check_candidate)
    empty_score = score(empty_candidate)
    off_score = score(off_candidate)

    if matched(empty_candidate) and (
        check_candidate is None
        or empty_score >= check_score + F3_OPERATIONAL_PHYSICAL_MARGIN
    ) and empty_score >= off_score:
        return {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "color": F3_OPERATIONAL_STATUS_COLORS["empty"],
            "allow_auto": False,
        }

    if matched(off_candidate) and (
        check_candidate is None
        or off_score >= check_score + F3_OPERATIONAL_PHYSICAL_MARGIN
    ):
        return {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "color": F3_OPERATIONAL_STATUS_COLORS["off"],
            "allow_auto": False,
        }

    if check_candidate is not None:
        normalized_name = str(check_name or "CHECK").strip().upper()
        return {
            "kind": "check",
            "text": f"DISPLAY EM {normalized_name}",
            "color": F3_OPERATIONAL_STATUS_COLORS["check"],
            "allow_auto": True,
            "check_name": normalized_name,
            "check_id": check_id,
            "score": check_score,
        }

    if matched(off_candidate):
        return {
            "kind": "off",
            "text": "PLACA NO SUPORTE • DESLIGADA",
            "color": F3_OPERATIONAL_STATUS_COLORS["off"],
            "allow_auto": False,
        }

    if matched(empty_candidate):
        return {
            "kind": "empty",
            "text": "PLACA FORA DO SUPORTE",
            "color": F3_OPERATIONAL_STATUS_COLORS["empty"],
            "allow_auto": False,
        }

    if not board_references_complete:
        return {
            "kind": "unavailable",
            "text": "REFERÊNCIAS DE PRESENÇA NÃO CONFIGURADAS",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": True,
        }

    return {
        "kind": "unknown",
        "text": "IDENTIFICANDO...",
        "color": F3_OPERATIONAL_STATUS_COLORS["unknown"],
        "allow_auto": False,
    }


def _build_operational_state(self, frame, project_name: str, context: dict | None) -> dict:
    repository = getattr(self, "display_project_repository", None)
    if repository is None:
        return {
            "kind": "unavailable",
            "text": "PROJETO DISPLAY NÃO DISPONÍVEL",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": False,
        }

    matcher = getattr(self, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        matcher = DisplayVisualReferenceMatcher(repository)
        self._display_f3_operational_matcher = matcher

    current_small = visual_status_module._small_image(frame)
    if current_small is None:
        return {
            "kind": "unknown",
            "text": "AGUARDANDO CÂMERA",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            "allow_auto": False,
        }

    project_references = matcher.project_store.get_all(project_name)
    board_complete = all(kind in project_references for kind in DISPLAY_PROJECT_REFERENCE_TYPES)
    empty_candidate = _score_candidate(
        matcher,
        current_small,
        project_references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT),
    )
    off_candidate = _score_candidate(
        matcher,
        current_small,
        project_references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF),
    )

    current_check_id = str((context or {}).get("check_id") or "")
    current_check_name = str((context or {}).get("check_name") or current_check_id)
    current_metadata = (
        matcher.check_store.get(project_name, current_check_id)
        if current_check_id
        else None
    )
    current_candidate = _score_candidate(matcher, current_small, current_metadata)

    last_check_id = str(getattr(self, "_display_f3_last_recognized_check_id", "") or "")
    last_check_name = str(
        getattr(self, "_display_f3_last_recognized_check_name", "") or last_check_id
    )
    last_candidate = None
    if last_check_id and last_check_id != current_check_id:
        last_metadata = matcher.check_store.get(project_name, last_check_id)
        last_candidate = _score_candidate(matcher, current_small, last_metadata)

    state = resolver_estado_operacional_f3(
        empty_candidate=empty_candidate,
        off_candidate=off_candidate,
        current_check_candidate=current_candidate,
        current_check_name=current_check_name,
        current_check_id=current_check_id,
        last_check_candidate=last_candidate,
        last_check_name=last_check_name,
        last_check_id=last_check_id,
        board_references_complete=board_complete,
    )
    state["current_check_reference_configured"] = current_metadata is not None
    state["board_references_complete"] = board_complete
    return state


def _build_visual_analysis_state(self, frame, project_name: str) -> dict:
    """Classificação puramente visual das referências de projeto; nunca decide o fluxo."""
    repository = getattr(self, "display_project_repository", None)
    if repository is None:
        return {
            "text": "ANÁLISE VISUAL: projeto indisponível",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
        }

    matcher = getattr(self, "_display_f3_operational_matcher", None)
    if matcher is None or getattr(matcher, "repository", None) is not repository:
        matcher = DisplayVisualReferenceMatcher(repository)
        self._display_f3_operational_matcher = matcher

    current_small = visual_status_module._small_image(frame)
    if current_small is None:
        return {
            "text": "ANÁLISE VISUAL: aguardando câmera",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
        }

    references = matcher.project_store.get_all(project_name)
    if not all(kind in references for kind in DISPLAY_PROJECT_REFERENCE_TYPES):
        return {
            "text": "ANÁLISE VISUAL: configure as 2 referências do projeto",
            "color": F3_OPERATIONAL_STATUS_COLORS["unavailable"],
        }

    empty_candidate = _score_candidate(
        matcher,
        current_small,
        references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT),
    )
    off_candidate = _score_candidate(
        matcher,
        current_small,
        references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF),
    )

    empty_score = float((empty_candidate or {}).get("score", 0.0) or 0.0)
    off_score = float((off_candidate or {}).get("score", 0.0) or 0.0)
    empty_matched = bool((empty_candidate or {}).get("matched"))
    off_matched = bool((off_candidate or {}).get("matched"))

    if empty_matched and off_matched:
        if abs(empty_score - off_score) < F3_OPERATIONAL_PHYSICAL_MARGIN:
            return {
                "text": "ANÁLISE VISUAL: identificando estado da placa...",
                "color": F3_OPERATIONAL_STATUS_COLORS["unknown"],
            }
        if empty_score > off_score:
            off_matched = False
        else:
            empty_matched = False

    if empty_matched:
        return {
            "text": f"ANÁLISE VISUAL: PLACA FORA DO SUPORTE • {empty_score * 100:.0f}%",
            "color": F3_OPERATIONAL_STATUS_COLORS["empty"],
        }

    if off_matched:
        return {
            "text": f"ANÁLISE VISUAL: PLACA DESLIGADA NO SUPORTE • {off_score * 100:.0f}%",
            "color": F3_OPERATIONAL_STATUS_COLORS["off"],
        }

    best_score = max(empty_score, off_score)
    return {
        "text": f"ANÁLISE VISUAL: estado visual não identificado • melhor {best_score * 100:.0f}%",
        "color": F3_OPERATIONAL_STATUS_COLORS["unknown"],
    }


def _set_operational_reference_status(self, text: str, color: str) -> None:
    if bool(getattr(self, "_display_ng_evidence_frozen", False)):
        return
    label = getattr(self, "operational_reference_state_label", None)
    if label is None:
        return
    if str(label.cget("text")) != str(text) or str(label.cget("fg")) != str(color):
        label.configure(text=str(text), fg=str(color))


def _set_visual_analysis_status(self, text: str, color: str) -> None:
    if bool(getattr(self, "_display_ng_evidence_frozen", False)):
        return
    label = getattr(self, "visual_analysis_state_label", None)
    if label is None:
        return
    if str(label.cget("text")) != str(text) or str(label.cget("fg")) != str(color):
        label.configure(text=str(text), fg=str(color))


def _ignore_legacy_dual_status(self, *_args, **_kwargs) -> None:
    return None


def _install_single_status_window() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_f3_single_operational_status_installed", False)):
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        previous_box = getattr(self, "_display_reference_status_box", None)
        if previous_box is not None:
            try:
                previous_box.destroy()
            except Exception:
                pass

        self.board_reference_state_label = None
        self.visual_reference_state_label = None

        status_box = tk.Frame(self.preview_header, bg=self.PREVIEW_PANEL, height=48)
        status_box.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        status_box.grid_propagate(False)
        status_box.grid_columnconfigure(0, weight=1)
        self._display_operational_status_box = status_box

        self.operational_reference_state_label = tk.Label(
            status_box,
            text="IDENTIFICANDO...",
            font=("DejaVu Sans", 10, "bold"),
            bg=self.PREVIEW_PANEL,
            fg=F3_OPERATIONAL_STATUS_COLORS["unknown"],
            anchor="w",
            justify="left",
        )
        self.operational_reference_state_label.grid(
            row=0,
            column=0,
            sticky="ew",
        )

        self.visual_analysis_state_label = tk.Label(
            status_box,
            text="ANÁLISE VISUAL: aguardando referências do projeto",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.PREVIEW_PANEL,
            fg=F3_OPERATIONAL_STATUS_COLORS["unavailable"],
            anchor="w",
            justify="left",
        )
        self.visual_analysis_state_label.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(2, 0),
        )

    cls.__init__ = init
    cls.set_operational_reference_status = _set_operational_reference_status
    cls.set_visual_analysis_status = _set_visual_analysis_status
    cls.set_visual_reference_status = _ignore_legacy_dual_status
    cls._display_f3_single_operational_status_installed = True


def _install_operational_auto_gate() -> None:
    """Mantém o estado físico informativo sem decidir o CHECK.

    A autoridade de H1/BLUE/USB/AUX é a análise óptica das máscaras executada por
    DisplayAutomaticCheckF3Mixin. O estado físico continua sendo publicado no
    painel e só participa do rearmamento terminal: depois de OK/NG/descartada,
    uma nova placa não pode começar até o suporte vazio ser confirmado.
    """
    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_operational_gate_installed", False)):
        return

    original_process = cls._process_display_auto_check

    def process(self):
        if not bool(getattr(self, "display_f3_ativo", False)):
            return original_process(self)

        frame = getattr(self, "camera_frame_atual", None)
        repository = getattr(self, "display_project_repository", None)
        window = getattr(self, "display_f3_window", None)
        if (
            frame is None
            or getattr(frame, "size", 0) == 0
            or repository is None
            or window is None
        ):
            return original_process(self)

        project_name = repository.obter_projeto_ativo()
        if not project_name:
            return original_process(self)

        context = self._display_auto_current_context()
        state = _build_operational_state(self, frame, str(project_name), context)
        self._display_f3_operational_state = dict(state)

        try:
            window.set_operational_reference_status(
                str(state.get("text") or "IDENTIFICANDO..."),
                str(state.get("color") or F3_OPERATIONAL_STATUS_COLORS["unknown"]),
            )
        except Exception:
            pass

        # Status paralelo e estritamente informativo. Usa somente as duas fotos
        # de presença do Projeto Display (e a ROI, quando configurada). O valor
        # não entra em nenhuma condição de aprovação, reprovação ou transição.
        visual_state = _build_visual_analysis_state(self, frame, str(project_name))
        try:
            window.set_visual_analysis_status(
                str(visual_state.get("text") or "ANÁLISE VISUAL: identificando..."),
                str(
                    visual_state.get("color")
                    or F3_OPERATIONAL_STATUS_COLORS["unknown"]
                ),
            )
        except Exception:
            pass

        # Memória usada apenas pela apresentação/classificação física. Ela não
        # autoriza, reprova nem avança o CHECK.
        kind = str(state.get("kind") or "unknown")
        if kind == "check":
            self._display_f3_last_recognized_check_id = str(state.get("check_id") or "")
            self._display_f3_last_recognized_check_name = str(
                state.get("check_name") or ""
            )
        elif kind == "empty":
            self._display_f3_last_recognized_check_id = ""
            self._display_f3_last_recognized_check_name = ""

        # Única trava física mantida: após um evento terminal, o mesmo produto
        # não pode iniciar um novo ciclo até PLACA FORA DO SUPORTE ser confirmada.
        # O wrapper de rearmamento limpa este latch assim que EMPTY é reconhecido.
        if bool(getattr(self, "_display_f3_waiting_empty_rearm", False)):
            try:
                self._reset_display_auto_stability(transition=False)
            except Exception:
                pass
            try:
                self._display_auto_set_preview_status(
                    "AUTO • retire a placa • aguardando PLACA FORA DO SUPORTE",
                    "#FDE68A",
                )
            except Exception:
                pass
            return None

        # Fora do rearmamento terminal, o estado físico não participa da decisão.
        # O processo original classifica as máscaras, aplica debounce e registra
        # OK/NG/avanço conforme o CHECK lógico atual.
        return original_process(self)

    cls._process_display_auto_check = process
    cls._display_f3_operational_gate_installed = True


_DISPLAY_F3_OPERATIONAL_STATUS_INSTALLED = False


def instalar_status_operacional_display_f3() -> None:
    """Instala status físico; decisões de CHECK permanecem pelas máscaras no F3."""
    global _DISPLAY_F3_OPERATIONAL_STATUS_INSTALLED
    if _DISPLAY_F3_OPERATIONAL_STATUS_INSTALLED:
        return
    _install_single_status_window()
    _install_operational_auto_gate()
    _DISPLAY_F3_OPERATIONAL_STATUS_INSTALLED = True
