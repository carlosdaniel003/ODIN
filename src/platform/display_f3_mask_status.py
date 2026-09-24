from __future__ import annotations

import tkinter as tk

from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_f3_live_runtime_fix import atualizar_classificacao_overlay_f3
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


F3_MASK_STATUS_COLORS = {
    "waiting": "#94A3B8",
    "detected": "#86EFAC",
    "partial": "#FDE68A",
    "unavailable": "#FCA5A5",
}


def _analysis_matches_context(analysis: dict | None, context: dict | None) -> bool:
    if not isinstance(analysis, dict) or not isinstance(context, dict):
        return False
    return (
        str(analysis.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(context.get("check_id") or "")
    )


def _plural_count(value: int, singular: str, plural: str) -> str:
    return f"{int(value)} {singular if int(value) == 1 else plural}"


def formatar_status_mascaras_f3(
    analysis: dict | None,
    context: dict | None,
) -> tuple[str, str]:
    """Resume somente o que as máscaras do CHECK corrente estão classificando."""
    if not isinstance(context, dict):
        return "MÁSCARAS • SEM CHECK ATIVO", F3_MASK_STATUS_COLORS["waiting"]

    check_name = str(
        context.get("check_name") or context.get("check_id") or "CHECK"
    ).strip().upper()

    if not _analysis_matches_context(analysis, context):
        return (
            f"MÁSCARAS • {check_name}: AGUARDANDO LEITURA",
            F3_MASK_STATUS_COLORS["waiting"],
        )

    if not bool(analysis.get("ready")):
        reason = str(analysis.get("reason") or "indisponivel").replace("_", " ").upper()
        return (
            f"MÁSCARAS • {check_name}: INDISPONÍVEL • {reason}",
            F3_MASK_STATUS_COLORS["unavailable"],
        )

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
    ]
    total = int(analysis.get("active_mask_count", len(results)) or len(results))
    matched = int(
        analysis.get(
            "effective_matched_mask_count",
            analysis.get(
                "matched_mask_count",
                sum(1 for item in results if bool(item.get("matched"))),
            ),
        )
        or 0
    )

    counts = {
        DISPLAY_CHECK_STATE_ON: 0,
        DISPLAY_CHECK_STATE_OFF: 0,
        DISPLAY_AUTO_CLASS_LOW_LIGHT: 0,
    }
    effective_classifications = analysis.get(
        "effective_classifications"
    )
    if isinstance(effective_classifications, dict):
        classification_values = [
            str(value or "").strip().lower()
            for value in effective_classifications.values()
        ]
    else:
        classification_values = [
            str(item.get("classified") or "").strip().lower()
            for item in results
        ]

    for classified in classification_values:
        if classified in counts:
            counts[classified] += 1

    readings = []
    if counts[DISPLAY_CHECK_STATE_ON]:
        readings.append(
            _plural_count(counts[DISPLAY_CHECK_STATE_ON], "ACESO", "ACESOS")
        )
    if counts[DISPLAY_CHECK_STATE_OFF]:
        readings.append(
            _plural_count(counts[DISPLAY_CHECK_STATE_OFF], "APAGADO", "APAGADOS")
        )
    if counts[DISPLAY_AUTO_CLASS_LOW_LIGHT]:
        readings.append(
            _plural_count(
                counts[DISPLAY_AUTO_CLASS_LOW_LIGHT],
                "POUCA LUZ",
                "POUCA LUZ",
            )
        )
    if not readings:
        readings.append("SEM CLASSIFICAÇÃO")

    detected = total > 0 and matched == total
    state_text = "DETECTADO" if detected else "NÃO CONFIRMADO"
    detail = " • ".join(readings)
    return (
        f"MÁSCARAS • {check_name} {state_text} • {matched}/{total} CONFORMES • {detail}",
        F3_MASK_STATUS_COLORS["detected" if detected else "partial"],
    )


def _set_mask_analysis_status(self, text: str, color: str) -> None:
    if bool(getattr(self, "_display_ng_evidence_frozen", False)):
        return
    label = getattr(self, "mask_analysis_state_label", None)
    if label is None:
        return
    if str(label.cget("text")) != str(text) or str(label.cget("fg")) != str(color):
        label.configure(text=str(text), fg=str(color))


