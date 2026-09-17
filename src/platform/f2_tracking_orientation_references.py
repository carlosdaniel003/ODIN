from __future__ import annotations

"""Referências reais por orientação para o rastreamento da Produção F2.

Os três slots deste módulo são opcionais e não participam do classificador de
presença (placa ligada/desligada/suporte vazio). Eles existem exclusivamente para
melhorar a pose geométrica do rastreamento quando a placa está aproximadamente em
90°, 180° ou 270°.

Cada referência guarda:
- a imagem real capturada/carregada naquela orientação;
- uma transformação 2x3 CANÔNICO -> REFERÊNCIA calibrada pelo operador;
- o timestamp do contorno canônico usado na calibração.

O contorno da placa continua sendo único no projeto. O botão "Desenhar placa" dos
slots angulares abre um calibrador: a mesma máscara canônica é rotacionada para a
orientação nominal e o operador apenas move, gira e escala até encaixar na foto.
Nenhuma segunda geometria independente da placa é criada.
"""

import copy
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageTk

from config import CONFIG_DIR
from src.core.roi_geometry import bbox_roi, pontos_segmento
from src.platform.f2_board_presence_references import F2BoardPresenceReferenceController
from src.platform.f2_board_shape_editor import (
    carregar_contorno_placa_leds,
    obter_contorno_placa_projeto,
)
from src.platform.f2_object_tracking_visual_overlay import (
    transformar_rois_para_frame_atual_f2,
)
from src.platform.reference_capture import _criar_photo_preview, _encontrar_corpo_referencias
from src.platform.reference_project_store import escrever_configuracao


F2_TRACKING_ORIENTATION_KEY = "f2_tracking_orientation_references"
F2_ORIENTATION_90 = "orientation_90"
F2_ORIENTATION_180 = "orientation_180"
F2_ORIENTATION_270 = "orientation_270"
F2_ORIENTATION_SLOTS = (
    F2_ORIENTATION_90,
    F2_ORIENTATION_180,
    F2_ORIENTATION_270,
)
F2_ORIENTATION_ANGLE = {
    F2_ORIENTATION_90: 90.0,
    F2_ORIENTATION_180: 180.0,
    F2_ORIENTATION_270: 270.0,
}
F2_ORIENTATION_UI = {
    F2_ORIENTATION_90: {
        "title": "Rotação real 90°",
        "short": "90°",
        "color": "#7DD3FC",
    },
    F2_ORIENTATION_180: {
        "title": "Rotação real 180°",
        "short": "180°",
        "color": "#C4B5FD",
    },
    F2_ORIENTATION_270: {
        "title": "Rotação real 270°",
        "short": "270°",
        "color": "#67E8F9",
    },
}

_PATCH_PRESERVACAO_INSTALADO = False
_PATCH_UI_INSTALADO = False


def _normalizar_nome_projeto(nome: str | None) -> str:
    return re.sub(r"\s+", " ", str(nome or "").strip()).upper()


def _slug(valor: str | None) -> str:
    texto = re.sub(r"[^A-Za-z0-9_-]+", "_", str(valor or "").strip())
    return texto.strip("_").lower() or "sem_projeto"


def _normalizar_matriz(valor) -> list[list[float]] | None:
    try:
        matriz = np.asarray(valor, dtype=np.float32).reshape(2, 3)
    except Exception:
        return None
    if not np.all(np.isfinite(matriz)):
        return None
    return [[float(v) for v in linha] for linha in matriz]


def matriz_orientacao_np(entrada: dict | None) -> np.ndarray | None:
    if not isinstance(entrada, dict):
        return None
    valor = _normalizar_matriz(entrada.get("canonical_to_reference"))
    if valor is None:
        return None
    return np.asarray(valor, dtype=np.float32).reshape(2, 3)


def _normalizar_entrada(entrada, slot: str) -> dict:
    if not isinstance(entrada, dict):
        return {}
    caminho = str(entrada.get("image_path") or "").strip()
    if not caminho:
        return {}
    try:
        width = max(0, int(entrada.get("width") or 0))
        height = max(0, int(entrada.get("height") or 0))
    except (TypeError, ValueError):
        width = height = 0
    matriz = _normalizar_matriz(entrada.get("canonical_to_reference"))
    return {
        "image_path": caminho,
        "width": width,
        "height": height,
        "angle_deg": float(F2_ORIENTATION_ANGLE.get(slot, 0.0)),
        "canonical_to_reference": matriz,
        "calibrated": bool(entrada.get("calibrated", False) and matriz is not None),
        "base_shape_updated_at": entrada.get("base_shape_updated_at"),
        "updated_at": entrada.get("updated_at"),
    }


