from __future__ import annotations

"""Tela leve para o DEBUG TÉCNICO do snapshot manual do Display F3.

O relatório completo continua disponível para suporte e para o clipboard, porém
não é inserido em um widget Text. Isso evita custo de layout/renderização de
milhares de linhas e mantém a janela consistente com os workspaces F3.

A análise visual de presença usa exatamente o mesmo frame congelado pelo botão
ANALISAR. Ela é anexada ao snapshot somente para diagnóstico e nunca participa
de OK/NG, avanço de CHECK, rearmamento ou qualquer decisão produtiva.
"""

import base64
import tkinter as tk

import cv2

from src.platform.display_f3_window_geometry import fit_f3_toplevel

import src.platform.display_f3_manual_snapshot_debug as manual_module
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
    "O debug técnico contém o snapshot congelado do frame analisado, a análise "
    "visual informativa da placa, dados da captura, estado físico, scores das "
    "referências, CHECK lógico, configuração das máscaras, comparação com os "
    "gabaritos, aprendizado ACESO/APAGADO e evidências de energia. O conteúdo "
    "completo não é renderizado nesta tela para evitar lentidão. Use COPIAR DEBUG "
    "para enviá-lo ao suporte."
)
COPY_START_DELAY_MS = 12
COPY_FEEDBACK_RESET_MS = 1800
READY_TEXT = "RELATÓRIO PRONTO PARA CÓPIA"
VISUAL_FRAME_MAX_WIDTH = 640
VISUAL_FRAME_MAX_HEIGHT = 340


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
        block = _visual_report_block(snapshot)
        if not block:
            return base
        marker = "\nCole este bloco inteiro na conversa/chamado de debug do Display F3."
        if marker in base:
            return base.replace(marker, f"\n\n{block}\n{marker}", 1)
        return f"{base}\n\n{block}"

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
    """Reduz a prévia em telas baixas para preservar a barra de ações."""
    screen_height = 768
    if widget is not None:
        try:
            screen_height = max(480, int(widget.winfo_screenheight()))
        except Exception:
            pass
    if screen_height <= 800:
        return 560, 250
    if screen_height <= 900:
        return 620, 300
    return VISUAL_FRAME_MAX_WIDTH, VISUAL_FRAME_MAX_HEIGHT