def _install_mask_status_window() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_f3_mask_status_window_installed", False)):
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        status_box = getattr(self, "_display_operational_status_box", None)
        if status_box is None:
            return

        # Pilha informativa do F3: estado operacional, máscaras e, logo abaixo,
        # análise visual. As duas últimas linhas são diagnósticas e não decidem
        # OK/NG, avanço de CHECK ou rearmamento.
        status_box.configure(height=76)
        status_box.grid_propagate(False)
        status_box.grid_rowconfigure(0, weight=0)
        status_box.grid_rowconfigure(1, weight=0)
        status_box.grid_rowconfigure(2, weight=0)

        self.mask_analysis_state_label = tk.Label(
            status_box,
            text="MÁSCARAS • AGUARDANDO LEITURA",
            font=("DejaVu Sans", 9, "bold"),
            bg=self.PREVIEW_PANEL,
            fg=F3_MASK_STATUS_COLORS["waiting"],
            anchor="w",
            justify="left",
        )
        self.mask_analysis_state_label.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(3, 0),
        )

        visual_label = getattr(self, "visual_analysis_state_label", None)
        if visual_label is not None:
            visual_label.grid_configure(
                row=2,
                column=0,
                sticky="ew",
                pady=(3, 0),
            )

    cls.__init__ = init
    cls.set_mask_analysis_status = _set_mask_analysis_status
    cls._display_f3_mask_status_window_installed = True


def _publish_mask_status(app) -> None:
    if not bool(getattr(app, "display_f3_ativo", False)):
        return

    window = getattr(app, "display_f3_window", None)
    if window is None:
        return

    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None

    analysis = getattr(app, "_display_auto_last_analysis", None)
    if isinstance(context, dict) and not _analysis_matches_context(analysis, context):
        try:
            analysis = atualizar_classificacao_overlay_f3(app)
        except Exception:
            analysis = getattr(app, "_display_auto_last_analysis", None)

    text, color = formatar_status_mascaras_f3(analysis, context)
    try:
        window.set_mask_analysis_status(text, color)
    except Exception:
        return

    app._display_f3_mask_status_snapshot = {
        "text": text,
        "color": color,
        "check_id": str((context or {}).get("check_id") or ""),
        "check_name": str((context or {}).get("check_name") or ""),
        "ready": bool(isinstance(analysis, dict) and analysis.get("ready")),
        "approved": (
            analysis.get("approved") if isinstance(analysis, dict) else None
        ),
        "matched_mask_count": int(
            (analysis or {}).get(
                "effective_matched_mask_count",
                (analysis or {}).get("matched_mask_count", 0),
            )
            or 0
        ) if isinstance(analysis, dict) else 0,
        "active_mask_count": int(
            (analysis or {}).get(
                "effective_active_mask_count",
                (analysis or {}).get("active_mask_count", 0),
            )
            or 0
        ) if isinstance(analysis, dict) else 0,
        "effective_failed_mask_ids": tuple(
            str(mask_id)
            for mask_id in (
                (analysis or {}).get("effective_failed_mask_ids") or ()
            )
            if str(mask_id)
        ) if isinstance(analysis, dict) else (),
    }


def _install_mask_status_runtime() -> None:
    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_mask_status_runtime_installed", False)):
        return

    original_process = cls._process_display_auto_check

    def process(self):
        result = original_process(self)
        try:
            _publish_mask_status(self)
        except Exception:
            # O status é diagnóstico; nunca pode interromper o ciclo F3.
            pass
        return result

    cls._process_display_auto_check = process
    cls._display_f3_mask_status_runtime_installed = True


_DISPLAY_F3_MASK_STATUS_INSTALLED = False


def instalar_status_mascaras_display_f3() -> None:
    """Adiciona o segundo status diagnóstico somente à Produção Display F3."""
    global _DISPLAY_F3_MASK_STATUS_INSTALLED
    if _DISPLAY_F3_MASK_STATUS_INSTALLED:
        return
    _install_mask_status_window()
    _install_mask_status_runtime()
    _DISPLAY_F3_MASK_STATUS_INSTALLED = True