def normalizar_referencias_orientacao(valor) -> dict[str, dict]:
    origem = valor if isinstance(valor, dict) else {}
    return {
        slot: _normalizar_entrada(origem.get(slot), slot)
        for slot in F2_ORIENTATION_SLOTS
    }


def obter_referencias_orientacao_projeto(
    configuracao: dict | None,
    projeto: str | None,
) -> dict[str, dict]:
    dados = configuracao if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        return normalizar_referencias_orientacao({})
    nome = _normalizar_nome_projeto(projeto)
    projeto_dados = projetos.get(nome, {})
    if not isinstance(projeto_dados, dict):
        return normalizar_referencias_orientacao({})
    return normalizar_referencias_orientacao(
        projeto_dados.get(F2_TRACKING_ORIENTATION_KEY)
    )


def definir_referencia_orientacao_projeto(
    configuracao: dict | None,
    projeto: str,
    slot: str,
    entrada: dict | None,
) -> dict:
    if slot not in F2_ORIENTATION_SLOTS:
        raise ValueError("slot de orientação F2 inválido")
    dados = copy.deepcopy(configuracao) if isinstance(configuracao, dict) else {}
    projetos = dados.get("led_projects", {})
    if not isinstance(projetos, dict):
        projetos = {}
    nome = _normalizar_nome_projeto(projeto)
    if not nome or nome not in projetos or not isinstance(projetos[nome], dict):
        raise ValueError("carregue um projeto de LEDs antes de salvar a orientação")

    projeto_dados = dict(projetos[nome])
    referencias = normalizar_referencias_orientacao(
        projeto_dados.get(F2_TRACKING_ORIENTATION_KEY)
    )
    referencias[slot] = _normalizar_entrada(entrada, slot)
    agora = datetime.now(timezone.utc).isoformat()
    projeto_dados[F2_TRACKING_ORIENTATION_KEY] = referencias
    projeto_dados["updated_at"] = agora
    projetos[nome] = projeto_dados
    dados["led_projects"] = projetos
    return dados


def instalar_preservacao_referencias_orientacao_f2() -> None:
    global _PATCH_PRESERVACAO_INSTALADO
    if _PATCH_PRESERVACAO_INSTALADO:
        return

    import src.platform.led_project_repository as repository_module

    atual = repository_module._normalizar_projetos
    if bool(getattr(atual, "_odin_f2_orientation_refs", False)):
        _PATCH_PRESERVACAO_INSTALADO = True
        return
    anterior = atual

    def normalizar_com_orientacoes(configuracao: dict) -> dict:
        preservadas: dict[str, dict] = {}
        origem = configuracao.get("led_projects", {})
        if isinstance(origem, dict):
            for chave, dados in origem.items():
                if not isinstance(dados, dict):
                    continue
                nome = repository_module.normalizar_nome_projeto_led(
                    dados.get("name", chave)
                )
                if nome:
                    preservadas[nome] = normalizar_referencias_orientacao(
                        dados.get(F2_TRACKING_ORIENTATION_KEY)
                    )

        projetos = anterior(configuracao)
        for nome, referencias in preservadas.items():
            if nome in projetos and isinstance(projetos[nome], dict):
                projetos[nome][F2_TRACKING_ORIENTATION_KEY] = referencias
        configuracao["led_projects"] = projetos
        return projetos

    normalizar_com_orientacoes._odin_f2_orientation_refs = True
    repository_module._normalizar_projetos = normalizar_com_orientacoes
    _PATCH_PRESERVACAO_INSTALADO = True


def _shape_stamp(controller, projeto: str) -> str | None:
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return None
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
        shape = obter_contorno_placa_projeto(config, projeto)
        return shape.get("updated_at")
    except Exception:
        return None


def referencia_orientacao_calibrada(
    entrada: dict | None,
    shape_stamp: str | None,
) -> bool:
    if not isinstance(entrada, dict) or not entrada:
        return False
    if not bool(entrada.get("calibrated")):
        return False
    if matriz_orientacao_np(entrada) is None:
        return False
    salvo = entrada.get("base_shape_updated_at")
    return bool(shape_stamp and salvo and str(salvo) == str(shape_stamp))


