from __future__ import annotations

import base64
import queue
import sys
import threading
import time
import tkinter as tk

import cv2

from src.platform.camera_selection import (
    CAMERA_SELECTOR_MAX_PREVIEWS,
    CAMERA_SELECTOR_PREVIEW_HEIGHT,
    CAMERA_SELECTOR_PREVIEW_WIDTH,
    CAMERA_SELECTOR_REFRESH_MS,
    CAMERA_SELECTOR_RELEASE_GRACE_MS,
    CAMERA_SELECTOR_SCAN_MAX_INDEX,
    abrir_camera_preview,
)


SELECTOR_WINDOW_WIDTH = 920
SELECTOR_WINDOW_HEIGHT = 520
SELECTOR_LOADING_MS = 320
SELECTOR_RELEASE_WAIT_MAX_MS = 2200
# No Windows, dê tempo para selecionar a primeira câmera já comprovada antes
# de iniciar um VideoCapture potencialmente bloqueante em outro índice.
CAMERA_SELECTOR_WINDOWS_FIRST_CHOICE_GRACE_S = 1.2


def _codificar_preview(frame) -> str | None:
    """Prepara o PNG fora da thread gráfica do Tkinter."""
    if frame is None or getattr(frame, "size", 0) <= 0:
        return None
    altura, largura = frame.shape[:2]
    if largura <= 0 or altura <= 0:
        return None

    escala = min(
        CAMERA_SELECTOR_PREVIEW_WIDTH / float(largura),
        CAMERA_SELECTOR_PREVIEW_HEIGHT / float(altura),
    )
    largura_final = max(1, int(round(largura * escala)))
    altura_final = max(1, int(round(altura * escala)))
    interpolacao = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR
    reduzida = cv2.resize(
        frame,
        (largura_final, altura_final),
        interpolation=interpolacao,
    )
    sucesso, buffer = cv2.imencode(".png", reduzida)
    if not sucesso:
        return None
    return base64.b64encode(buffer).decode("ascii")


def executar_busca_camera_em_background(
    stop_event: threading.Event,
    eventos: queue.Queue,
    previews: dict[int, str],
    previews_lock: threading.RLock,
    released_event: threading.Event,
) -> None:
    """Mantém VideoCapture/open/read completamente fora do event loop do Tk."""
    captures: dict[int, object] = {}
    try:
        for indice in range(CAMERA_SELECTOR_SCAN_MAX_INDEX + 1):
            if stop_event.is_set() or len(captures) >= CAMERA_SELECTOR_MAX_PREVIEWS:
                break

            eventos.put(("testando", int(indice)))
            capture, backend, primeiro_frame = abrir_camera_preview(indice)

            if stop_event.is_set():
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        pass
                break

            if capture is None:
                continue

            captures[int(indice)] = capture
            dados = _codificar_preview(primeiro_frame)
            if dados is not None:
                with previews_lock:
                    previews[int(indice)] = dados
            eventos.put((
                "encontrada",
                int(indice),
                str(backend or ""),
                (int(primeiro_frame.shape[1]), int(primeiro_frame.shape[0])),
            ))
            if (
                sys.platform.startswith("win")
                and len(captures) == 1
                and stop_event.wait(CAMERA_SELECTOR_WINDOWS_FIRST_CHOICE_GRACE_S)
            ):
                break

        eventos.put(("concluida", len(captures)))

        while captures and not stop_event.is_set():
            inicio = time.monotonic()
            for indice, capture in tuple(captures.items()):
                if stop_event.is_set():
                    break
                try:
                    sucesso, frame = capture.read()
                except Exception:
                    sucesso, frame = False, None
                if not sucesso or frame is None or getattr(frame, "size", 0) <= 0:
                    continue

                dados = _codificar_preview(frame)
                if dados is not None:
                    with previews_lock:
                        previews[int(indice)] = dados

            # O seletor não precisa renderizar duas câmeras a 30/60 FPS.
            # Limitamos o trabalho para manter CPU disponível para o ODIN.
            decorrido = time.monotonic() - inicio
            stop_event.wait(max(0.01, 0.075 - decorrido))
    finally:
        for capture in tuple(captures.values()):
            try:
                capture.release()
            except Exception:
                pass
        released_event.set()


