from __future__ import annotations

import tkinter as tk

import cv2
import numpy as np

from src.core.roi_geometry import (
    TIPO_ROI_SEGMENTO,
    bbox_roi,
    normalizar_tipo_roi,
    pontos_segmento,
)
from src.platform.blue_operation_window import BlueRaspberryOperationWindow


F2_LIVE_ROI_OVERLAY_ALPHA = 0.14
F2_LIVE_ROI_COLORS_BGR = {
    "ACESO": (94, 197, 34),
    "APAGADO": (68, 68, 239),
    "POUCA_LUZ": (21, 204, 250),
    "POUCA LUZ": (21, 204, 250),
    "UNKNOWN": (184, 163, 148),
}
F2_LIVE_ROI_LEGEND = (
    "VERDE: ACESO  •  VERMELHO: APAGADO  •  AMARELO: POUCA LUZ"
)

F2_ANALYZED_WAITING_TEXT = "PLACA JÁ ANALISADA\nCOLOQUE OUTRA PLACA"
F2_ANALYZED_WAITING_FONT_MAX = 28
F2_ANALYZED_WAITING_FONT_MIN = 14

F2_RESULT_PREVIEW_SHARE = 0.42
F2_RESULT_PREVIEW_RESIZE_DEBOUNCE_MS = 80
F2_RESULT_PREVIEW_MIN_WIDTH = 150
F2_RESULT_PREVIEW_MIN_HEIGHT = 110

F2_BOARD_STATUS_UI = {
    "board_on": ("PLACA PRESENTE — LIGADA", "#86EFAC"),
    "board_off": ("PLACA PRESENTE — DESLIGADA", "#FBBF24"),
    "empty_support": ("PLACA AUSENTE", "#94A3B8"),
    "unknown": ("IDENTIFICANDO...", "#CBD5E1"),
    "unavailable": ("REFERÊNCIAS DE PRESENÇA NÃO CONFIGURADAS", "#FBBF24"),
    "analyzed_ok": ("JÁ ANALISADA — RESULTADO: OK", "#86EFAC"),
    "analyzed_ng": ("JÁ ANALISADA — RESULTADO: NG", "#FCA5A5"),
}


def tamanho_fonte_status_analisado_f2(panel_width: int) -> int:
    """Dimensiona o aviso em duas linhas para não cortar em telas estreitas."""
    try:
        width = int(panel_width)
    except (TypeError, ValueError):
        width = 640

    usable_width = max(160, max(220, width) - 72)
    longest_line = max(len(line) for line in F2_ANALYZED_WAITING_TEXT.splitlines())
    # Aproxima a largura de texto em DejaVu Sans Bold de forma conservadora.
    estimated = int(usable_width / max(1.0, longest_line * 0.90))
    return max(
        F2_ANALYZED_WAITING_FONT_MIN,
        min(F2_ANALYZED_WAITING_FONT_MAX, estimated),
    )


def largura_texto_com_preview_resultado_f2(panel_width: int) -> int:
    """Reserva espaço para o snapshot sem comprimir o texto de resultado."""
    try:
        width = max(320, int(panel_width))
    except (TypeError, ValueError):
        width = 640
    text_share = max(0.50, 1.0 - F2_RESULT_PREVIEW_SHARE)
    return max(220, int(round(width * text_share)) - 28)


