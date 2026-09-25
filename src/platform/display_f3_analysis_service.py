from __future__ import annotations

"""Análise manual leve do CHECK atual do Display F3.

Este módulo é deliberadamente puro em relação à interface e ao ciclo produtivo:
recebe um snapshot congelado, analisa somente o CHECK capturado e devolve dados.
Não registra OK/NG, não avança CHECK, não rearma placa e não toca em widgets.
"""

from copy import deepcopy

from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)


F3_MANUAL_CURRENT_CHECK_SOURCE = "f3_manual_current_check_analysis"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _frame_identity(frame) -> dict:
    if not _valid_frame(frame):
        return {"available": False}
    shape = getattr(frame, "shape", ())
    return {
        "available": True,
        "shape": [int(value) for value in shape],
        "dtype": str(getattr(frame, "dtype", "")),
    }


def _analysis_matches_context(analysis: dict | None, context: dict) -> bool:
    if not isinstance(analysis, dict):
        return False
    return (
        str(analysis.get("project_name") or "")
        == str(context.get("project_name") or "")
        and str(analysis.get("check_id") or "")
        == str(context.get("check_id") or "")
    )


class DisplayF3CurrentCheckAnalysisService:
    """Executa somente a classificação semântica do CHECK congelado."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def analyze(self, request: dict) -> dict:
        frame = request.get("frame")
        capture = deepcopy(request.get("capture") or {})
        context = deepcopy(request.get("logical_context") or {})
        snapshot = {
            "source": F3_MANUAL_CURRENT_CHECK_SOURCE,
            "captured_at": str(request.get("captured_at") or ""),
            "capture": capture,
            "rotation": int(request.get("rotation", 0) or 0),
            "logical_context": context,
            "frame": _frame_identity(frame),
            "project_name": str(context.get("project_name") or ""),
            "check_id": str(context.get("check_id") or ""),
            "check_name": str(context.get("check_name") or ""),
            "current_check_only": True,
            "debug_complete": False,
            "report_ready": False,
            "errors": [],
        }
        if not _valid_frame(frame):
            snapshot["errors"].append(
                str(capture.get("reason") or "camera_sem_frame")
            )
            snapshot["analysis_ready"] = False
            return snapshot

        project_name = snapshot["project_name"]
        check_id = snapshot["check_id"]
        if not project_name or not check_id:
            snapshot["errors"].append("contexto_check_atual_indisponivel")
            snapshot["analysis_ready"] = False
            return snapshot

        # Em NG terminal a análise produtiva já pertence exatamente ao frame
        # congelado. Reutilizá-la evita recalcular as mesmas máscaras.
        frozen_production = request.get("frozen_production_analysis")
        if _analysis_matches_context(frozen_production, context):
            analysis = deepcopy(frozen_production)
            snapshot["analysis_source"] = "frozen_production_analysis"
        else:
            analyzer = F3SameMaskReferenceAnalyzer(self.repository)
            tracking = request.get("tracking_geometry")
            tracking = tracking if isinstance(tracking, dict) else {}
            kwargs = {}
            if bool(tracking.get("locked")) and tracking.get("masks"):
                kwargs = {
                    "mask_geometry_override": deepcopy(
                        tracking.get("masks") or []
                    ),
                    "mask_geometry_resolution": deepcopy(
                        tracking.get("resolution")
                    ),
                    "mask_geometry_source": str(
                        tracking.get("geometry_space")
                        or "manual_snapshot_tracking"
                    ),
                }
            analysis = analyzer.analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=int(snapshot["rotation"]),
                **kwargs,
            )
            snapshot["analysis_source"] = (
                "same_mask_current_check_with_tracking"
                if kwargs
                else "same_mask_current_check"
            )

        snapshot["frozen_frame_analysis"] = deepcopy(analysis)
        snapshot["analysis_ready"] = bool(
            isinstance(analysis, dict) and analysis.get("ready")
        )
        snapshot["approved"] = (
            analysis.get("approved")
            if isinstance(analysis, dict)
            else None
        )
        snapshot["reason"] = (
            str(analysis.get("reason") or "")
            if isinstance(analysis, dict)
            else "analise_indisponivel"
        )
        return snapshot
