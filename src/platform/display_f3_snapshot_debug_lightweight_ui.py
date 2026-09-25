from __future__ import annotations

"""Tela leve do DEBUG TÉCNICO do Display F3.

A janela não reconstrói o frame analisado. Ela apresenta exclusivamente o print
dos pixels da tela PRODUÇÃO DISPLAY F3 capturado no clique em ANALISAR. O
relatório técnico completo é gerado em segundo plano sobre o frame bruto
congelado e fica disponível para COPIAR DEBUG.

A análise visual anexada ao relatório continua estritamente diagnóstica e nunca
participa de OK/NG, avanço de CHECK, rearmamento ou decisão produtiva.
"""

import base64
import io
import sys
import tkinter as tk

import cv2

from src.platform.display_f3_window_geometry import fit_f3_toplevel

import src.platform.display_f3_manual_snapshot_debug as manual_module
import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_visual_rotation import preparar_frame_visual_display
import src.platform.display_f3_operational_status as operational_module
import src.platform.display_visual_reference_status as visual_status_module
from src.platform.display_f3_workspace_ui import maximizar_janela_workspace_f3
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    DISPLAY_PROJECT_REFERENCE_LABELS,
    DISPLAY_PROJECT_REFERENCE_TYPES,
    DisplayVisualReferenceMatcher,
)


DEBUG_SUMMARY = (
    "Este é o print exato da tela PRODUÇÃO DISPLAY F3 no instante em que "
    "ANALISAR foi acionado. Abrir DEBUG TÉCNICO não executa nova visão "
    "computacional e não reconstrói overlay, visor ou status. O relatório de "
    "texto é gerado em segundo plano sobre o frame bruto congelado daquele "
    "mesmo clique e fica disponível em COPIAR DEBUG."
)
COPY_START_DELAY_MS = 12
COPY_FEEDBACK_RESET_MS = 1800
READY_TEXT = "RELATÓRIO PRONTO PARA CÓPIA"
VISUAL_FRAME_MAX_WIDTH = 640
VISUAL_FRAME_MAX_HEIGHT = 340

STATUS_TITLES = {
    "preview_status": "PREVIEW",
    "operational_reference_state_label": "ESTADO OPERACIONAL",
    "mask_analysis_state_label": "MÁSCARAS",
    "visual_analysis_state_label": "ANÁLISE VISUAL",
    "visual_reference_state_label": "REFERÊNCIA VISUAL",
    "board_reference_state_label": "PRESENÇA DA PLACA",
}


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value) -> str:
    number = _safe_float(value)
    return "--" if number is None else f"{number * 100.0:.1f}%"


def _visual_candidate(
    matcher: DisplayVisualReferenceMatcher,
    current_small,
    metadata: dict | None,
    kind: str,
) -> dict:
    configured = isinstance(metadata, dict)
    score = None
    threshold = None
    error = None
    if configured and current_small is not None:
        try:
            score = matcher._score(current_small, metadata)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        try:
            threshold = matcher._threshold(metadata)
        except Exception as exc:
            if error is None:
                error = f"{type(exc).__name__}: {exc}"

    score_float = _safe_float(score)
    threshold_float = _safe_float(threshold)
    matched = bool(
        score_float is not None
        and threshold_float is not None
        and score_float >= threshold_float
    )
    return {
        "kind": str(kind),
        "name": DISPLAY_PROJECT_REFERENCE_LABELS.get(str(kind), str(kind)),
        "configured": configured,
        "score": score_float,
        "threshold": threshold_float,
        "matched": matched,
        "margin_to_threshold": (
            None
            if score_float is None or threshold_float is None
            else round(score_float - threshold_float, 6)
        ),
        "roi": dict((metadata or {}).get("roi") or {})
        if isinstance((metadata or {}).get("roi"), dict)
        else None,
        "image_path": str((metadata or {}).get("image_path") or "")
        if configured
        else "",
        "error": error,
    }