def renderizar_overlay_rois_f2(frame, leds, states: dict[str, str] | None):
    """Desenha uma cópia translúcida das ROIs sem alterar o frame da câmera."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame

    result = frame.copy()
    tint = result.copy()
    outlines: list[tuple[str, object, tuple[int, int, int]]] = []
    state_map = {
        str(key): str(value).strip().upper()
        for key, value in dict(states or {}).items()
    }

    for led in tuple(leds or ()):
        led_id = str(getattr(led, "id", ""))
        status = state_map.get(led_id, "UNKNOWN")
        color = F2_LIVE_ROI_COLORS_BGR.get(
            status,
            F2_LIVE_ROI_COLORS_BGR["UNKNOWN"],
        )
        tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))

        if tipo == TIPO_ROI_SEGMENTO:
            points = np.asarray(
                [(int(round(x)), int(round(y))) for x, y in pontos_segmento(led)],
                dtype=np.int32,
            )
            if len(points) < 3:
                continue
            polygon = points.reshape((-1, 1, 2))
            cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)
            outlines.append(("segment", polygon, color))
        else:
            center = (
                int(getattr(led, "centro_x", 0)),
                int(getattr(led, "centro_y", 0)),
            )
            radius = max(2, int(getattr(led, "raio", 2)))
            cv2.circle(tint, center, radius, color, -1, cv2.LINE_AA)
            outlines.append(("circle", (center, radius), color))

    cv2.addWeighted(
        tint,
        F2_LIVE_ROI_OVERLAY_ALPHA,
        result,
        1.0 - F2_LIVE_ROI_OVERLAY_ALPHA,
        0.0,
        dst=result,
    )

    for kind, geometry, color in outlines:
        if kind == "segment":
            cv2.polylines(
                result,
                [geometry],
                True,
                color,
                2,
                cv2.LINE_AA,
            )
        else:
            center, radius = geometry
            cv2.circle(result, center, radius, color, 2, cv2.LINE_AA)

    return result


class SegmentDisplayOperationWindow(BlueRaspberryOperationWindow):
    """Prévia F2 capaz de desenhar simultaneamente círculos e segmentos."""

    def __init__(self, *args, **kwargs) -> None:
        self._live_roi_states: dict[str, str] = {}
        self._live_roi_overlay_enabled = False
        self._board_presence_status = "unknown"
        self._f2_analyzed_waiting_active = False
        self._result_snapshot_bgr = None
        self._result_snapshot_tk = None
        self._result_snapshot_resize_after_id = None
        self._result_snapshot_visible = False
        self._result_snapshot_is_ok: bool | None = None
        super().__init__(*args, **kwargs)
        try:
            self.preview_legend.configure(text="AZUL: ROI APAGADA")
        except Exception:
            pass

        self.board_presence_label = tk.Label(
            self.preview_header,
            text="STATUS DA PLACA: IDENTIFICANDO...",
            font=("DejaVu Sans", 10, "bold"),
            bg=self.PREVIEW_PANEL,
            fg="#CBD5E1",
            anchor="w",
            justify="left",
        )
        self.board_presence_label.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 0),
        )
        self.board_presence_label.grid_remove()

        self._instalar_preview_frame_resultado_f2()

    def _instalar_preview_frame_resultado_f2(self) -> None:
        """Adiciona o último frame analisado à esquerda do resultado do F2."""
        self.result_snapshot_panel = tk.Frame(
            self.status_frame,
            bg="#08111F",
            highlightbackground="#475569",
            highlightthickness=1,
        )
        self.result_snapshot_panel.grid_rowconfigure(1, weight=1)
        self.result_snapshot_panel.grid_columnconfigure(0, weight=1)

        header = tk.Frame(
            self.result_snapshot_panel,
            bg="#08111F",
            highlightthickness=0,
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=9,
            pady=(7, 5),
        )
        header.grid_columnconfigure(0, weight=1)

        self.result_snapshot_title = tk.Label(
            header,
            text="FRAME ANALISADO",
            font=("DejaVu Sans", 9, "bold"),
            bg="#08111F",
            fg="#CBD5E1",
            anchor="w",
            justify="left",
        )
        self.result_snapshot_title.grid(row=0, column=0, sticky="w")

        self.result_snapshot_result = tk.Label(
            header,
            text="",
            font=("DejaVu Sans", 9, "bold"),
            bg="#08111F",
            fg="#FFFFFF",
            anchor="e",
            justify="right",
        )
        self.result_snapshot_result.grid(row=0, column=1, sticky="e")

        self.result_snapshot_canvas = tk.Canvas(
            self.result_snapshot_panel,
            bg=self.PREVIEW_BACKGROUND,
            highlightbackground="#1E293B",
            highlightthickness=1,
            bd=0,
            width=F2_RESULT_PREVIEW_MIN_WIDTH,
            height=F2_RESULT_PREVIEW_MIN_HEIGHT,
        )
        self.result_snapshot_canvas.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=8,
            pady=(0, 8),
        )
        self.result_snapshot_canvas.bind(
            "<Configure>",
            self._on_result_snapshot_resize,
        )
        self.result_snapshot_panel.grid_remove()

    def _set_result_snapshot_layout(self, visible: bool) -> None:
        """Usa somente o espaço do resultado; a câmera ao vivo permanece intacta."""
        self._result_snapshot_visible = bool(visible)
        if visible:
            self.status_frame.grid_columnconfigure(
                0,
                weight=42,
                uniform="f2_result_content",
            )
            self.status_frame.grid_columnconfigure(
                1,
                weight=58,
                uniform="f2_result_content",
            )
            self.result_snapshot_panel.grid(
                row=0,
                column=0,
                rowspan=2,
                sticky="nsew",
                padx=(0, 12),
                pady=4,
            )
            self.status_label.grid_configure(
                row=0,
                column=1,
                sticky="nsew",
                padx=8,
            )
            self.detail_label.grid_configure(
                row=1,
                column=1,
                sticky="ew",
                padx=12,
                pady=(0, 8),
            )
        else:
            self.result_snapshot_panel.grid_remove()
            self.status_frame.grid_columnconfigure(
                0,
                weight=1,
                uniform="",
            )
            self.status_frame.grid_columnconfigure(
                1,
                weight=0,
                uniform="",
            )
            self.status_label.grid_configure(
                row=0,
                column=0,
                sticky="nsew",
                padx=8,
            )
            self.detail_label.grid_configure(
                row=1,
                column=0,
                sticky="ew",
                padx=16,
                pady=(0, 8),
            )

    def _cancel_result_snapshot_resize(self) -> None:
        after_id = getattr(self, "_result_snapshot_resize_after_id", None)
        self._result_snapshot_resize_after_id = None
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except Exception:
            pass

    def _hide_result_snapshot(self, clear: bool = False) -> None:
        self._cancel_result_snapshot_resize()
        self._set_result_snapshot_layout(False)
        if clear:
            self._result_snapshot_bgr = None
            self._result_snapshot_tk = None
            self._result_snapshot_is_ok = None
            try:
                self.result_snapshot_canvas.delete("all")
            except Exception:
                pass

    def _show_result_snapshot(self) -> bool:
        frame = getattr(self, "_result_snapshot_bgr", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            self._set_result_snapshot_layout(False)
            return False
        self._set_result_snapshot_layout(True)
        return self._render_result_snapshot()

    def set_result_preview_frame(
        self,
        frame,
        *,
        is_ok: bool,
        failed_led_ids=(),
    ) -> bool:
        """Congela exatamente o frame que originou o último OK/NG do F2.

        ``failed_led_ids`` é aceito para manter o contexto da inspeção disponível
        à interface, mas a miniatura permanece o frame bruto realmente enviado ao
        motor. Assim ela não pode ser confundida com a câmera ao vivo nem com uma
        reconstrução posterior do resultado.
        """
        del failed_led_ids
        if frame is None or getattr(frame, "size", 0) == 0:
            self._hide_result_snapshot(clear=True)
            return False

        try:
            self._result_snapshot_bgr = frame.copy()
        except Exception:
            self._hide_result_snapshot(clear=True)
            return False

        self._result_snapshot_is_ok = bool(is_ok)
        try:
            self.result_snapshot_result.configure(
                text="OK" if is_ok else "NG",
                fg="#86EFAC" if is_ok else "#FCA5A5",
            )
        except Exception:
            pass
        return self._show_result_snapshot()

    def _result_snapshot_canvas_size(self) -> tuple[int, int]:
        try:
            width = int(self.result_snapshot_canvas.winfo_width())
            height = int(self.result_snapshot_canvas.winfo_height())
        except Exception:
            width = height = 0

        if width <= 2 or height <= 2:
            try:
                panel_width = int(self.analysis_panel.winfo_width())
            except Exception:
                panel_width = 640
            width = max(
                F2_RESULT_PREVIEW_MIN_WIDTH,
                int(max(320, panel_width) * F2_RESULT_PREVIEW_SHARE) - 38,
            )
            height = max(
                F2_RESULT_PREVIEW_MIN_HEIGHT,
                int(round(width * 0.75)),
            )
        return max(1, width), max(1, height)

    def _render_result_snapshot(self) -> bool:
        frame = getattr(self, "_result_snapshot_bgr", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            return False

        try:
            frame_height, frame_width = frame.shape[:2]
        except Exception:
            return False
        if frame_width <= 0 or frame_height <= 0:
            return False

        canvas_width, canvas_height = self._result_snapshot_canvas_size()
        scale = min(
            canvas_width / float(frame_width),
            canvas_height / float(frame_height),
        )
        render_width = max(1, int(round(frame_width * scale)))
        render_height = max(1, int(round(frame_height * scale)))
        interpolation = (
            cv2.INTER_AREA
            if render_width < frame_width or render_height < frame_height
            else cv2.INTER_LINEAR
        )
        preview = cv2.resize(
            frame,
            (render_width, render_height),
            interpolation=interpolation,
        )
        image_tk = self._create_preview_image(preview)
        if image_tk is None:
            return False

        offset_x = max(0, (canvas_width - render_width) // 2)
        offset_y = max(0, (canvas_height - render_height) // 2)
        self._result_snapshot_tk = image_tk
        try:
            self.result_snapshot_canvas.delete("all")
            self.result_snapshot_canvas.create_image(
                offset_x,
                offset_y,
                image=image_tk,
                anchor=tk.NW,
            )
        except Exception:
            return False
        return True

    def _on_result_snapshot_resize(self, _event=None) -> None:
        if not bool(getattr(self, "_result_snapshot_visible", False)):
            return
        self._cancel_result_snapshot_resize()
        try:
            self._result_snapshot_resize_after_id = self.root.after(
                F2_RESULT_PREVIEW_RESIZE_DEBOUNCE_MS,
                self._render_result_snapshot,
            )
        except Exception:
            self._result_snapshot_resize_after_id = None
            self._render_result_snapshot()

    def _set_state(
        self,
        background: str,
        foreground: str,
        status: str,
        detail: str,
    ) -> None:
        """Restaura uma linha antes de cada estado normal exclusivo do F2."""
        self._f2_analyzed_waiting_active = False
        label = getattr(self, "status_label", None)
        if label is not None:
            try:
                label.configure(height=1, wraplength=0, pady=0)
            except Exception:
                pass
        super()._set_state(
            background=background,
            foreground=foreground,
            status=status,
            detail=detail,
        )

    def _aplicar_status_pos_analise_f2(self, panel_width: int | None = None) -> None:
        if panel_width is None:
            try:
                panel_width = int(self.analysis_panel.winfo_width())
            except Exception:
                panel_width = 640
        if int(panel_width or 0) <= 2:
            panel_width = 640

        available_width = int(panel_width)
        if bool(getattr(self, "_result_snapshot_visible", False)):
            available_width = largura_texto_com_preview_resultado_f2(
                available_width
            )
        font_size = tamanho_fonte_status_analisado_f2(available_width)
        self.status_label.configure(
            text=F2_ANALYZED_WAITING_TEXT,
            font=("DejaVu Sans", font_size, "bold"),
            height=2,
            pady=0,
            justify="center",
            anchor="center",
            wraplength=0,
        )

    def show_preparing(
        self,
        detail: str = "Preparando câmera e parâmetros",
    ) -> None:
        self._hide_result_snapshot(clear=True)
        return super().show_preparing(detail)

    def show_positioning(
        self,
        delay_seconds: float,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self._hide_result_snapshot(clear=True)
        return super().show_positioning(
            delay_seconds=delay_seconds,
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )

    def show_processing(
        self,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self._hide_result_snapshot(clear=True)
        return super().show_processing(
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )

    def show_error(
        self,
        message: str,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        self._hide_result_snapshot(clear=True)
        return super().show_error(
            message=message,
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )

    def show_waiting(
        self,
        led_count: int,
        total: int,
        ok_count: int,
        ng_count: int,
    ) -> None:
        """Após resultado, orienta a troca da placa sem alterar o ciclo F2."""
        super().show_waiting(
            led_count=led_count,
            total=total,
            ok_count=ok_count,
            ng_count=ng_count,
        )
        if not (
            bool(getattr(self, "_has_led_result", False))
            and getattr(self, "_last_result_ok", None) is not None
        ):
            self._hide_result_snapshot(clear=True)
            return

        self._show_result_snapshot()
        self._f2_analyzed_waiting_active = True
        self._aplicar_status_pos_analise_f2()

    def _on_analysis_resize(self, event) -> None:
        super()._on_analysis_resize(event)
        try:
            width = int(event.width)
        except (TypeError, ValueError, AttributeError):
            width = 640

        if bool(getattr(self, "_result_snapshot_visible", False)):
            text_width = largura_texto_com_preview_resultado_f2(width)
            try:
                self.detail_label.configure(
                    wraplength=max(180, text_width - 28)
                )
            except Exception:
                pass
            self._on_result_snapshot_resize()

        if bool(getattr(self, "_f2_analyzed_waiting_active", False)):
            self._aplicar_status_pos_analise_f2(width)

    def set_board_presence_status(
        self,
        status: str | None,
        enabled: bool = True,
    ) -> None:
        """Mostra o estado físico da placa somente no F2 automático."""
        if not enabled:
            try:
                self.board_presence_label.grid_remove()
            except Exception:
                pass
            return

        normalized = str(status or "unknown").strip().lower()
        if normalized not in F2_BOARD_STATUS_UI:
            normalized = "unknown"
        self._board_presence_status = normalized
        text, color = F2_BOARD_STATUS_UI[normalized]
        try:
            self.board_presence_label.configure(
                text=f"STATUS DA PLACA: {text}",
                fg=color,
            )
            self.board_presence_label.grid()
        except Exception:
            pass

    def set_live_roi_states(
        self,
        states: dict[str, str] | None,
        enabled: bool = True,
    ) -> None:
        """Liga o overlay somente quando a análise automática F2 está ativa."""
        self._live_roi_states = {
            str(key): str(value).strip().upper()
            for key, value in dict(states or {}).items()
        }
        self._live_roi_overlay_enabled = bool(enabled)
        try:
            self.preview_legend.configure(
                text=(F2_LIVE_ROI_LEGEND if enabled else "AZUL: ROI APAGADA")
            )
        except Exception:
            pass

        if enabled:
            self.set_board_presence_status(
                self._board_presence_status,
                enabled=True,
            )
        else:
            self.set_board_presence_status(None, enabled=False)

    def update_preview(self, frame, leds=()) -> bool:
        if not self._live_roi_overlay_enabled:
            return super().update_preview(frame, leds)

        decorated = renderizar_overlay_rois_f2(
            frame,
            leds,
            self._live_roi_states,
        )
        # As ROIs já estão desenhadas no frame com transparência; não sobrepor
        # as guias legadas azul/ciano do modo manual.
        return super().update_preview(decorated, leds=())

    def _draw_guides(
        self,
        leds,
        frame_width: int,
        frame_height: int,
        scale: float,
        offset_x: int,
        offset_y: int,
    ) -> None:
        led_list = list(leds or ())
        if not led_list:
            return

        left = offset_x + int(frame_width * scale)
        top = offset_y + int(frame_height * scale)
        right = offset_x
        bottom = offset_y

        for led in led_list:
            led_id = str(getattr(led, "id", ""))
            center_x = offset_x + int(round(int(getattr(led, "centro_x", 0)) * scale))
            center_y = offset_y + int(round(int(getattr(led, "centro_y", 0)) * scale))
            failed = led_id in self._failed_led_ids
            color = self.PREVIEW_FAILED if failed else self.PREVIEW_GUIDE
            line_width = 3 if failed else 1
            tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))

            bx1, by1, bx2, by2 = bbox_roi(led)
            left = min(left, offset_x + int(round(bx1 * scale)))
            top = min(top, offset_y + int(round(by1 * scale)))
            right = max(right, offset_x + int(round(bx2 * scale)))
            bottom = max(bottom, offset_y + int(round(by2 * scale)))

            if tipo == TIPO_ROI_SEGMENTO:
                coords = []
                for x, y in pontos_segmento(led):
                    coords.extend(
                        (
                            offset_x + float(x) * scale,
                            offset_y + float(y) * scale,
                        )
                    )
                self.preview_canvas.create_polygon(
                    *coords,
                    fill="",
                    outline=color,
                    width=line_width,
                    tags=("preview_guide",),
                )
                label_y = offset_y + int(round(by1 * scale)) - 9
            else:
                radius = max(
                    3,
                    int(round(int(getattr(led, "raio", 1)) * scale)),
                )
                self.preview_canvas.create_oval(
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                    outline=color,
                    width=line_width,
                    tags=("preview_guide",),
                )
                label_y = center_y - radius - 9

            if failed:
                dot_radius = max(3, int(round(4 * max(1.0, scale))))
                self.preview_canvas.create_oval(
                    center_x - dot_radius,
                    center_y - dot_radius,
                    center_x + dot_radius,
                    center_y + dot_radius,
                    fill=self.PREVIEW_FAILED,
                    outline="#FFFFFF",
                    width=1,
                    tags=("preview_guide",),
                )
                self.preview_canvas.create_text(
                    center_x,
                    max(offset_y + 12, label_y),
                    text=f"{led_id} APAGADO",
                    fill="#FFFFFF",
                    font=("DejaVu Sans", 9, "bold"),
                    anchor="s",
                    tags=("preview_guide",),
                )

        margin = max(6, int(round(8 * scale)))
        self.preview_canvas.create_rectangle(
            left - margin,
            top - margin,
            right + margin,
            bottom + margin,
            outline=self.PREVIEW_BOARD_GUIDE,
            width=2,
            dash=(6, 4),
            tags=("preview_guide",),
        )