class ResponsiveCameraSelectionMixin:
    """Interface não bloqueante para escolher câmera com previews ao vivo."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._selector_worker_thread = None
        self._selector_stop_event = None
        self._selector_released_event = None
        self._selector_event_queue = None
        self._selector_latest_previews: dict[int, str] = {}
        self._selector_previews_lock = threading.RLock()
        self._selector_loading_after_id = None
        self._selector_loading_frame = None
        self._selector_loading_label = None
        self._selector_status_label = None
        self._selector_frame_previews = None

    def abrir_seletor_camera(self, ao_selecionar=None) -> None:
        janela_existente = getattr(self, "_camera_selector_window", None)
        if janela_existente is not None:
            try:
                if janela_existente.winfo_exists():
                    janela_existente.lift()
                    janela_existente.focus_force()
                    return
            except tk.TclError:
                pass

        janela = tk.Toplevel(self.root)
        self._camera_selector_window = janela
        janela.title("Selecionar câmera")
        janela.configure(bg="#07111F")
        janela.transient(self.root)
        janela.resizable(False, False)
        janela.grab_set()

        pos_x = self.root.winfo_rootx() + max(
            0,
            (self.root.winfo_width() - SELECTOR_WINDOW_WIDTH) // 2,
        )
        pos_y = self.root.winfo_rooty() + max(
            0,
            (self.root.winfo_height() - SELECTOR_WINDOW_HEIGHT) // 2,
        )
        janela.geometry(
            f"{SELECTOR_WINDOW_WIDTH}x{SELECTOR_WINDOW_HEIGHT}+{pos_x}+{pos_y}"
        )

        tk.Label(
            janela,
            text="Selecionar câmera para o ODIN",
            font=("Segoe UI", 17, "bold"),
            fg="#F9FAFB",
            bg="#07111F",
        ).pack(anchor="w", padx=24, pady=(20, 3))
        tk.Label(
            janela,
            text=(
                "Compare as imagens ao vivo e escolha a câmera que será usada "
                "na parametrização e na produção."
            ),
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#07111F",
        ).pack(anchor="w", padx=24, pady=(0, 12))

        frame_previews = tk.Frame(janela, bg="#07111F")
        frame_previews.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 8))
        self._selector_frame_previews = frame_previews

        loading = tk.Frame(
            frame_previews,
            bg="#0B1728",
            highlightthickness=1,
            highlightbackground="#253247",
        )
        loading.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)
        self._selector_loading_frame = loading

        loading_label = tk.Label(
            loading,
            text="CARREGANDO CÂMERAS",
            font=("Segoe UI", 12, "bold"),
            fg="#E2E8F0",
            bg="#0B1728",
        )
        loading_label.pack(expand=True, pady=(65, 4))
        self._selector_loading_label = loading_label

        tk.Label(
            loading,
            text=(
                "O Windows está inicializando os dispositivos de vídeo.\n"
                "A interface continua disponível enquanto isso."
            ),
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#0B1728",
            justify=tk.CENTER,
        ).pack(pady=(0, 65))

        status = tk.Label(
            janela,
            text="Inicializando dispositivos de vídeo...",
            font=("Segoe UI", 9, "bold"),
            fg="#94A3B8",
            bg="#07111F",
            anchor="w",
        )
        status.pack(fill=tk.X, padx=24, pady=(0, 8))
        self._selector_status_label = status

        rodape = tk.Frame(janela, bg="#07111F")
        rodape.pack(fill=tk.X, padx=24, pady=(0, 18))
        tk.Button(
            rodape,
            text="Cancelar",
            command=self._fechar_seletor_camera,
            font=("Segoe UI", 10, "bold"),
            bg="#1F2937",
            fg="#E5E7EB",
            activebackground="#374151",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            padx=22,
            pady=10,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        janela.protocol("WM_DELETE_WINDOW", self._fechar_seletor_camera)
        janela.bind("<Escape>", lambda _event: self._fechar_seletor_camera())

        self._camera_selector_cards = {}
        self._camera_selector_captures = {}
        self._selector_latest_previews = {}
        self._selector_preview_resolutions = {}
        self._selector_event_queue = queue.Queue()
        self._selector_stop_event = threading.Event()
        self._selector_released_event = threading.Event()

        self._animar_loading_camera(0)
        self._camera_selector_after_id = janela.after(
            40,
            lambda: self._processar_eventos_camera(ao_selecionar),
        )

        worker = threading.Thread(
            target=executar_busca_camera_em_background,
            args=(
                self._selector_stop_event,
                self._selector_event_queue,
                self._selector_latest_previews,
                self._selector_previews_lock,
                self._selector_released_event,
            ),
            name="odin-camera-selector",
            daemon=True,
        )
        self._selector_worker_thread = worker
        worker.start()

    def _animar_loading_camera(self, passo: int) -> None:
        janela = getattr(self, "_camera_selector_window", None)
        label = self._selector_loading_label
        if janela is None or label is None:
            return
        try:
            if not janela.winfo_exists() or not label.winfo_exists():
                return
            label.configure(text="CARREGANDO CÂMERAS" + "." * ((passo % 3) + 1))
            self._selector_loading_after_id = janela.after(
                SELECTOR_LOADING_MS,
                lambda: self._animar_loading_camera(passo + 1),
            )
        except tk.TclError:
            self._selector_loading_after_id = None

    def _remover_loading_camera(self) -> None:
        janela = getattr(self, "_camera_selector_window", None)
        if janela is not None and self._selector_loading_after_id is not None:
            try:
                janela.after_cancel(self._selector_loading_after_id)
            except Exception:
                pass
        self._selector_loading_after_id = None

        frame = self._selector_loading_frame
        self._selector_loading_frame = None
        self._selector_loading_label = None
        if frame is not None:
            try:
                if frame.winfo_exists():
                    frame.destroy()
            except tk.TclError:
                pass

    def _processar_eventos_camera(self, ao_selecionar) -> None:
        janela = getattr(self, "_camera_selector_window", None)
        if janela is None:
            return
        try:
            if not janela.winfo_exists():
                return
        except tk.TclError:
            return

        eventos = self._selector_event_queue
        if eventos is not None:
            while True:
                try:
                    evento = eventos.get_nowait()
                except queue.Empty:
                    break

                tipo = evento[0]
                if tipo == "testando":
                    self._status_camera(
                        f"Detectando câmera {int(evento[1])}... A interface continua responsiva.",
                        "#94A3B8",
                    )
                elif tipo == "encontrada":
                    indice = int(evento[1])
                    backend = str(evento[2] or "")
                    if len(evento) >= 4:
                        self._selector_preview_resolutions[indice] = tuple(evento[3])
                    if indice not in self._camera_selector_cards:
                        self._remover_loading_camera()
                        self._criar_card_camera_responsivo(
                            indice,
                            backend,
                            ao_selecionar,
                        )
                elif tipo == "concluida":
                    total = int(evento[1])
                    if total <= 0:
                        self._mostrar_sem_camera()
                    else:
                        self._status_camera(
                            f"{total} câmera(s) disponível(is). Escolha uma opção.",
                            "#86EFAC",
                        )

        with self._selector_previews_lock:
            previews = dict(self._selector_latest_previews)
            self._selector_latest_previews.clear()
        for indice, dados in previews.items():
            self._desenhar_preview_codificado(indice, dados)

        self._camera_selector_after_id = janela.after(
            CAMERA_SELECTOR_REFRESH_MS,
            lambda: self._processar_eventos_camera(ao_selecionar),
        )

    def _status_camera(self, texto: str, cor: str) -> None:
        label = self._selector_status_label
        if label is None:
            return
        try:
            label.configure(text=texto, fg=cor)
        except tk.TclError:
            pass

    def _mostrar_sem_camera(self) -> None:
        janela = getattr(self, "_camera_selector_window", None)
        if janela is not None and self._selector_loading_after_id is not None:
            try:
                janela.after_cancel(self._selector_loading_after_id)
            except Exception:
                pass
        self._selector_loading_after_id = None
        label = self._selector_loading_label
        if label is not None:
            try:
                label.configure(
                    text="NENHUMA CÂMERA ENCONTRADA",
                    fg="#FCA5A5",
                )
            except tk.TclError:
                pass
        self._status_camera(
            "Nenhuma câmera disponível foi encontrada nos índices 0 a 3.",
            "#FCA5A5",
        )

    def _criar_card_camera_responsivo(
        self,
        indice: int,
        backend: str,
        ao_selecionar,
    ) -> None:
        parent = self._selector_frame_previews
        if parent is None:
            return

        card = tk.Frame(
            parent,
            bg="#0B1728",
            highlightthickness=1,
            highlightbackground="#253247",
        )
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=2)

        topo = tk.Frame(card, bg="#0B1728")
        topo.pack(fill=tk.X, padx=12, pady=(10, 7))
        tk.Label(
            topo,
            text=f"CÂMERA {indice}",
            font=("Segoe UI", 11, "bold"),
            fg="#F9FAFB",
            bg="#0B1728",
        ).pack(side=tk.LEFT)
        tk.Label(
            topo,
            text=backend,
            font=("Segoe UI", 8),
            fg="#94A3B8",
            bg="#0B1728",
        ).pack(side=tk.RIGHT)

        canvas = tk.Canvas(
            card,
            width=CAMERA_SELECTOR_PREVIEW_WIDTH,
            height=CAMERA_SELECTOR_PREVIEW_HEIGHT,
            bg="#020617",
            bd=0,
            highlightthickness=1,
            highlightbackground="#334155",
        )
        canvas.pack(padx=12)
        canvas.create_text(
            CAMERA_SELECTOR_PREVIEW_WIDTH / 2,
            CAMERA_SELECTOR_PREVIEW_HEIGHT / 2,
            text="Aguardando imagem...",
            fill="#64748B",
            font=("Segoe UI", 9, "bold"),
        )

        botao = tk.Button(
            card,
            text=f"SELECIONAR CÂMERA {indice}",
            command=lambda i=indice: self._confirmar_camera_selecionada(
                i,
                ao_selecionar,
            ),
            font=("Segoe UI", 11, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            padx=18,
            pady=12,
            cursor="hand2",
        )
        botao.pack(fill=tk.X, padx=12, pady=(10, 12))

        self._camera_selector_cards[indice] = {
            "canvas": canvas,
            "photo": None,
            "button": botao,
        }

    def _desenhar_preview_codificado(self, indice: int, dados: str) -> None:
        card = self._camera_selector_cards.get(int(indice))
        if not card or not dados:
            return
        try:
            photo = tk.PhotoImage(data=dados)
        except tk.TclError:
            return

        canvas = card["canvas"]
        card["photo"] = photo
        try:
            canvas.delete("all")
            x = (CAMERA_SELECTOR_PREVIEW_WIDTH - int(photo.width())) / 2.0
            y = (CAMERA_SELECTOR_PREVIEW_HEIGHT - int(photo.height())) / 2.0
            canvas.create_image(x, y, image=photo, anchor="nw")
        except tk.TclError:
            pass

    def _atualizar_previews_seletor_camera(self) -> None:
        """Compatibilidade: nunca lê VideoCapture na thread gráfica."""
        with self._selector_previews_lock:
            previews = dict(self._selector_latest_previews)
            self._selector_latest_previews.clear()
        for indice, dados in previews.items():
            self._desenhar_preview_codificado(indice, dados)

    def _confirmar_camera_selecionada(self, indice: int, callback=None) -> None:
        self.indice_camera_selecionada = int(indice)
        released_event = self._selector_released_event
        self._fechar_seletor_camera()

        try:
            self.view.atualizar_status(
                f"Câmera {indice} selecionada. Liberando preview..."
            )
        except Exception:
            pass

        if callback is None:
            return

        def continuar(espera_ms: int = 0) -> None:
            liberada = released_event is None or released_event.is_set()
            limite = espera_ms >= SELECTOR_RELEASE_WAIT_MAX_MS
            if liberada or limite:
                try:
                    self.view.atualizar_status(
                        f"Câmera {indice} selecionada para esta sessão."
                    )
                except Exception:
                    pass
                callback(int(indice))
                return
            self.root.after(50, lambda: continuar(espera_ms + 50))

        # Esperar nunca bloqueia a UI: são apenas callbacks curtos via after().
        self.root.after(CAMERA_SELECTOR_RELEASE_GRACE_MS, continuar)

    def _fechar_seletor_camera(self) -> None:
        janela = getattr(self, "_camera_selector_window", None)

        if janela is not None and getattr(self, "_camera_selector_after_id", None) is not None:
            try:
                janela.after_cancel(self._camera_selector_after_id)
            except Exception:
                pass
        self._camera_selector_after_id = None

        if janela is not None and self._selector_loading_after_id is not None:
            try:
                janela.after_cancel(self._selector_loading_after_id)
            except Exception:
                pass
        self._selector_loading_after_id = None

        # release()/join() podem bloquear no driver USB. Apenas sinalizamos o
        # worker; ele encerra e libera os handles fora da thread do Tkinter.
        stop_event = self._selector_stop_event
        if stop_event is not None:
            stop_event.set()

        self._camera_selector_cards = {}
        self._camera_selector_captures = {}
        self._selector_preview_resolutions = {}
        self._selector_status_label = None
        self._selector_loading_frame = None
        self._selector_loading_label = None
        self._selector_frame_previews = None
        self._selector_event_queue = None
        self._selector_stop_event = None
        self._selector_worker_thread = None
        with self._selector_previews_lock:
            self._selector_latest_previews.clear()

        self._camera_selector_window = None
        if janela is not None:
            try:
                if janela.winfo_exists():
                    janela.grab_release()
                    janela.destroy()
            except tk.TclError:
                pass