def _frame_photo(
    frame,
    visual: dict | None,
    widget=None,
    *,
    visual_rotation: int = 0,
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
    if roi is not None:
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
    try:
        window._display_f3_snapshot_debug_photo = None
    except Exception:
        pass
    window.close_f3_snapshot_debug()


def _open_lightweight_snapshot_debug(window):
    report = str(getattr(window, "_display_f3_manual_snapshot_report", "") or "")
    if not report:
        return None

    existing = getattr(window, "_display_f3_snapshot_debug_window", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass

    top = tk.Toplevel(window.root)
    fit_f3_toplevel(
        top,
        window.root,
        preferred_width=1080,
        preferred_height=700,
        min_width=760,
        min_height=520,
    )
    window._display_f3_snapshot_debug_window = top
    window._display_f3_snapshot_debug_text = None
    top.title("ODIN • DISPLAY F3 • DEBUG DO FRAME ANALISADO")
    top.configure(bg=manual_module.DEBUG_BG)

    # Uma única maximização, somente depois de toda a hierarquia estar criada.
    # Evita o antigo ciclo geometry -> paint -> geometry -> paint na abertura.
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

    # Cabeçalho fixo + corpo elástico + rodapé fixo.
    header = tk.Frame(shell, bg=manual_module.DEBUG_BG)
    header.grid(row=0, column=0, sticky="ew")
    tk.Label(
        header,
        text="DEBUG TÉCNICO • FRAME ANALISADO",
        font=("Segoe UI", 18, "bold"),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_TEXT,
        anchor="w",
    ).pack(fill="x")

    snapshot = getattr(window, "_display_f3_manual_snapshot", {}) or {}
    frame_id = (snapshot.get("capture") or {}).get("frame_id", "--")
    sha = (snapshot.get("frame") or {}).get("sha256_24", "--")
    capture_source = str((snapshot.get("capture") or {}).get("source") or "")
    source_text = (
        "EVIDÊNCIA NG CONGELADA • câmera ao vivo ignorada"
        if capture_source == "ng_evidence_frozen"
        else "conteúdo congelado no clique em ANALISAR"
    )
    tk.Label(
        header,
        text=f"Frame {frame_id} • hash {sha} • {source_text}",
        font=("Segoe UI", 10),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    body = tk.Frame(shell, bg=manual_module.DEBUG_BG)
    body.grid(
        row=1,
        column=0,
        sticky="nsew",
        pady=(14, 10),
    )
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(0, weight=1)

    visual = snapshot.get("visual_analysis")
    visual = visual if isinstance(visual, dict) else {}
    owner = getattr(window, "_display_f3_manual_debug_owner", None)
    frozen_frame = getattr(owner, "_display_f3_manual_snapshot_frozen_frame", None)

    visual_area = tk.Frame(body, bg=manual_module.DEBUG_BG)
    visual_area.grid(row=0, column=0, sticky="nsew")
    visual_area.grid_columnconfigure(0, weight=3)
    visual_area.grid_columnconfigure(1, weight=2, minsize=330)
    visual_area.grid_rowconfigure(0, weight=1)

    frame_column = tk.Frame(visual_area, bg=manual_module.DEBUG_BG)
    frame_column.grid(row=0, column=0, sticky="nsew", padx=(0, 22))
    preview_rotation = int(snapshot.get("rotation", 0) or 0)
    tk.Label(
        frame_column,
        text=(
            "FRAME CONGELADO • "
            f"VISUAL {preview_rotation}° • MESMA CÓPIA USADA NA ANÁLISE"
        ),
        font=("Segoe UI", 9, "bold"),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        anchor="w",
    ).pack(fill="x", pady=(0, 7))

    photo = _frame_photo(
        frozen_frame,
        visual,
        top,
        visual_rotation=preview_rotation,
    )
    window._display_f3_snapshot_debug_photo = photo
    if photo is not None:
        tk.Label(
            frame_column,
            image=photo,
            bg="#020617",
            bd=0,
            anchor="nw",
        ).pack(anchor="nw")
    else:
        tk.Label(
            frame_column,
            text="PRÉVIA DO FRAME NÃO DISPONÍVEL",
            font=("Segoe UI", 11, "bold"),
            bg=manual_module.DEBUG_BG,
            fg=manual_module.DEBUG_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(30, 0))

    info_column = tk.Frame(visual_area, bg=manual_module.DEBUG_BG)
    info_column.grid(row=0, column=1, sticky="nsew")
    tk.Label(
        info_column,
        text="ANÁLISE VISUAL • SOMENTE DIAGNÓSTICO",
        font=("Segoe UI", 10, "bold"),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        info_column,
        text=str(visual.get("status_text") or "ANÁLISE VISUAL: não disponível"),
        font=("Segoe UI", 13, "bold"),
        bg=manual_module.DEBUG_BG,
        fg=str(visual.get("status_color") or manual_module.DEBUG_TEXT),
        justify="left",
        anchor="w",
        wraplength=500,
    ).pack(fill="x", pady=(8, 10))
    tk.Label(
        info_column,
        text="Não altera OK/NG, CHECK, máscaras, avanço do fluxo ou rearmamento.",
        font=("Segoe UI", 9),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        justify="left",
        anchor="w",
        wraplength=500,
    ).pack(fill="x", pady=(0, 14))

    for line in (
        _candidate_line(visual, "empty_support", "PLACA FORA DO SUPORTE"),
        _candidate_line(visual, "board_off", "PLACA DESLIGADA NO SUPORTE"),
        (
            f"Margem entre referências: {_pct(visual.get('score_margin'))}  •  "
            f"mínima {_pct(visual.get('minimum_margin'))}"
        ),
    ):
        tk.Label(
            info_column,
            text=line,
            font=("Segoe UI", 9),
            bg=manual_module.DEBUG_BG,
            fg=manual_module.DEBUG_TEXT,
            justify="left",
            anchor="w",
            wraplength=500,
        ).pack(fill="x", pady=(0, 7))

    lower_info = tk.Frame(body, bg=manual_module.DEBUG_BG)
    lower_info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    lower_info.grid_columnconfigure(0, weight=1)

    message = tk.Label(
        lower_info,
        text=DEBUG_SUMMARY,
        font=("Segoe UI", 10),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        justify="left",
        anchor="nw",
        wraplength=1040,
    )
    message.pack(anchor="nw", fill="x", pady=(14, 0))

    def fit_message(event):
        try:
            message.configure(wraplength=max(420, int(event.width) - 8))
        except Exception:
            pass

    body.bind("<Configure>", fit_message, add="+")

    status = tk.Label(
        lower_info,
        text=READY_TEXT,
        font=("Segoe UI", 9, "bold"),
        bg=manual_module.DEBUG_BG,
        fg=manual_module.DEBUG_MUTED,
        anchor="w",
    )
    status.pack(anchor="w", pady=(12, 0))

    actions = tk.Frame(
        shell,
        bg=manual_module.DEBUG_PANEL,
        highlightbackground=manual_module.DEBUG_BORDER,
        highlightthickness=1,
    )
    actions.grid(
        row=2,
        column=0,
        sticky="ew",
        pady=(4, 0),
    )
    actions.grid_columnconfigure(0, weight=0)
    actions.grid_columnconfigure(1, weight=1)
    actions.grid_columnconfigure(2, weight=0)

    copy_button = tk.Button(
        actions,
        text="COPIAR DEBUG",
        font=("Segoe UI", 10, "bold"),
        bg=manual_module.DEBUG_ACTION,
        fg="#FFFFFF",
        activebackground=manual_module.DEBUG_ACTION_ACTIVE,
        activeforeground="#FFFFFF",
        disabledforeground="#CBD5E1",
        relief="flat",
        bd=0,
        padx=16,
        pady=8,
        cursor="hand2",
    )
    copy_button.configure(
        command=lambda: _schedule_copy_report(window, top, status, copy_button)
    )
    copy_button.grid(
        row=0,
        column=0,
        sticky="w",
        padx=(10, 6),
        pady=9,
    )

    tk.Button(
        actions,
        text="FECHAR",
        command=lambda: _close_debug(window),
        font=("Segoe UI", 10, "bold"),
        bg="#1E293B",
        fg=manual_module.DEBUG_TEXT,
        activebackground="#334155",
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        padx=16,
        pady=8,
        cursor="hand2",
    ).grid(
        row=0,
        column=2,
        sticky="e",
        padx=(6, 10),
        pady=9,
    )

    # Garante que o rodapé permaneça acima do conteúdo mesmo em resize manual.
    try:
        top.update_idletasks()
        actions.lift()
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
    DisplayProductionF3Window._display_f3_snapshot_debug_lightweight_ui = True
    _INSTALLED = True