def _managed_path(projeto: str, slot: str) -> Path:
    directory = Path(CONFIG_DIR) / "f2_tracking_orientations" / _slug(projeto)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{slot}.png"


def _entries(controller, projeto: str) -> dict[str, dict]:
    repository = getattr(controller.app, "config_repository", None)
    if repository is None:
        return normalizar_referencias_orientacao({})
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        config = {}
    return obter_referencias_orientacao_projeto(config, projeto)


def _invalidar_tracking(controller) -> None:
    app = controller.app
    try:
        app._f2_tracking_visual_geometry_cache = None
    except Exception:
        pass
    tracker = getattr(app, "_f2_object_tracker", None)
    reset = getattr(tracker, "reset", None)
    if callable(reset):
        try:
            reset()
        except Exception:
            pass


def _matriz_nominal(controller, projeto: str, slot: str) -> np.ndarray | None:
    resolution = controller.master_resolution(projeto)
    if not resolution:
        return None
    width, height = int(resolution[0]), int(resolution[1])
    shape = carregar_contorno_placa_leds(controller, projeto, width, height)
    if not shape:
        return None
    try:
        points = np.asarray(pontos_segmento(shape[0]), dtype=np.float32).reshape(-1, 2)
        if len(points) < 3:
            return None
        center = np.mean(points, axis=0)
        angle = float(F2_ORIENTATION_ANGLE[slot])
        return cv2.getRotationMatrix2D(
            (float(center[0]), float(center[1])),
            angle,
            1.0,
        ).astype(np.float32)
    except Exception:
        return None