def _build_visual_analysis_snapshot(app, frame, project_name: str) -> dict:
    """Reexecuta somente a leitura visual sobre a mesma cópia congelada."""
    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return {
            "available": False,
            "informational_only": True,
            "affects_result": False,
            "status_text": "ANÁLISE VISUAL: projeto indisponível",
            "reason": "repository_display_indisponivel",
        }

    matcher = DisplayVisualReferenceMatcher(repository)

    # A identidade por contorno + região do display é a leitura que realmente
    # diferencia H1/BLUE/USB/AUX. O comparador global EMPTY/OFF continua abaixo
    # apenas como diagnóstico de presença.
    contour_identity = None
    try:
        from src.platform.display_f3_contour_check_identity import (
            avaliar_identidade_visual_checks_por_contorno_f3,
        )
        contour_identity = avaliar_identidade_visual_checks_por_contorno_f3(
            app,
            frame,
        )
    except Exception as exc:
        contour_identity = {
            "available": False,
            "confirmed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if isinstance(contour_identity, dict) and contour_identity.get("confirmed"):
        name = str(
            contour_identity.get("best_check_name")
            or contour_identity.get("best_check_id")
            or "CHECK"
        ).strip().upper()
        score = float(contour_identity.get("best_score", 0.0) or 0.0)
        margin = float(contour_identity.get("margin", 0.0) or 0.0)
        status_state = {
            "text": (
                f"ANÁLISE VISUAL: DISPLAY EM {name} • "
                f"contorno {score * 100:.0f}% • margem {margin * 100:.0f}%"
            ),
            "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
        }
    else:
        try:
            status_state = operational_module._build_visual_analysis_state(
                app,
                frame,
                str(project_name),
            )
        except Exception as exc:
            status_state = {
                "text": "ANÁLISE VISUAL: falha no diagnóstico",
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["unavailable"],
                "error": f"{type(exc).__name__}: {exc}",
            }

    current_small = visual_status_module._small_image(frame)
    try:
        references = matcher.project_store.get_all(str(project_name))
    except Exception as exc:
        references = {}
        load_error = f"{type(exc).__name__}: {exc}"
    else:
        load_error = None

    empty = _visual_candidate(
        matcher,
        current_small,
        references.get(DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT),
        DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
    )
    off = _visual_candidate(
        matcher,
        current_small,
        references.get(DISPLAY_PROJECT_REFERENCE_BOARD_OFF),
        DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    )
    candidates = {
        "empty_support": empty,
        "board_off": off,
    }

    empty_score = _safe_float(empty.get("score"))
    off_score = _safe_float(off.get("score"))
    score_margin = (
        None
        if empty_score is None or off_score is None
        else abs(empty_score - off_score)
    )

    complete = all(bool(item.get("configured")) for item in candidates.values())
    empty_matched = bool(empty.get("matched"))
    off_matched = bool(off.get("matched"))
    selected_reference = None
    result_kind = "unidentified"

    if not complete:
        result_kind = "incomplete"
    elif current_small is None:
        result_kind = "camera_unavailable"
    elif empty_matched and off_matched:
        if (
            score_margin is not None
            and score_margin < operational_module.F3_OPERATIONAL_PHYSICAL_MARGIN
        ):
            result_kind = "ambiguous"
        elif (empty_score or 0.0) > (off_score or 0.0):
            result_kind = "empty_support"
            selected_reference = "empty_support"
        else:
            result_kind = "board_off"
            selected_reference = "board_off"
    elif empty_matched:
        result_kind = "empty_support"
        selected_reference = "empty_support"
    elif off_matched:
        result_kind = "board_off"
        selected_reference = "board_off"

    scored = [
        (key, _safe_float(value.get("score")))
        for key, value in candidates.items()
        if _safe_float(value.get("score")) is not None
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    best_reference = scored[0][0] if scored else None

    return {
        "available": bool(current_small is not None and complete),
        "informational_only": True,
        "affects_result": False,
        "uses_masks": False,
        "uses_check_state": False,
        "analysis_type": "project_visual_reference_comparison",
        "comparison_basis": "imagem_de_referencia_do_projeto_com_roi_quando_configurada",
        "status_text": str(status_state.get("text") or "ANÁLISE VISUAL: identificando..."),
        "status_color": str(status_state.get("color") or ""),
        "result_kind": result_kind,
        "selected_reference": selected_reference,
        "best_reference": best_reference,
        "score_margin": score_margin,
        "minimum_margin": operational_module.F3_OPERATIONAL_PHYSICAL_MARGIN,
        "project_references_complete": complete,
        "candidates": candidates,
        "load_error": load_error,
        "status_error": status_state.get("error"),
        "check_identity_by_contour": (
            dict(contour_identity)
            if isinstance(contour_identity, dict)
            else None
        ),
        "check_identity_authority": bool(
            isinstance(contour_identity, dict)
            and contour_identity.get("confirmed")
        ),
    }


def _visual_report_block(snapshot: dict) -> str:
    visual = snapshot.get("visual_analysis")
    if not isinstance(visual, dict):
        return ""

    lines = [
        "[ANÁLISE VISUAL INFORMATIVA - MESMO FRAME CONGELADO]",
        "Esta leitura usa somente as referências visuais do projeto e a ROI configurada.",
        "Ela NÃO participa de OK/NG, CHECK, máscaras, avanço de fluxo ou rearmamento.",
        f"status={visual.get('status_text', '--')}",
        " | ".join(
            (
                f"result_kind={visual.get('result_kind', '--')}",
                f"available={visual.get('available', '--')}",
                f"informational_only={visual.get('informational_only', '--')}",
                f"affects_result={visual.get('affects_result', '--')}",
                f"uses_masks={visual.get('uses_masks', '--')}",
                f"uses_check_state={visual.get('uses_check_state', '--')}",
            )
        ),
        " | ".join(
            (
                f"selected_reference={visual.get('selected_reference', '--')}",
                f"best_reference={visual.get('best_reference', '--')}",
                f"score_margin={manual_module._fmt(visual.get('score_margin'))}",
                f"minimum_margin={manual_module._fmt(visual.get('minimum_margin'))}",
                f"comparison={visual.get('comparison_basis', '--')}",
            )
        ),
    ]

    for key in ("empty_support", "board_off"):
        candidate = (visual.get("candidates") or {}).get(key)
        if not isinstance(candidate, dict):
            continue
        lines.append(
            "visual_reference "
            + " | ".join(
                (
                    f"key={key}",
                    f"name={candidate.get('name', '--')}",
                    f"configured={candidate.get('configured', '--')}",
                    f"matched={candidate.get('matched', '--')}",
                    f"score={manual_module._fmt(candidate.get('score'))}",
                    f"threshold={manual_module._fmt(candidate.get('threshold'))}",
                    f"margin_threshold={manual_module._fmt(candidate.get('margin_to_threshold'))}",
                    f"roi={candidate.get('roi', '--')}",
                    f"path={candidate.get('image_path', '--')}",
                    f"error={candidate.get('error', '--')}",
                )
            )
        )
    return "\n".join(lines)


def _install_visual_analysis_snapshot_extension() -> None:
    """Anexa a leitura visual ao snapshot sem capturar um segundo frame."""
    if bool(getattr(manual_module, "_display_f3_visual_analysis_debug_extended", False)):
        return

    original_freeze = manual_module._freeze_current_frame
    original_capture = manual_module.capturar_snapshot_debug_display_f3
    original_report = manual_module.montar_relatorio_snapshot_display_f3

    def freeze(app):
        frame, capture = original_freeze(app)
        try:
            app._display_f3_manual_snapshot_frozen_frame = frame
        except Exception:
            pass
        return frame, capture

    def capture(app):
        snapshot = original_capture(app)
        frame = getattr(app, "_display_f3_manual_snapshot_frozen_frame", None)
        project_name = str((snapshot or {}).get("project_name") or "")
        if frame is None or getattr(frame, "size", 0) == 0 or not project_name:
            return snapshot
        try:
            snapshot["visual_analysis"] = _build_visual_analysis_snapshot(
                app,
                frame,
                project_name,
            )
        except Exception as exc:
            snapshot["visual_analysis"] = {
                "available": False,
                "informational_only": True,
                "affects_result": False,
                "status_text": "ANÁLISE VISUAL: falha no diagnóstico",
                "error": f"{type(exc).__name__}: {exc}",
            }
        return snapshot

    def report(snapshot):
        base = original_report(snapshot)
        blocks = [
            block
            for block in (
                _visual_report_block(snapshot),
                _visual_state_report_block(snapshot),
            )
            if block
        ]
        if not blocks:
            return base
        extra = "\n\n".join(blocks)
        marker = "\nCole este bloco inteiro na conversa/chamado de debug do Display F3."
        if marker in base:
            return base.replace(marker, f"\n\n{extra}\n{marker}", 1)
        return f"{base}\n\n{extra}"

    manual_module._freeze_current_frame = freeze
    manual_module.capturar_snapshot_debug_display_f3 = capture
    manual_module.montar_relatorio_snapshot_display_f3 = report
    manual_module._display_f3_visual_analysis_debug_extended = True


def _normalized_roi(roi) -> dict | None:
    if not isinstance(roi, dict):
        return None
    try:
        x = max(0.0, min(1.0, float(roi.get("x", 0.0))))
        y = max(0.0, min(1.0, float(roi.get("y", 0.0))))
        width = max(0.0, min(1.0 - x, float(roi.get("width", roi.get("w", 0.0)))))
        height = max(0.0, min(1.0 - y, float(roi.get("height", roi.get("h", 0.0)))))
    except (TypeError, ValueError):
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}



def _debug_preview_limits(widget=None) -> tuple[int, int]:
    """Aproveita a área disponível para mostrar o print completo da tela F3."""
    screen_height = 768
    if widget is not None:
        try:
            screen_height = max(480, int(widget.winfo_screenheight()))
        except Exception:
            pass
    if screen_height <= 800:
        return 820, 410
    if screen_height <= 900:
        return 940, 470
    return 1060, 560


def _frame_photo(
    frame,
    visual: dict | None,
    widget=None,
    *,
    visual_rotation: int = 0,
    overlay_context: dict | None = None,
):
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    try:
        image = frame.copy()
    except Exception:
        return None

    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim != 3 or image.shape[2] != 3:
        return None

    data = visual if isinstance(visual, dict) else {}
    candidate_key = data.get("selected_reference") or data.get("best_reference")
    candidate = (data.get("candidates") or {}).get(candidate_key)
    roi = _normalized_roi((candidate or {}).get("roi"))
    if overlay_context is None and roi is not None:
        height, width = image.shape[:2]
        x1 = int(round(roi["x"] * width))
        y1 = int(round(roi["y"] * height))
        x2 = int(round((roi["x"] + roi["width"]) * width))
        y2 = int(round((roi["y"] + roi["height"]) * height))
        cv2.rectangle(
            image,
            (max(0, x1), max(0, y1)),
            (min(width - 1, x2), min(height - 1, y2)),
            (255, 255, 255),
            3,
        )

    # O snapshot é analisado sobre o frame bruto congelado, porém o operador
    # precisa enxergar exatamente a orientação visual do F3. Rotacionamos apenas
    # a cópia destinada à UI, depois de desenhar qualquer ROI no domínio bruto.
    image = preparar_frame_visual_display(image, int(visual_rotation or 0))
    if image is None or getattr(image, "size", 0) == 0:
        return None

    if isinstance(overlay_context, dict):
        try:
            image = overlay_module.renderizar_overlay_rois_display_f3(
                image,
                overlay_context,
            )
        except Exception:
            pass

    height, width = image.shape[:2]
    max_width, max_height = _debug_preview_limits(widget)
    scale = min(
        max_width / float(width),
        max_height / float(height),
        1.0,
    )
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    if (target_width, target_height) != (width, height):
        image = cv2.resize(
            image,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )

    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


def _snapshot_status_rows(visual_state: dict | None) -> list[tuple[str, dict]]:
    data = visual_state if isinstance(visual_state, dict) else {}
    rows = []

    main = data.get("main_status")
    if isinstance(main, dict):
        for key, title in (
            ("status", "STATUS PRINCIPAL"),
            ("detail", "DETALHE"),
        ):
            value = main.get(key)
            if isinstance(value, dict) and str(value.get("text") or "").strip():
                rows.append((title, value))

    statuses = data.get("statuses")
    if isinstance(statuses, dict):
        for key, title in STATUS_TITLES.items():
            value = statuses.get(key)
            if isinstance(value, dict) and str(value.get("text") or "").strip():
                rows.append((title, value))
    return rows


def _readout_color(state: str) -> tuple[str, str, str]:
    cls = DisplayProductionF3Window
    if state == "ng":
        return (
            cls.DISPLAY_READOUT_NG,
            cls.DISPLAY_READOUT_NG_OUTLINE,
            cls.DISPLAY_READOUT_NUMBER_NG,
        )
    if state == "on":
        return (
            cls.DISPLAY_READOUT_ACTIVE,
            "#86EFAC",
            cls.DISPLAY_READOUT_NUMBER,
        )
    if state == "off":
        return (
            cls.DISPLAY_READOUT_OFF,
            "#166534",
            cls.DISPLAY_READOUT_NUMBER,
        )
    return (
        cls.DISPLAY_READOUT_INACTIVE,
        cls.DISPLAY_READOUT_INACTIVE_OUTLINE,
        cls.DISPLAY_READOUT_NUMBER,
    )


def _draw_debug_readout(canvas, context: dict | None) -> bool:
    """Replica uma vez o visor 88:88 do snapshot; não cria timers."""
    if not isinstance(context, dict):
        canvas.create_text(
            210,
            48,
            text="VISOR SEM SNAPSHOT",
            fill=manual_module.DEBUG_MUTED,
            font=("DejaVu Sans", 9, "bold"),
        )
        return False

    slots = [
        str(mask_id)
        for mask_id in (context.get("mask_slots") or ())
        if str(mask_id)
    ]
    if len(slots) != 28 or len(set(slots)) != 28:
        slots = DisplayProductionF3Window._display_readout_mask_slots(
            context.get("mask_ids") or ()
        )
    if len(slots) != 28:
        canvas.create_text(
            210,
            48,
            text="VISOR SEM 28 MÁSCARAS NO SNAPSHOT",
            fill=manual_module.DEBUG_MUTED,
            font=("DejaVu Sans", 8, "bold"),
        )
        return False

    width = 420.0
    height = 96.0
    digit_height = 66.0
    digit_width = digit_height * 0.52
    digit_gap = 40.0
    colon_width = 22.0
    group_gap = 26.0
    total_width = (
        digit_width * 4.0
        + digit_gap * 2.0
        + group_gap * 2.0
        + colon_width
    )
    start_x = (width - total_width) / 2.0
    y = (height - digit_height) / 2.0

    energy_state = str(context.get("energy_state") or "").strip().lower()
    ready = bool(
        context.get("power_confirmed")
        and not bool(context.get("power_off_confirmed"))
        and energy_state != "off"
    )
    classifications = dict(context.get("classifications") or {})
    expected_states = dict(context.get("expected_states") or {})
    failed = {
        str(mask_id)
        for mask_id in (context.get("failed_mask_ids") or ())
        if str(mask_id)
    }

    def draw_digit(x, ids):
        thickness = max(5.0, min(digit_width, digit_height) * 0.105)
        polygons = DisplayProductionF3Window._seven_segment_points(
            x, y, digit_width, digit_height, thickness
        )
        for segment_name, mask_id in zip(
            ("a", "b", "c", "d", "e", "f", "g"),
            ids,
        ):
            state = DisplayProductionF3Window._display_readout_semantic_state(
                classifications.get(mask_id),
                expected_states.get(mask_id),
                mask_id in failed,
                ready=ready,
                intermittent=bool(context.get("intermittent", False)),
                has_any_on=bool(context.get("has_any_on")),
            )
            fill, outline, number_color = _readout_color(state)
            points = polygons[segment_name]
            if state == "ng":
                canvas.create_polygon(
                    points,
                    fill="",
                    outline=DisplayProductionF3Window.DISPLAY_READOUT_NG_OUTLINE,
                    width=3,
                )
            canvas.create_polygon(
                points,
                fill=fill,
                outline=outline,
                width=2 if state == "ng" else 1,
            )
            label = DisplayProductionF3Window._display_readout_mask_number(mask_id)
            if label:
                xs = points[0::2]
                ys = points[1::2]
                canvas.create_text(
                    sum(xs) / len(xs),
                    sum(ys) / len(ys),
                    text=label,
                    fill=number_color,
                    font=("DejaVu Sans", 5, "bold"),
                )

    x = start_x
    draw_digit(x, slots[0:7])
    x += digit_width + digit_gap
    draw_digit(x, slots[7:14])
    x += digit_width + group_gap

    colon_x = x + colon_width / 2.0
    for cy in (y + digit_height * 0.36, y + digit_height * 0.66):
        canvas.create_oval(
            colon_x - 2.5,
            cy - 2.5,
            colon_x + 2.5,
            cy + 2.5,
            fill=DisplayProductionF3Window.DISPLAY_READOUT_INACTIVE,
            outline=DisplayProductionF3Window.DISPLAY_READOUT_INACTIVE_OUTLINE,
        )

    x += colon_width + group_gap
    draw_digit(x, slots[14:21])
    x += digit_width + digit_gap
    draw_digit(x, slots[21:28])
    return True


def _visual_state_report_block(snapshot: dict) -> str:
    visual_state = snapshot.get("visual_state")
    if not isinstance(visual_state, dict):
        return ""

    lines = ["[ESTADO VISUAL CONGELADO - MESMO FRAME]"]
    lines.append(
        f"frozen_ng={visual_state.get('frozen_ng', False)}"
    )
    for title, value in _snapshot_status_rows(visual_state):
        lines.append(
            f"status {title} | text={value.get('text', '--')} | "
            f"fg={value.get('fg', '--')} | bg={value.get('bg', '--')}"
        )

    readout = visual_state.get("readout_context")
    if isinstance(readout, dict):
        lines.append(
            "visor | "
            f"power_confirmed={readout.get('power_confirmed')} | "
            f"power_off_confirmed={readout.get('power_off_confirmed')} | "
            f"energy={readout.get('energy_state')} | "
            f"failed={sorted(readout.get('failed_mask_ids') or ())}"
        )
        lines.append(
            f"visor_classifications={readout.get('classifications', {})}"
        )
        lines.append(
            f"visor_expected={readout.get('expected_states', {})}"
        )

    overlay = snapshot.get("overlay_context")
    if isinstance(overlay, dict):
        lines.append(
            "overlay_camera | "
            f"check_id={overlay.get('check_id', '--')} | "
            f"rotation={overlay.get('visual_rotation', '--')} | "
            f"classifications={overlay.get('classifications', {})}"
        )

    camera = snapshot.get("camera_settings_at_frame")
    if isinstance(camera, dict):
        lines.append(f"camera_backend={camera.get('backend', '--')}")
        configured = camera.get("configured")
        hardware = camera.get("hardware_values")
        statuses = camera.get("control_status")
        for key in ("focus", "exposure", "gain", "white_balance"):
            configured_value = (
                configured.get(key)
                if isinstance(configured, dict)
                else None
            )
            hardware_value = (
                hardware.get(key)
                if isinstance(hardware, dict)
                else None
            )
            control_value = (
                statuses.get(key)
                if isinstance(statuses, dict)
                else None
            )
            lines.append(
                f"camera_{key} | configured={configured_value} | "
                f"hardware={hardware_value} | status={control_value}"
            )
    return "\n".join(lines)


def _candidate_line(visual: dict, key: str, fallback: str) -> str:
    candidate = (visual.get("candidates") or {}).get(key)
    if not isinstance(candidate, dict):
        return f"{fallback}: --"
    roi_text = "ROI ATIVA" if candidate.get("roi") else "IMAGEM TODA"
    return (
        f"{fallback}: {_pct(candidate.get('score'))}  •  "
        f"limiar {_pct(candidate.get('threshold'))}  •  {roi_text}"
    )


def _set_copy_feedback(
    status_label=None,
    copy_button=None,
    *,
    status_text: str,
    button_text: str,
    enabled: bool,
) -> None:
    if status_label is not None:
        try:
            status_label.configure(text=status_text)
        except Exception:
            pass
    if copy_button is not None:
        try:
            copy_button.configure(
                text=button_text,
                state=(tk.NORMAL if enabled else tk.DISABLED),
            )
        except Exception:
            pass


def _restore_copy_feedback(status_label=None, copy_button=None) -> None:
    _set_copy_feedback(
        status_label,
        copy_button,
        status_text=READY_TEXT,
        button_text="COPIAR DEBUG",
        enabled=True,
    )


def _copy_report(window, top, status_label=None, copy_button=None) -> bool:
    """Copia diretamente para o clipboard sem forçar processamento síncrono da UI."""
    report = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
    if not report:
        _set_copy_feedback(
            status_label,
            copy_button,
            status_text="SEM DEBUG DISPONÍVEL PARA COPIAR",
            button_text="TENTAR NOVAMENTE",
            enabled=True,
        )
        return False

    try:
        top.clipboard_clear()
        top.clipboard_append(report)
        _set_copy_feedback(
            status_label,
            copy_button,
            status_text="DEBUG COPIADO COM SUCESSO",
            button_text="COPIADO",
            enabled=False,
        )
        return True
    except Exception:
        _set_copy_feedback(
            status_label,
            copy_button,
            status_text="NÃO FOI POSSÍVEL COPIAR O DEBUG",
            button_text="TENTAR NOVAMENTE",
            enabled=True,
        )
        return False


def _schedule_copy_report(window, top, status_label=None, copy_button=None) -> bool:
    """Entrega um paint ao Tk antes de copiar o relatório grande para o clipboard."""
    report = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
    if not report:
        _set_copy_feedback(
            status_label,
            copy_button,
            status_text="SEM DEBUG DISPONÍVEL PARA COPIAR",
            button_text="TENTAR NOVAMENTE",
            enabled=True,
        )
        return False

    _set_copy_feedback(
        status_label,
        copy_button,
        status_text="COPIANDO DEBUG...",
        button_text="COPIANDO...",
        enabled=False,
    )

    def do_copy() -> None:
        copied = _copy_report(window, top, status_label, copy_button)
        if not copied:
            return
        try:
            top.after(
                COPY_FEEDBACK_RESET_MS,
                lambda: _restore_copy_feedback(status_label, copy_button),
            )
        except Exception:
            pass

    try:
        top.after(COPY_START_DELAY_MS, do_copy)
    except Exception:
        do_copy()
    return True



def _close_debug(window) -> None:
    for attribute in (
        "_display_f3_snapshot_debug_photo",
        "_display_f3_snapshot_debug_status_label",
        "_display_f3_snapshot_debug_copy_button",
        "_display_f3_snapshot_debug_copy_image_button",
    ):
        try:
            setattr(window, attribute, None)
        except Exception:
            pass
    window.close_f3_snapshot_debug()


def _screen_capture_photo(window, widget=None):
    """Converte somente o print já capturado para PhotoImage de apresentação."""
    image = getattr(window, "_display_f3_manual_screen_capture_image", None)
    if image is None:
        return None
    try:
        preview = image.copy()
        max_width, max_height = _debug_preview_limits(widget)
        preview.thumbnail((max_width, max_height))
        buffer = io.BytesIO()
        preview.save(buffer, format="PNG")
        return tk.PhotoImage(data=base64.b64encode(buffer.getvalue()).decode("ascii"))
    except Exception:
        return None


def _screen_capture_png_bytes(window) -> bytes:
    image = getattr(window, "_display_f3_manual_screen_capture_image", None)
    if image is None:
        return b""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _copy_screen_image_windows(image) -> bool:
    """Publica CF_DIB no Windows para Ctrl+V em aplicativos como WhatsApp."""
    import ctypes
    from ctypes import wintypes

    bmp = io.BytesIO()
    image.convert("RGB").save(bmp, format="BMP")
    dib = bmp.getvalue()[14:]
    if not dib:
        return False

    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return False
    try:
        ctypes.memmove(pointer, dib, len(dib))
    finally:
        kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    transferred = False
    try:
        if not user32.EmptyClipboard():
            return False
        if not user32.SetClipboardData(CF_DIB, handle):
            return False
        transferred = True
        return True
    finally:
        user32.CloseClipboard()
        if not transferred:
            kernel32.GlobalFree(handle)


def _copy_screen_image_to_clipboard(window, top) -> bool:
    """Copia imagem nativa, nunca texto/base64, para o clipboard do SO."""
    image = getattr(window, "_display_f3_manual_screen_capture_image", None)
    if image is None:
        return False
    try:
        if sys.platform.startswith("win"):
            return _copy_screen_image_windows(image)
        png = _screen_capture_png_bytes(window)
        if not png:
            return False
        top.clipboard_clear()
        top.tk.call("clipboard", "append", "-type", "image/png", "--", png)
        return True
    except Exception:
        return False


def _schedule_copy_image(window, top, status_label=None, copy_button=None) -> bool:
    image = getattr(window, "_display_f3_manual_screen_capture_image", None)
    if image is None:
        _set_copy_feedback(
            status_label, copy_button,
            status_text="PRINT DA TELA NÃO DISPONÍVEL",
            button_text="COPIAR IMAGEM", enabled=False,
        )
        return False

    _set_copy_feedback(
        status_label, copy_button,
        status_text="COPIANDO IMAGEM...",
        button_text="COPIANDO...", enabled=False,
    )

    def do_copy() -> None:
        copied = _copy_screen_image_to_clipboard(window, top)
        if copied:
            _set_copy_feedback(
                status_label, copy_button,
                status_text="IMAGEM COPIADA • USE CTRL+V",
                button_text="COPIADO", enabled=False,
            )
        else:
            _set_copy_feedback(
                status_label, copy_button,
                status_text="NÃO FOI POSSÍVEL COPIAR A IMAGEM",
                button_text="TENTAR NOVAMENTE", enabled=True,
            )
            return
        try:
            top.after(
                COPY_FEEDBACK_RESET_MS,
                lambda: _restore_image_copy_feedback(window, status_label, copy_button),
            )
        except Exception:
            pass

    try:
        top.after(COPY_START_DELAY_MS, do_copy)
    except Exception:
        do_copy()
    return True


def _restore_image_copy_feedback(window, status_label, copy_button) -> None:
    available = getattr(window, "_display_f3_manual_screen_capture_image", None) is not None
    _set_copy_feedback(
        status_label, copy_button,
        status_text="PRINT PRONTO PARA CÓPIA" if available else "PRINT INDISPONÍVEL",
        button_text="COPIAR IMAGEM", enabled=available,
    )


def _refresh_lightweight_debug_state(window) -> None:
    """Atualiza apenas disponibilidade dos botões; não recalcula diagnóstico."""
    report = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
    running = bool(getattr(window, "_display_f3_debug_analysis_running", False))
    image_available = getattr(window, "_display_f3_manual_screen_capture_image", None) is not None
    status = getattr(window, "_display_f3_snapshot_debug_status_label", None)
    copy_debug = getattr(window, "_display_f3_snapshot_debug_copy_button", None)
    copy_image = getattr(window, "_display_f3_snapshot_debug_copy_image_button", None)

    status_text = READY_TEXT if report else (
        "GERANDO RELATÓRIO TÉCNICO..." if running
        else "RELATÓRIO TÉCNICO NÃO DISPONÍVEL"
    )
    if status is not None:
        try:
            status.configure(text=status_text)
        except Exception:
            pass
    if copy_debug is not None:
        try:
            copy_debug.configure(
                state=tk.NORMAL if bool(report) else tk.DISABLED,
                cursor="hand2" if bool(report) else "arrow",
            )
        except Exception:
            pass
    if copy_image is not None:
        try:
            copy_image.configure(
                state=tk.NORMAL if image_available else tk.DISABLED,
                cursor="hand2" if image_available else "arrow",
            )
        except Exception:
            pass


def _open_lightweight_snapshot_debug(window):
    """Abre somente a evidência visual já capturada; não executa análise."""
    screen_meta = getattr(window, "_display_f3_manual_screen_capture_meta", {})
    serial = int(getattr(window, "_display_f3_manual_snapshot_serial", 0) or 0)
    if serial <= 0 and not bool(
        isinstance(screen_meta, dict) and screen_meta.get("available")
    ):
        return None

    existing = getattr(window, "_display_f3_snapshot_debug_window", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                _refresh_lightweight_debug_state(window)
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass

    top = tk.Toplevel(window.root)
    fit_f3_toplevel(
        top, window.root,
        preferred_width=1120, preferred_height=760,
        min_width=760, min_height=520,
    )
    window._display_f3_snapshot_debug_window = top
    window._display_f3_snapshot_debug_text = None
    top.title("ODIN • DISPLAY F3 • DEBUG DO PRINT ANALISADO")
    top.configure(bg=manual_module.DEBUG_BG)
    try:
        top.after_idle(lambda current=top: maximizar_janela_workspace_f3(current))
    except Exception:
        pass

    shell = tk.Frame(top, bg=manual_module.DEBUG_BG)
    shell.pack(fill="both", expand=True, padx=24, pady=(18, 16))
    shell.grid_columnconfigure(0, weight=1)
    shell.grid_rowconfigure(0, weight=0)
    shell.grid_rowconfigure(1, weight=1)
    shell.grid_rowconfigure(2, weight=0)

    header = tk.Frame(shell, bg=manual_module.DEBUG_BG)
    header.grid(row=0, column=0, sticky="ew")
    tk.Label(
        header, text="DEBUG TÉCNICO • PRINT DA TELA ANALISADA",
        font=("Segoe UI", 18, "bold"), bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_TEXT, anchor="w",
    ).pack(fill="x")

    snapshot = getattr(window, "_display_f3_manual_snapshot", {}) or {}
    frame_id = (snapshot.get("capture") or {}).get("frame_id", "--")
    captured_at = screen_meta.get("captured_at", "--") if isinstance(screen_meta, dict) else "--"
    tk.Label(
        header,
        text=(
            f"Frame {frame_id} • print capturado em {captured_at} • "
            "nenhuma reconstrução é executada ao abrir esta janela"
        ),
        font=("Segoe UI", 10), bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED, anchor="w",
    ).pack(fill="x", pady=(4, 0))

    body = tk.Frame(shell, bg=manual_module.DEBUG_BG)
    body.grid(row=1, column=0, sticky="nsew", pady=(14, 10))
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(0, weight=1)

    preview_label = tk.Label(
        body, text="CARREGANDO PRINT CAPTURADO...",
        font=("Segoe UI", 10, "bold"), bg="#020617",
        fg=manual_module.DEBUG_MUTED, bd=0, anchor="center",
        padx=12, pady=18,
    )
    preview_label.grid(row=0, column=0, sticky="nsew")
    window._display_f3_snapshot_debug_photo = None

    def render_captured_screen():
        photo = _screen_capture_photo(window, top)
        window._display_f3_snapshot_debug_photo = photo
        try:
            if photo is not None:
                preview_label.configure(image=photo, text="")
            else:
                reason = (
                    (screen_meta.get("error") or screen_meta.get("reason") or "captura indisponível")
                    if isinstance(screen_meta, dict)
                    else "captura indisponível"
                )
                preview_label.configure(
                    image="", text=f"PRINT DA TELA NÃO DISPONÍVEL\n{reason}"
                )
        except Exception:
            pass
    try:
        top.after(18, render_captured_screen)
    except Exception:
        render_captured_screen()

    message = tk.Label(
        body, text=DEBUG_SUMMARY, font=("Segoe UI", 10),
        bg=manual_module.DEBUG_BG, fg=manual_module.DEBUG_MUTED,
        justify="left", anchor="nw", wraplength=1060,
    )
    message.grid(row=1, column=0, sticky="ew", pady=(12, 0))
    def fit_message(event):
        try:
            message.configure(wraplength=max(420, int(event.width) - 8))
        except Exception:
            pass
    body.bind("<Configure>", fit_message, add="+")

    status = tk.Label(
        body, text="GERANDO RELATÓRIO TÉCNICO...",
        font=("Segoe UI", 9, "bold"), bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED, anchor="w",
    )
    status.grid(row=2, column=0, sticky="ew", pady=(10, 0))
    window._display_f3_snapshot_debug_status_label = status

    actions = tk.Frame(
        shell, bg=manual_module.DEBUG_PANEL,
        highlightbackground=manual_module.DEBUG_BORDER, highlightthickness=1,
    )
    actions.grid(row=2, column=0, sticky="ew", pady=(4, 0))
    actions.grid_columnconfigure(0, weight=0)
    actions.grid_columnconfigure(1, weight=0)
    actions.grid_columnconfigure(2, weight=1)
    actions.grid_columnconfigure(3, weight=0)

    copy_debug_button = tk.Button(
        actions, text="COPIAR DEBUG",
        command=lambda: _schedule_copy_report(window, top, status, copy_debug_button),
        font=("Segoe UI", 10, "bold"), bg=manual_module.DEBUG_ACTION,
        fg="#FFFFFF", activebackground=manual_module.DEBUG_ACTION_ACTIVE,
        activeforeground="#FFFFFF", disabledforeground="#64748B",
        relief="flat", bd=0, padx=16, pady=8, cursor="arrow", state=tk.DISABLED,
    )
    copy_debug_button.grid(row=0, column=0, sticky="w", padx=(10, 6), pady=9)
    window._display_f3_snapshot_debug_copy_button = copy_debug_button

    copy_image_button = tk.Button(
        actions, text="COPIAR IMAGEM",
        command=lambda: _schedule_copy_image(window, top, status, copy_image_button),
        font=("Segoe UI", 10, "bold"), bg="#1D4ED8", fg="#FFFFFF",
        activebackground="#2563EB", activeforeground="#FFFFFF",
        disabledforeground="#64748B", relief="flat", bd=0,
        padx=16, pady=8, cursor="hand2",
    )
    copy_image_button.grid(row=0, column=1, sticky="w", padx=6, pady=9)
    window._display_f3_snapshot_debug_copy_image_button = copy_image_button

    tk.Button(
        actions, text="FECHAR", command=lambda: _close_debug(window),
        font=("Segoe UI", 10, "bold"), bg="#1E293B",
        fg=manual_module.DEBUG_TEXT, activebackground="#334155",
        activeforeground="#FFFFFF", relief="flat", bd=0,
        padx=16, pady=8, cursor="hand2",
    ).grid(row=0, column=3, sticky="e", padx=(6, 10), pady=9)

    _refresh_lightweight_debug_state(window)
    try:
        top.after_idle(actions.lift)
    except Exception:
        pass
    top.protocol("WM_DELETE_WINDOW", lambda: _close_debug(window))
    top.bind("<Escape>", lambda _event: _close_debug(window))
    return top

_INSTALLED = False


def instalar_debug_snapshot_leve_display_f3() -> None:
    """Substitui apresentação do snapshot e anexa análise visual informativa."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_visual_analysis_snapshot_extension()
    DisplayProductionF3Window.open_f3_snapshot_debug = (
        lambda self: _open_lightweight_snapshot_debug(self)
    )
    DisplayProductionF3Window.refresh_f3_snapshot_debug_state = (
        lambda self: _refresh_lightweight_debug_state(self)
    )
    DisplayProductionF3Window._display_f3_snapshot_debug_lightweight_ui = True
    _INSTALLED = True
