from __future__ import annotations

"""Captura guiada ao vivo das referências reais 90°/180°/270° do F2.

Ao clicar em ``Capturar câmera`` em um slot angular, a foto não é mais gravada
imediatamente. O operador recebe uma tela ao vivo com o contorno canônico da placa
(ciano) e as ROIs dos LEDs (amarelo) já transformados para o ângulo nominal do
slot. A máscara fica fixa; quem se move é a peça física até coincidir com a guia.

Quando o operador confirma, exatamente o último frame exibido é persistido e a
transformação nominal usada como guia é marcada como calibrada. O botão
``Desenhar placa`` continua disponível depois para ajuste fino, caso necessário.

Esta camada altera somente a ação de captura dos três slots de orientação. Ela
não abre uma segunda câmera e não interfere no classificador de presença nem no
F3: reutiliza exclusivamente ``app.camera_frame_atual``.
"""

import tkinter as tk
from tkinter import messagebox

import cv2
from PIL import Image, ImageTk

import src.platform.f2_tracking_orientation_references as orientation_refs
from src.platform.f2_board_presence_mask_preview_native import (
    desenhar_contorno_placa_na_referencia_f2,
    desenhar_rois_na_referencia_f2,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds
from src.platform.f2_object_tracking_visual_overlay import (
    transformar_rois_para_frame_atual_f2,
)
from src.platform.reference_project_store import escrever_configuracao


LIVE_CAPTURE_INTERVAL_MS = 35
_PATCH_INSTALADO = False


def _carregar_leds(controller, projeto: str):
    repository = getattr(controller.app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    if not callable(getter):
        return []
    try:
        return list(getter(projeto=projeto) or [])
    except TypeError:
        try:
            return list(getter(projeto) or [])
        except Exception:
            return []
    except Exception:
        return []


def _marcar_captura_nominal_calibrada(controller, slot: str, matrix) -> bool:
    projeto = str(controller.project_name() or "").strip()
    repository = getattr(controller.app, "config_repository", None)
    if not projeto or repository is None or matrix is None:
        return False

    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
        current = orientation_refs.obter_referencias_orientacao_projeto(
            config,
            projeto,
        ).get(slot, {})
        if not current:
            return False

        current = dict(current)
        current["canonical_to_reference"] = matrix.tolist()
        current["calibrated"] = True
        current["base_shape_updated_at"] = orientation_refs._shape_stamp(
            controller,
            projeto,
        )
        # ``definir_referencia_orientacao_projeto`` renormaliza os dados e atualiza
        # o timestamp do projeto. O updated_at da imagem já foi gravado pela rotina
        # de captura imediatamente antes desta chamada.
        config = orientation_refs.definir_referencia_orientacao_projeto(
            config,
            projeto,
            slot,
            current,
        )
        escrever_configuracao(repository, config)
        orientation_refs._invalidar_tracking(controller)
        return True
    except Exception:
        return False


class _LiveOrientationCaptureWindow:
    def __init__(self, controller, slot: str, settings_window) -> None:
        self.controller = controller
        self.app = controller.app
        self.slot = slot
        self.settings_window = settings_window
        self.project = str(controller.project_name() or "").strip()
        self.ui = orientation_refs.F2_ORIENTATION_UI[slot]
        self._photo = None
        self._after_id = None
        self._latest_frame = None
        self._closing = False

        resolution = controller.master_resolution(self.project)
        self.width = int(resolution[0]) if resolution else 0
        self.height = int(resolution[1]) if resolution else 0
        self.matrix = orientation_refs._matriz_nominal(
            controller,
            self.project,
            slot,
        )
        self.shape = (
            carregar_contorno_placa_leds(
                controller,
                self.project,
                self.width,
                self.height,
            )
            if self.width and self.height
            else []
        )
        self.leds = _carregar_leds(controller, self.project)

        self.window = tk.Toplevel(settings_window)
        self.window.title(f"ODIN • Captura guiada {self.ui['short']} • F2")
        self.window.configure(bg="#08111F")
        try:
            sw = int(self.window.winfo_screenwidth())
            sh = int(self.window.winfo_screenheight())
            self.window.geometry(f"{sw}x{sh}+0+0")
        except Exception:
            pass
        self.window.transient(settings_window)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        header = tk.Frame(self.window, bg="#111827")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"CAPTURA GUIADA • PLACA EM {self.ui['short']}",
            font=("Segoe UI", 13, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(12, 3))
        tk.Label(
            header,
            text=(
                "A máscara fica fixa. Movimente e rotacione fisicamente a placa até "
                "o contorno CIANO e as ROIs AMARELAS coincidirem com a peça real. "
                "Quando estiver encaixado, pressione CAPTURAR."
            ),
            font=("Segoe UI", 9),
            fg="#CBD5E1",
            bg="#111827",
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 4))
        tk.Label(
            header,
            text=(
                "CIANO = contorno da placa • AMARELO = posições esperadas dos LEDs • "
                "Enter = capturar • Esc = cancelar"
            ),
            font=("Segoe UI", 8, "bold"),
            fg="#7DD3FC",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 10))

        self.canvas = tk.Canvas(
            self.window,
            bg="#020617",
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 6))

        footer = tk.Frame(self.window, bg="#111827")
        footer.pack(fill=tk.X, padx=12, pady=(0, 12))
        self.status = tk.Label(
            footer,
            text="AGUARDANDO FRAME DA CÂMERA...",
            font=("Segoe UI", 9, "bold"),
            fg="#FBBF24",
            bg="#111827",
            anchor="w",
        )
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 12), pady=8)
        tk.Button(
            footer,
            text="CANCELAR",
            command=self.close,
            font=("Segoe UI", 9, "bold"),
            bg="#3A151A",
            fg="#FCA5A5",
            activebackground="#4A1D23",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=8,
        ).pack(side=tk.RIGHT, padx=(4, 8), pady=6)
        self.capture_button = tk.Button(
            footer,
            text="CAPTURAR",
            command=self.capture,
            state=tk.DISABLED,
            font=("Segoe UI", 9, "bold"),
            bg="#0F3A2B",
            fg="#86EFAC",
            activebackground="#14523B",
            activeforeground="#FFFFFF",
            disabledforeground="#64748B",
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=18,
            pady=8,
        )
        self.capture_button.pack(side=tk.RIGHT, padx=4, pady=6)

        self.window.bind("<Return>", lambda _event: self.capture())
        self.window.bind("<Escape>", lambda _event: self.close())
        self.canvas.bind("<Configure>", lambda _event: self._render_latest())

        try:
            self.window.grab_set()
            self.window.focus_force()
        except Exception:
            pass
        self._schedule_next(immediate=True)

    def _schedule_next(self, *, immediate: bool = False) -> None:
        if self._closing:
            return
        try:
            self._after_id = self.window.after(
                1 if immediate else LIVE_CAPTURE_INTERVAL_MS,
                self._update_live,
            )
        except Exception:
            self._after_id = None

    def _update_live(self) -> None:
        self._after_id = None
        if self._closing:
            return

        frame = getattr(self.app, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            self._latest_frame = None
            try:
                self.capture_button.configure(state=tk.DISABLED)
                self.status.configure(
                    text="CÂMERA SEM FRAME • mantenha a câmera ativa para capturar",
                    fg="#FBBF24",
                )
            except Exception:
                pass
            self._schedule_next()
            return

        try:
            raw = frame.copy()
        except Exception:
            self._schedule_next()
            return

        h, w = raw.shape[:2]
        if (int(w), int(h)) != (self.width, self.height):
            self._latest_frame = None
            self._render_frame(raw, overlay=False)
            try:
                self.capture_button.configure(state=tk.DISABLED)
                self.status.configure(
                    text=(
                        f"RESOLUÇÃO INCOMPATÍVEL • câmera {w}x{h} • "
                        f"projeto {self.width}x{self.height}"
                    ),
                    fg="#FCA5A5",
                )
            except Exception:
                pass
            self._schedule_next()
            return

        self._latest_frame = raw
        self._render_frame(raw, overlay=True)
        try:
            self.capture_button.configure(state=tk.NORMAL)
            self.status.configure(
                text=(
                    f"ALINHE FISICAMENTE A PLACA EM {self.ui['short']} COM A MÁSCARA "
                    "FIXA E PRESSIONE CAPTURAR"
                ),
                fg="#86EFAC",
            )
        except Exception:
            pass
        self._schedule_next()

    def _decorate(self, frame):
        if self.matrix is None:
            return frame
        try:
            tracked_leds = transformar_rois_para_frame_atual_f2(
                self.leds,
                self.matrix,
                self.width,
                self.height,
            )
            tracked_shape = transformar_rois_para_frame_atual_f2(
                self.shape,
                self.matrix,
                self.width,
                self.height,
            )
            decorated, _ = desenhar_rois_na_referencia_f2(frame, tracked_leds)
            decorated, _ = desenhar_contorno_placa_na_referencia_f2(
                decorated,
                tracked_shape,
            )
            cv2.putText(
                decorated,
                f"ALVO {self.ui['short']} - MOVA A PLACA ATE ENCAIXAR",
                (18, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (248, 189, 56),
                2,
                cv2.LINE_AA,
            )
            return decorated
        except Exception:
            return frame

    def _render_frame(self, frame, *, overlay: bool) -> None:
        if frame is None or getattr(frame, "size", 0) == 0:
            return
        decorated = self._decorate(frame.copy()) if overlay else frame.copy()
        try:
            rgb = cv2.cvtColor(decorated, cv2.COLOR_BGR2RGB)
            canvas_w = max(120, int(self.canvas.winfo_width()))
            canvas_h = max(120, int(self.canvas.winfo_height()))
            h, w = rgb.shape[:2]
            scale = min(canvas_w / float(w), canvas_h / float(h))
            scale = max(0.01, scale)
            display_w = max(1, int(round(w * scale)))
            display_h = max(1, int(round(h * scale)))
            pil = Image.fromarray(rgb).resize(
                (display_w, display_h),
                Image.Resampling.LANCZOS,
            )
            self._photo = ImageTk.PhotoImage(pil)
            self.canvas.delete("all")
            self.canvas.create_image(
                canvas_w / 2.0,
                canvas_h / 2.0,
                image=self._photo,
                anchor="center",
            )
        except Exception:
            pass

    def _render_latest(self) -> None:
        frame = self._latest_frame
        if frame is not None and getattr(frame, "size", 0):
            self._render_frame(frame, overlay=True)

    def capture(self) -> None:
        if self._closing:
            return
        frame = self._latest_frame
        if frame is None or getattr(frame, "size", 0) == 0:
            return
        if self.matrix is None:
            messagebox.showwarning(
                "Contorno base necessário",
                "Não foi possível construir a máscara nominal desta orientação.",
                parent=self.window,
            )
            return

        # Usa exatamente o último frame mostrado ao operador, evitando capturar um
        # frame posterior depois que a peça já começou a se mover novamente.
        saved = orientation_refs._save_orientation_image(
            self.controller,
            self.slot,
            frame.copy(),
            self.window,
        )
        if not saved:
            return

        calibrated = _marcar_captura_nominal_calibrada(
            self.controller,
            self.slot,
            self.matrix,
        )
        if not calibrated:
            messagebox.showwarning(
                "Imagem salva",
                (
                    "A imagem foi salva, mas a calibração automática não pôde ser "
                    "confirmada. Use 'Desenhar placa' neste slot para concluir."
                ),
                parent=self.window,
            )
        self.close(refresh=True)

    def close(self, refresh: bool = False) -> None:
        if self._closing:
            return
        self._closing = True
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass

        if refresh:
            try:
                self.controller.render_settings(self.settings_window)
                self.settings_window.lift()
                self.settings_window.focus_force()
            except Exception:
                pass
        try:
            self.settings_window.grab_set()
        except Exception:
            pass


def _abrir_captura_guiada(controller, slot: str, window) -> None:
    if slot not in orientation_refs.F2_ORIENTATION_SLOTS:
        return
    projeto = str(controller.project_name() or "").strip()
    resolution = controller.master_resolution(projeto) if projeto else None
    if not projeto or not resolution:
        messagebox.showwarning(
            "Projeto necessário",
            "Carregue um projeto LED com resolução mestre antes de capturar.",
            parent=window,
        )
        return

    shape = carregar_contorno_placa_leds(
        controller,
        projeto,
        int(resolution[0]),
        int(resolution[1]),
    )
    if not shape:
        messagebox.showwarning(
            "Contorno base necessário",
            (
                "Desenhe primeiro a placa em 'Placa fixa ligada' ou 'Placa fixa "
                "desligada'. A captura guiada rotaciona esse mesmo contorno."
            ),
            parent=window,
        )
        return

    matrix = orientation_refs._matriz_nominal(controller, projeto, slot)
    if matrix is None:
        messagebox.showwarning(
            "Máscara indisponível",
            "Não foi possível gerar a máscara rotacionada para este slot.",
            parent=window,
        )
        return

    _LiveOrientationCaptureWindow(controller, slot, window)


def instalar_captura_guiada_referencias_orientacao_f2() -> None:
    """Substitui somente ``Capturar câmera`` dos três slots angulares do F2."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    atual = orientation_refs._capture_orientation
    if bool(getattr(atual, "_odin_f2_guided_orientation_capture", False)):
        _PATCH_INSTALADO = True
        return

    def capturar_com_guia(controller, slot: str, window) -> None:
        return _abrir_captura_guiada(controller, slot, window)

    capturar_com_guia._odin_f2_guided_orientation_capture = True
    capturar_com_guia._odin_f2_guided_orientation_capture_base = atual
    orientation_refs._capture_orientation = capturar_com_guia
    _PATCH_INSTALADO = True