def _save_orientation_image(controller, slot: str, image, window) -> bool:
    projeto = str(controller.project_name() or "").strip()
    if not projeto:
        messagebox.showwarning(
            "Projeto necessário",
            "Carregue um projeto de LEDs antes de salvar esta referência.",
            parent=window,
        )
        return False

    validator = getattr(controller, "_validate_image", None)
    if not callable(validator):
        return False
    valid, resolution = validator(image, window)
    if not valid or resolution is None:
        return False

    path = _managed_path(projeto, slot)
    if not cv2.imwrite(str(path), image):
        messagebox.showerror(
            "Falha ao salvar",
            "Não foi possível salvar a referência real de orientação do F2.",
            parent=window,
        )
        return False

    nominal = _matriz_nominal(controller, projeto, slot)
    repository = controller.app.config_repository
    config = repository.carregar_configuracao_existente_sem_alerta()
    config = definir_referencia_orientacao_projeto(
        config,
        projeto,
        slot,
        {
            "image_path": str(path),
            "width": int(resolution[0]),
            "height": int(resolution[1]),
            "angle_deg": float(F2_ORIENTATION_ANGLE[slot]),
            "canonical_to_reference": (
                nominal.tolist() if nominal is not None else None
            ),
            "calibrated": False,
            "base_shape_updated_at": _shape_stamp(controller, projeto),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    escrever_configuracao(repository, config)
    _invalidar_tracking(controller)
    return True


def _capture_orientation(controller, slot: str, window) -> None:
    frame = getattr(controller.app, "camera_frame_atual", None)
    if frame is None or getattr(frame, "size", 0) == 0:
        messagebox.showwarning(
            "Câmera sem imagem",
            "A câmera ainda não possui um frame válido para capturar.",
            parent=window,
        )
        return
    if _save_orientation_image(controller, slot, frame.copy(), window):
        controller.render_settings(window)


def _load_orientation(controller, slot: str, window) -> None:
    path = filedialog.askopenfilename(
        parent=window,
        title=f"Selecionar referência real {F2_ORIENTATION_UI[slot]['short']}",
        filetypes=[
            ("Imagens", "*.png *.jpg *.jpeg *.bmp"),
            ("Todos os arquivos", "*.*"),
        ],
    )
    if not path:
        return
    image = cv2.imread(path)
    if _save_orientation_image(controller, slot, image, window):
        controller.render_settings(window)


def _remove_orientation(controller, slot: str, window) -> None:
    projeto = str(controller.project_name() or "").strip()
    if not projeto:
        return
    entries = _entries(controller, projeto)
    entry = entries.get(slot, {})
    if not entry:
        return
    if not messagebox.askyesno(
        "Remover referência",
        f"Remover a referência real de {F2_ORIENTATION_UI[slot]['short']} do projeto {projeto}?",
        parent=window,
    ):
        return

    repository = controller.app.config_repository
    config = repository.carregar_configuracao_existente_sem_alerta()
    config = definir_referencia_orientacao_projeto(config, projeto, slot, None)
    escrever_configuracao(repository, config)
    path = str(entry.get("image_path") or "")
    try:
        managed_root = (Path(CONFIG_DIR) / "f2_tracking_orientations").resolve()
        candidate = Path(path).resolve()
        if managed_root in candidate.parents and candidate.exists():
            candidate.unlink()
    except Exception:
        pass
    _invalidar_tracking(controller)
    controller.render_settings(window)


def _matriz_homogenea(affine) -> np.ndarray:
    value = np.asarray(affine, dtype=np.float32).reshape(2, 3)
    return np.asarray(
        [
            [value[0, 0], value[0, 1], value[0, 2]],
            [value[1, 0], value[1, 1], value[1, 2]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def _compor_esquerda(ajuste, atual) -> np.ndarray:
    resultado = _matriz_homogenea(ajuste) @ _matriz_homogenea(atual)
    return np.asarray(resultado[:2, :], dtype=np.float32)


def _centro_rois(rois) -> tuple[float, float]:
    pontos = []
    for roi in tuple(rois or ()):
        try:
            pontos.extend(np.asarray(pontos_segmento(roi), dtype=np.float32).reshape(-1, 2))
        except Exception:
            try:
                x1, y1, x2, y2 = bbox_roi(roi)
                pontos.extend([(x1, y1), (x2, y2)])
            except Exception:
                continue
    if not pontos:
        return 0.0, 0.0
    values = np.asarray(pontos, dtype=np.float32).reshape(-1, 2)
    center = np.mean(values, axis=0)
    return float(center[0]), float(center[1])


class _OrientationCalibrationWindow:
    def __init__(self, controller, slot: str, settings_window) -> None:
        self.controller = controller
        self.app = controller.app
        self.slot = slot
        self.settings_window = settings_window
        self.project = str(controller.project_name() or "").strip()
        self.entries = _entries(controller, self.project)
        self.entry = self.entries.get(slot, {})
        self.image = cv2.imread(str(self.entry.get("image_path") or ""))
        resolution = controller.master_resolution(self.project)
        self.width = int(resolution[0]) if resolution else 0
        self.height = int(resolution[1]) if resolution else 0
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
        repository = getattr(self.app, "config_repository", None)
        getter = getattr(repository, "carregar_leds_fixos", None)
        try:
            self.leds = list(getter(projeto=self.project) or []) if callable(getter) else []
        except TypeError:
            try:
                self.leds = list(getter(self.project) or []) if callable(getter) else []
            except Exception:
                self.leds = []
        except Exception:
            self.leds = []

        stored = matriz_orientacao_np(self.entry)
        nominal = _matriz_nominal(controller, self.project, slot)
        self.matrix = (
            stored.copy()
            if stored is not None
            else (nominal.copy() if nominal is not None else np.eye(2, 3, dtype=np.float32))
        )
        self.nominal = (
            nominal.copy() if nominal is not None else self.matrix.copy()
        )
        self._photo = None
        self._render_after = None
        self._drag_last = None
        self._display_scale = 1.0

        self.window = tk.Toplevel(settings_window)
        self.window.title(
            f"ODIN • Calibrar placa real {F2_ORIENTATION_UI[slot]['short']}"
        )
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
            text=(
                f"REFERÊNCIA REAL {F2_ORIENTATION_UI[slot]['short']} • "
                "AJUSTE O MESMO CONTORNO DA PLACA"
            ),
            font=("Segoe UI", 12, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(12, 3))
        tk.Label(
            header,
            text=(
                "Arraste a imagem para mover a máscara. Roda do mouse gira 1°. "
                "Shift + roda ajusta a escala. Use os botões para correção fina e SALVAR quando o ciano coincidir com a placa."
            ),
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(0, 10))

        self.canvas = tk.Canvas(
            self.window,
            bg="#020617",
            bd=0,
            highlightthickness=0,
            cursor="fleur",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        self.canvas.bind("<Configure>", lambda _e: self.schedule_render())
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: self._stop_drag())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", self._wheel)
        self.canvas.bind("<Button-5>", self._wheel)

        toolbar = tk.Frame(self.window, bg="#111827")
        toolbar.pack(fill=tk.X, padx=12, pady=(0, 12))

        def button(text, command, *, bg="#182231", fg="#E5E7EB"):
            tk.Button(
                toolbar,
                text=text,
                command=command,
                font=("Segoe UI", 8, "bold"),
                bg=bg,
                fg=fg,
                activebackground="#243246",
                activeforeground="#FFFFFF",
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                padx=9,
                pady=7,
            ).pack(side=tk.LEFT, padx=(0, 5))

        button("← 5px", lambda: self.translate(-5, 0))
        button("→ 5px", lambda: self.translate(5, 0))
        button("↑ 5px", lambda: self.translate(0, -5))
        button("↓ 5px", lambda: self.translate(0, 5))
        button("ROT -1°", lambda: self.rotate(-1.0))
        button("ROT +1°", lambda: self.rotate(1.0))
        button("ESC -1%", lambda: self.scale(0.99))
        button("ESC +1%", lambda: self.scale(1.01))
        button("RESET", self.reset, bg="#3F2B12", fg="#FCD34D")
        tk.Frame(toolbar, bg="#111827").pack(side=tk.LEFT, fill=tk.X, expand=True)
        button("CANCELAR", self.close, bg="#3A151A", fg="#FCA5A5")
        button("SALVAR", self.save, bg="#0F3A2B", fg="#86EFAC")

        self.window.bind("<Escape>", lambda _e: self.close())
        self.window.bind("<Left>", lambda _e: self.translate(-1, 0))
        self.window.bind("<Right>", lambda _e: self.translate(1, 0))
        self.window.bind("<Up>", lambda _e: self.translate(0, -1))
        self.window.bind("<Down>", lambda _e: self.translate(0, 1))
        try:
            self.window.grab_set()
            self.window.focus_force()
        except Exception:
            pass
        self.schedule_render()

    def transformed_shape(self):
        return transformar_rois_para_frame_atual_f2(
            self.shape,
            self.matrix,
            self.width,
            self.height,
        )

    def transformed_leds(self):
        return transformar_rois_para_frame_atual_f2(
            self.leds,
            self.matrix,
            self.width,
            self.height,
        )

    def current_center(self) -> tuple[float, float]:
        shape = self.transformed_shape()
        return _centro_rois(shape)

    def translate(self, dx: float, dy: float) -> None:
        adjustment = np.asarray(
            [[1.0, 0.0, float(dx)], [0.0, 1.0, float(dy)]],
            dtype=np.float32,
        )
        self.matrix = _compor_esquerda(adjustment, self.matrix)
        self.schedule_render()

    def rotate(self, angle: float) -> None:
        cx, cy = self.current_center()
        adjustment = cv2.getRotationMatrix2D((cx, cy), float(angle), 1.0).astype(np.float32)
        self.matrix = _compor_esquerda(adjustment, self.matrix)
        self.schedule_render()

    def scale(self, factor: float) -> None:
        cx, cy = self.current_center()
        adjustment = cv2.getRotationMatrix2D((cx, cy), 0.0, float(factor)).astype(np.float32)
        self.matrix = _compor_esquerda(adjustment, self.matrix)
        self.schedule_render()

    def reset(self) -> None:
        self.matrix = self.nominal.copy()
        self.schedule_render()

    def _start_drag(self, event) -> None:
        self._drag_last = (float(event.x), float(event.y))

    def _drag(self, event) -> None:
        if self._drag_last is None:
            return
        x, y = float(event.x), float(event.y)
        last_x, last_y = self._drag_last
        self._drag_last = (x, y)
        scale = max(1e-6, float(self._display_scale))
        self.translate((x - last_x) / scale, (y - last_y) / scale)

    def _stop_drag(self) -> None:
        self._drag_last = None

    def _wheel(self, event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        num = getattr(event, "num", None)
        direction = 1 if delta > 0 or num == 4 else -1
        shift = bool(int(getattr(event, "state", 0) or 0) & 0x0001)
        if shift:
            self.scale(1.01 if direction > 0 else 0.99)
        else:
            self.rotate(1.0 if direction > 0 else -1.0)
        return "break"

    def schedule_render(self) -> None:
        if self._render_after is not None:
            try:
                self.window.after_cancel(self._render_after)
            except Exception:
                pass
        try:
            self._render_after = self.window.after(20, self.render)
        except Exception:
            self._render_after = None

    def render(self) -> None:
        self._render_after = None
        if self.image is None or getattr(self.image, "size", 0) == 0:
            return
        try:
            from src.platform.f2_board_presence_mask_preview_native import (
                desenhar_contorno_placa_na_referencia_f2,
                desenhar_rois_na_referencia_f2,
            )

            decorated, _ = desenhar_rois_na_referencia_f2(
                self.image,
                self.transformed_leds(),
            )
            decorated, _ = desenhar_contorno_placa_na_referencia_f2(
                decorated,
                self.transformed_shape(),
            )
            rgb = cv2.cvtColor(decorated, cv2.COLOR_BGR2RGB)
            canvas_w = max(100, int(self.canvas.winfo_width()))
            canvas_h = max(100, int(self.canvas.winfo_height()))
            h, w = rgb.shape[:2]
            scale = min(canvas_w / float(w), canvas_h / float(h))
            scale = max(0.01, scale)
            display_w = max(1, int(round(w * scale)))
            display_h = max(1, int(round(h * scale)))
            pil = Image.fromarray(rgb).resize((display_w, display_h), Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(pil)
            self._display_scale = scale
            self.canvas.delete("all")
            self.canvas.create_image(
                canvas_w / 2.0,
                canvas_h / 2.0,
                image=self._photo,
                anchor="center",
            )
        except Exception:
            return

    def _shape_inside(self) -> bool:
        transformed = self.transformed_shape()
        if not transformed:
            return False
        try:
            points = np.asarray(pontos_segmento(transformed[0]), dtype=np.float32).reshape(-1, 2)
            if len(points) < 3:
                return False
            return bool(
                np.all(points[:, 0] >= 0)
                and np.all(points[:, 0] < self.width)
                and np.all(points[:, 1] >= 0)
                and np.all(points[:, 1] < self.height)
            )
        except Exception:
            return False

    def save(self) -> None:
        if not self._shape_inside():
            messagebox.showwarning(
                "Contorno fora da imagem",
                "A máscara da placa precisa ficar completamente dentro da imagem antes de salvar.",
                parent=self.window,
            )
            return

        repository = self.app.config_repository
        config = repository.carregar_configuracao_existente_sem_alerta()
        current = obter_referencias_orientacao_projeto(config, self.project).get(
            self.slot,
            {},
        )
        if not current:
            return
        current = dict(current)
        current["canonical_to_reference"] = self.matrix.tolist()
        current["calibrated"] = True
        current["base_shape_updated_at"] = _shape_stamp(self.controller, self.project)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        config = definir_referencia_orientacao_projeto(
            config,
            self.project,
            self.slot,
            current,
        )
        escrever_configuracao(repository, config)
        _invalidar_tracking(self.controller)
        self.close(refresh=True)

    def close(self, refresh: bool = False) -> None:
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


def _open_calibration(controller, slot: str, window) -> None:
    projeto = str(controller.project_name() or "").strip()
    entry = _entries(controller, projeto).get(slot, {}) if projeto else {}
    if not entry:
        messagebox.showwarning(
            "Referência necessária",
            "Capture ou carregue primeiro a imagem desta orientação.",
            parent=window,
        )
        return
    resolution = controller.master_resolution(projeto)
    shape = (
        carregar_contorno_placa_leds(
            controller,
            projeto,
            int(resolution[0]),
            int(resolution[1]),
        )
        if resolution
        else []
    )
    if not shape:
        messagebox.showwarning(
            "Contorno base necessário",
            "Desenhe primeiro a placa em 'Placa fixa ligada' ou 'Placa fixa desligada'. "
            "As orientações 90°/180°/270° reutilizam esse mesmo contorno.",
            parent=window,
        )
        return
    _OrientationCalibrationWindow(controller, slot, window)


def _render_orientation_section(controller, window) -> None:
    if window is None:
        return
    body = _encontrar_corpo_referencias(window)
    if body is None:
        return

    previous = getattr(window, "_odin_f2_orientation_refs_container", None)
    if previous is not None:
        try:
            previous.destroy()
        except Exception:
            pass

    view = controller.app.view
    container = tk.Frame(body, bg=view.COR_CARD_2)
    container.pack(fill=tk.X, padx=12, pady=(0, 14))
    window._odin_f2_orientation_refs_container = container

    tk.Frame(container, bg="#172033", height=1).pack(fill=tk.X, pady=(0, 10))
    tk.Label(
        container,
        text="Referências reais por orientação — rastreamento F2",
        font=("Segoe UI", 10, "bold"),
        fg=view.COR_TEXTO,
        bg=view.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 4))
    tk.Label(
        container,
        text=(
            "Opcional. Capture a mesma placa realmente posicionada em 90°, 180° e 270°. "
            "Depois use 'Desenhar placa' para encaixar o contorno ciano compartilhado. "
            "O ODIN usa essas fotos reais antes das vistas sintéticas para aumentar a precisão das ROIs rastreadas."
        ),
        font=("Segoe UI", 8),
        fg=view.COR_TEXTO_2,
        bg=view.COR_CARD_2,
        wraplength=790,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 9))

    projeto = str(controller.project_name() or "").strip()
    resolution = controller.master_resolution(projeto) if projeto else None
    entries = _entries(controller, projeto) if projeto else normalizar_referencias_orientacao({})
    stamp = _shape_stamp(controller, projeto) if projeto else None
    shape = []
    leds = []
    if projeto and resolution:
        shape = carregar_contorno_placa_leds(
            controller,
            projeto,
            int(resolution[0]),
            int(resolution[1]),
        )
        repository = getattr(controller.app, "config_repository", None)
        getter = getattr(repository, "carregar_leds_fixos", None)
        if callable(getter):
            try:
                leds = list(getter(projeto=projeto) or [])
            except TypeError:
                try:
                    leds = list(getter(projeto) or [])
                except Exception:
                    leds = []
            except Exception:
                leds = []

    grid = tk.Frame(container, bg=view.COR_CARD_2)
    grid.pack(fill=tk.X)
    for column in range(3):
        grid.grid_columnconfigure(column, weight=1, uniform="f2_orientation_refs")

    photos = []
    ready_count = 0
    for column, slot in enumerate(F2_ORIENTATION_SLOTS):
        ui = F2_ORIENTATION_UI[slot]
        entry = entries.get(slot, {})
        calibrated = referencia_orientacao_calibrada(entry, stamp)
        if calibrated:
            ready_count += 1
        card = tk.Frame(
            grid,
            bg=view.COR_CARD,
            highlightthickness=1,
            highlightbackground=view.COR_BORDA,
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0 if column == 0 else 5, 0 if column == 2 else 5),
        )
        tk.Label(
            card,
            text=ui["title"],
            font=("Segoe UI", 8, "bold"),
            fg=ui["color"],
            bg=view.COR_CARD,
            anchor="w",
        ).pack(fill=tk.X, padx=7, pady=(7, 4))

        preview = tk.Frame(card, bg="#020617", height=112)
        preview.pack(fill=tk.X, padx=7)
        preview.pack_propagate(False)
        image = cv2.imread(str(entry.get("image_path") or "")) if entry else None
        preview_image = image
        matrix = matriz_orientacao_np(entry)
        if image is not None and matrix is not None and shape:
            try:
                from src.platform.f2_board_presence_mask_preview_native import (
                    desenhar_contorno_placa_na_referencia_f2,
                    desenhar_rois_na_referencia_f2,
                )

                transformed_leds = transformar_rois_para_frame_atual_f2(
                    leds,
                    matrix,
                    image.shape[1],
                    image.shape[0],
                )
                transformed_shape = transformar_rois_para_frame_atual_f2(
                    shape,
                    matrix,
                    image.shape[1],
                    image.shape[0],
                )
                preview_image, _ = desenhar_rois_na_referencia_f2(
                    preview_image,
                    transformed_leds,
                )
                preview_image, _ = desenhar_contorno_placa_na_referencia_f2(
                    preview_image,
                    transformed_shape,
                )
            except Exception:
                preview_image = image

        photo = _criar_photo_preview(preview_image, largura_max=180, altura_max=104)
        if photo is not None:
            photos.append(photo)
            tk.Label(preview, image=photo, bg="#020617", bd=0).pack(
                fill=tk.BOTH,
                expand=True,
            )
        else:
            tk.Label(
                preview,
                text="SEM IMAGEM",
                font=("Segoe UI", 8, "bold"),
                fg=view.COR_TEXTO_3,
                bg="#020617",
            ).pack(fill=tk.BOTH, expand=True)

        if calibrated:
            status_text = "CALIBRADA"
            status_color = "#86EFAC"
        elif entry and shape:
            status_text = "AJUSTE O CONTORNO"
            status_color = "#FBBF24"
        elif entry:
            status_text = "FALTA CONTORNO BASE"
            status_color = "#FBBF24"
        else:
            status_text = "OPCIONAL"
            status_color = view.COR_TEXTO_3
        tk.Label(
            card,
            text=status_text,
            font=("Segoe UI", 7, "bold"),
            fg=status_color,
            bg=view.COR_CARD,
            anchor="w",
        ).pack(fill=tk.X, padx=7, pady=(4, 0))

        state = tk.NORMAL if projeto and resolution is not None else tk.DISABLED
        actions = tk.Frame(card, bg=view.COR_CARD)
        actions.pack(fill=tk.X, padx=7, pady=6)
        tk.Button(
            actions,
            text="Capturar câmera",
            state=state,
            command=lambda s=slot, w=window: _capture_orientation(controller, s, w),
            font=("Segoe UI", 7, "bold"),
            bg=view.COR_CARD_2,
            fg=view.COR_TEXTO,
            disabledforeground=view.COR_TEXTO_3,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=5,
            pady=4,
        ).pack(fill=tk.X)
        tk.Button(
            actions,
            text="Carregar imagem",
            state=state,
            command=lambda s=slot, w=window: _load_orientation(controller, s, w),
            font=("Segoe UI", 7),
            bg=view.COR_CARD_2,
            fg=view.COR_TEXTO_2,
            disabledforeground=view.COR_TEXTO_3,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=5,
            pady=3,
        ).pack(fill=tk.X, pady=(3, 0))
        if entry:
            tk.Button(
                actions,
                text="Remover",
                command=lambda s=slot, w=window: _remove_orientation(controller, s, w),
                font=("Segoe UI", 7),
                bg=view.COR_CARD,
                fg="#FCA5A5",
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                padx=5,
                pady=3,
            ).pack(fill=tk.X, pady=(3, 0))
        draw_state = (
            tk.NORMAL
            if projeto and resolution is not None and bool(entry) and bool(shape)
            else tk.DISABLED
        )
        tk.Button(
            actions,
            text="Desenhar placa",
            state=draw_state,
            command=lambda s=slot, w=window: _open_calibration(controller, s, w),
            font=("Segoe UI", 7, "bold"),
            bg="#0F2B3A",
            fg="#7DD3FC",
            disabledforeground=view.COR_TEXTO_3,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=5,
            pady=4,
        ).pack(fill=tk.X, pady=(3, 0))

    window._odin_f2_orientation_refs_preview_tk = photos
    tk.Label(
        container,
        text=(
            f"Rastreamento angular real: {ready_count}/3 referências calibradas. "
            "Slots ausentes continuam usando o fallback sintético existente."
        ),
        font=("Segoe UI", 8, "bold"),
        fg="#86EFAC" if ready_count == 3 else "#FBBF24",
        bg=view.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, pady=(8, 0))

    try:
        window.update_idletasks()
    except Exception:
        pass


def instalar_ui_referencias_reais_orientacao_f2() -> None:
    """Anexa os três slots ao renderer F2 já instalado, sem tocar no F3."""
    global _PATCH_UI_INSTALADO
    if _PATCH_UI_INSTALADO:
        return
    instalar_preservacao_referencias_orientacao_f2()

    atual = F2BoardPresenceReferenceController.render_settings
    if bool(getattr(atual, "_odin_f2_orientation_ui", False)):
        _PATCH_UI_INSTALADO = True
        return
    anterior = atual

    def render_com_orientacoes(self, window):
        resultado = anterior(self, window)
        try:
            _render_orientation_section(self, window)
        except Exception:
            pass
        return resultado

    render_com_orientacoes._odin_f2_orientation_ui = True
    render_com_orientacoes._odin_f2_orientation_ui_base = anterior
    F2BoardPresenceReferenceController.render_settings = render_com_orientacoes
    _PATCH_UI_INSTALADO = True


instalar_preservacao_referencias_orientacao_f2()
