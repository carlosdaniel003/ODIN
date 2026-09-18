from __future__ import annotations

import base64
import tkinter as tk

import cv2

from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)
from src.ui.main_window_parts.image.selection_zoom import (
    ZOOM_SELECAO_MAX,
    ZOOM_SELECAO_MIN,
    calcular_centro_zoom_ancorado,
    calcular_viewport_zoom_selecao,
    proximo_fator_zoom_selecao,
)

CTRL_MASK = 0x0004


def proximo_zoom_check_ctrl_a(atual: float) -> float:
    """Ctrl+A avança um passo de zoom; no máximo, retorna ao enquadramento."""
    atual = float(atual or ZOOM_SELECAO_MIN)
    if atual >= ZOOM_SELECAO_MAX - 1e-9:
        return ZOOM_SELECAO_MIN
    return proximo_fator_zoom_selecao(atual, 1)


def instalar_zoom_check_display() -> None:
    """Instala zoom somente na tela visual de CHECK do F3.

    Não altera classes, bindings ou estado da Produção F2. A substituição ocorre
    apenas no símbolo ``DisplayCheckMaskEditorWindow`` do módulo Display.
    """
    import src.platform.display_check_editor as check_module

    base = check_module.DisplayCheckMaskEditorWindow
    if getattr(base, "_odin_display_check_zoom", False):
        return

    class DisplayCheckMaskEditorComZoom(base):
        _odin_display_check_zoom = True

        def __init__(self, *args, **kwargs) -> None:
            self._check_zoom_factor = ZOOM_SELECAO_MIN
            self._check_zoom_centro_x = None
            self._check_zoom_centro_y = None
            self._check_pan_ativo = False
            self._check_pan_ultimo = None
            super().__init__(*args, **kwargs)
            self._instalar_eventos_zoom_check()

        def _viewport_check(self):
            return calcular_viewport_zoom_selecao(
                largura_visual=self.master_width,
                altura_visual=self.master_height,
                largura_canvas=max(1, int(self.canvas.winfo_width())),
                altura_canvas=max(1, int(self.canvas.winfo_height())),
                fator_zoom=self._check_zoom_factor,
                centro_visual_x=self._check_zoom_centro_x,
                centro_visual_y=self._check_zoom_centro_y,
            )

        def _canvas_geometry(self) -> tuple[float, float, float]:
            viewport = self._viewport_check()
            return (
                float(viewport.escala),
                float(viewport.deslocamento_virtual_x),
                float(viewport.deslocamento_virtual_y),
            )

        def _instalar_eventos_zoom_check(self) -> None:
            for sequencia in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.bind(sequencia, self._evento_zoom_check, add="+")
            self.canvas.bind("<Button-2>", self._iniciar_pan_check, add="+")
            self.canvas.bind("<B2-Motion>", self._arrastar_pan_check, add="+")
            self.canvas.bind("<ButtonRelease-2>", self._finalizar_pan_check, add="+")

            # Pedido específico do F3: Ctrl+A também avança o zoom.
            self.canvas.bind("<Control-a>", self._evento_ctrl_a_zoom_check)
            self.canvas.bind("<Control-A>", self._evento_ctrl_a_zoom_check)
            self.window.bind("<Control-a>", self._evento_ctrl_a_zoom_check)
            self.window.bind("<Control-A>", self._evento_ctrl_a_zoom_check)

            # Complemento simétrico para voltar um passo sem depender da roda.
            self.canvas.bind("<Control-Shift-A>", self._evento_ctrl_shift_a_zoom_check)
            self.window.bind("<Control-Shift-A>", self._evento_ctrl_shift_a_zoom_check)

        @staticmethod
        def _direcao_roda(evento) -> int:
            delta = int(getattr(evento, "delta", 0) or 0)
            numero = getattr(evento, "num", None)
            if delta > 0 or numero == 4:
                return 1
            if delta < 0 or numero == 5:
                return -1
            return 0

        def _ponto_ancora_canvas(self, evento=None) -> tuple[float, float]:
            largura = max(1, int(self.canvas.winfo_width()))
            altura = max(1, int(self.canvas.winfo_height()))
            if evento is not None:
                x = float(getattr(evento, "x", largura / 2.0))
                y = float(getattr(evento, "y", altura / 2.0))
                if 0 <= x < largura and 0 <= y < altura:
                    return x, y
            try:
                x = float(self.canvas.winfo_pointerx() - self.canvas.winfo_rootx())
                y = float(self.canvas.winfo_pointery() - self.canvas.winfo_rooty())
                if 0 <= x < largura and 0 <= y < altura:
                    return x, y
            except Exception:
                pass
            return largura / 2.0, altura / 2.0

        def _aplicar_zoom_check(
            self,
            novo_fator: float,
            evento=None,
        ) -> str:
            fator_atual = float(self._check_zoom_factor or ZOOM_SELECAO_MIN)
            novo_fator = float(novo_fator)
            if abs(novo_fator - fator_atual) < 1e-9:
                return "break"

            viewport = self._viewport_check()
            ancora_x, ancora_y = self._ponto_ancora_canvas(evento)
            nova_escala = max(1e-9, float(viewport.escala)) * (
                novo_fator / max(ZOOM_SELECAO_MIN, fator_atual)
            )
            centro_x, centro_y = calcular_centro_zoom_ancorado(
                ponteiro_x=ancora_x,
                ponteiro_y=ancora_y,
                escala_atual=float(viewport.escala),
                deslocamento_atual_x=float(viewport.deslocamento_virtual_x),
                deslocamento_atual_y=float(viewport.deslocamento_virtual_y),
                largura_virtual_atual=int(viewport.largura_virtual),
                altura_virtual_atual=int(viewport.altura_virtual),
                nova_escala=nova_escala,
                largura_canvas=max(1, int(self.canvas.winfo_width())),
                altura_canvas=max(1, int(self.canvas.winfo_height())),
                largura_visual=self.master_width,
                altura_visual=self.master_height,
                centro_atual_x=self._check_zoom_centro_x,
                centro_atual_y=self._check_zoom_centro_y,
            )

            self._check_zoom_factor = novo_fator
            if novo_fator <= ZOOM_SELECAO_MIN:
                self._check_zoom_centro_x = None
                self._check_zoom_centro_y = None
                self._finalizar_pan_check()
            else:
                self._check_zoom_centro_x = centro_x
                self._check_zoom_centro_y = centro_y
            self.redraw()
            return "break"

        def _evento_zoom_check(self, evento) -> str | None:
            # Igual ao editor do F2: somente Ctrl+roda altera o zoom.
            estado = int(getattr(evento, "state", 0) or 0)
            if not (estado & CTRL_MASK):
                return None
            direcao = self._direcao_roda(evento)
            if direcao == 0:
                return "break"
            novo = proximo_fator_zoom_selecao(
                self._check_zoom_factor,
                direcao,
            )
            return self._aplicar_zoom_check(novo, evento)

        def _evento_ctrl_a_zoom_check(self, evento=None) -> str:
            novo = proximo_zoom_check_ctrl_a(self._check_zoom_factor)
            return self._aplicar_zoom_check(novo, evento)

        def _evento_ctrl_shift_a_zoom_check(self, evento=None) -> str:
            novo = proximo_fator_zoom_selecao(self._check_zoom_factor, -1)
            return self._aplicar_zoom_check(novo, evento)

        def _iniciar_pan_check(self, evento) -> str:
            if self._check_zoom_factor <= ZOOM_SELECAO_MIN:
                return "break"
            self._check_pan_ativo = True
            self._check_pan_ultimo = (
                float(getattr(evento, "x", 0.0)),
                float(getattr(evento, "y", 0.0)),
            )
            try:
                self.canvas.configure(cursor="fleur")
            except Exception:
                pass
            return "break"

        def _arrastar_pan_check(self, evento) -> str:
            if not self._check_pan_ativo or self._check_pan_ultimo is None:
                return "break"
            viewport = self._viewport_check()
            escala = max(1e-9, float(viewport.escala))
            x = float(getattr(evento, "x", self._check_pan_ultimo[0]))
            y = float(getattr(evento, "y", self._check_pan_ultimo[1]))
            dx = x - self._check_pan_ultimo[0]
            dy = y - self._check_pan_ultimo[1]
            self._check_pan_ultimo = (x, y)

            largura_canvas = max(1, int(self.canvas.winfo_width()))
            altura_canvas = max(1, int(self.canvas.winfo_height()))
            centro_efetivo_x = (
                largura_canvas / 2.0 - float(viewport.deslocamento_virtual_x)
            ) / escala
            centro_efetivo_y = (
                altura_canvas / 2.0 - float(viewport.deslocamento_virtual_y)
            ) / escala
            self._check_zoom_centro_x = max(
                0.0,
                min(float(self.master_width), centro_efetivo_x - dx / escala),
            )
            self._check_zoom_centro_y = max(
                0.0,
                min(float(self.master_height), centro_efetivo_y - dy / escala),
            )
            self.redraw()
            return "break"

        def _finalizar_pan_check(self, _evento=None) -> str:
            self._check_pan_ativo = False
            self._check_pan_ultimo = None
            try:
                self.canvas.configure(cursor="hand2")
            except Exception:
                pass
            return "break"

        def _background_zoom_check(self, viewport):
            if self.frame is None:
                return None
            try:
                crop = self.frame[
                    viewport.origem_visual_y:viewport.fim_visual_y,
                    viewport.origem_visual_x:viewport.fim_visual_x,
                ]
                if getattr(crop, "size", 0) == 0:
                    return None
                resized = cv2.resize(
                    crop,
                    (
                        max(1, int(viewport.largura_render)),
                        max(1, int(viewport.altura_render)),
                    ),
                    interpolation=(
                        cv2.INTER_AREA if viewport.escala < 1.0 else cv2.INTER_LINEAR
                    ),
                )
                ok, buffer = cv2.imencode(
                    ".png",
                    resized,
                    [cv2.IMWRITE_PNG_COMPRESSION, 1],
                )
                if not ok:
                    return None
                return tk.PhotoImage(
                    data=base64.b64encode(buffer).decode("ascii")
                )
            except Exception:
                return None

        def redraw(self) -> None:
            if not self.visible:
                return
            self.canvas.delete("all")
            viewport = self._viewport_check()
            self._scale = float(viewport.escala)
            self._offset_x = float(viewport.deslocamento_virtual_x)
            self._offset_y = float(viewport.deslocamento_virtual_y)

            self._photo = self._background_zoom_check(viewport)
            if self._photo is not None:
                self.canvas.create_image(
                    viewport.deslocamento_render_x,
                    viewport.deslocamento_render_y,
                    image=self._photo,
                    anchor=tk.NW,
                )
            else:
                self.canvas.create_rectangle(
                    viewport.deslocamento_virtual_x,
                    viewport.deslocamento_virtual_y,
                    viewport.deslocamento_virtual_x + viewport.largura_virtual,
                    viewport.deslocamento_virtual_y + viewport.altura_virtual,
                    fill="#0B1220",
                    outline=self.BORDER,
                )

            if len(getattr(self, "board_points", [])) >= 3:
                coords = []
                for point in self.board_points:
                    cx, cy = self._to_canvas(point[0], point[1])
                    coords.extend((cx, cy))
                self.canvas.create_polygon(
                    *coords,
                    fill="",
                    outline="#22D3EE",
                    width=2,
                    tags=("f3_check_board",),
                )

            for index, mask in enumerate(self.masks):
                self._draw_mask(index, mask)

            if bool(getattr(self, "geometry_mode", False)):
                try:
                    self._draw_geometry_handles()
                except Exception:
                    pass

            counts = {
                state: sum(1 for value in self.states.values() if value == state)
                for state in (
                    DISPLAY_CHECK_STATE_ON,
                    DISPLAY_CHECK_STATE_OFF,
                    DISPLAY_CHECK_STATE_IGNORE,
                )
            }
            if bool(getattr(self, "geometry_mode", False)):
                self.status.configure(
                    text=(
                        f"GEOMETRIA • {len(getattr(self, 'board_points', []))} pontos da placa • "
                        f"{len(self.masks)} máscaras • ZOOM "
                        f"{int(round(self._check_zoom_factor * 100))}% • "
                        "arraste pontos/máscaras • setas 1 px • Ctrl+Z desfaz • "
                        "Ctrl+roda ajusta zoom"
                    )
                )
            else:
                self.status.configure(
                    text=(
                        f"{self.check_name} • ACESO {counts[DISPLAY_CHECK_STATE_ON]} • "
                        f"APAGADO {counts[DISPLAY_CHECK_STATE_OFF]} • "
                        f"IGNORAR {counts[DISPLAY_CHECK_STATE_IGNORE]} • "
                        f"ZOOM {int(round(self._check_zoom_factor * 100))}% • "
                        "Ctrl+A aproxima • Ctrl+Shift+A afasta • Ctrl+roda ajusta • "
                        "botão do meio arrasta"
                    )
                )

    DisplayCheckMaskEditorComZoom.__name__ = "DisplayCheckMaskEditorWindow"
    DisplayCheckMaskEditorComZoom.__qualname__ = "DisplayCheckMaskEditorWindow"
    check_module.DisplayCheckMaskEditorWindow = DisplayCheckMaskEditorComZoom


instalar_zoom_check_display()
