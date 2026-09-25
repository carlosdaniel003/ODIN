from __future__ import annotations

import base64
import sys
import tkinter as tk

import cv2


CAMERA_SELECTOR_SCAN_MAX_INDEX = 3
CAMERA_SELECTOR_MAX_PREVIEWS = 2
CAMERA_SELECTOR_PREVIEW_WIDTH = 400
CAMERA_SELECTOR_PREVIEW_HEIGHT = 225
CAMERA_SELECTOR_REFRESH_MS = 70
CAMERA_SELECTOR_PROBE_WIDTH = 640
CAMERA_SELECTOR_PROBE_HEIGHT = 360
CAMERA_SELECTOR_PROBE_FPS = 15
CAMERA_SELECTOR_PROBE_FRAMES = 8
CAMERA_SELECTOR_RELEASE_GRACE_MS = 300


_CAMERA_STRICT_CLASS_CACHE: dict[type, type] = {}


def camera_backends_preferidos(plataforma: str | None = None):
    plataforma = str(plataforma or sys.platform).lower()
    if plataforma.startswith("win"):
        # O Windows moderno usa Media Foundation como caminho nativo para
        # dispositivos de câmera. Tentamos esse backend primeiro e deixamos
        # DirectShow apenas como fallback para webcams antigas.
        return (
            (cv2.CAP_MSMF, "Media Foundation"),
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_ANY, "Automático"),
        )
    if plataforma.startswith("linux"):
        return (
            (cv2.CAP_V4L2, "V4L2"),
            (cv2.CAP_ANY, "Automático"),
        )
    return ((cv2.CAP_ANY, "Automático"),)


def _configurar_capture_preview(
    capture,
    plataforma: str | None = None,
) -> None:
    plataforma = str(plataforma or sys.platform).lower()

    # No Windows não forçamos FOURCC, resolução nem FPS na descoberta. O
    # driver negocia exatamente como ocorre nas APIs nativas do sistema. Isso
    # evita que uma câmera USB que funciona no app Configurações seja rejeitada
    # só porque não aceitou MJPG 640x360 durante o probe.
    if not plataforma.startswith("win"):
        try:
            capture.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"),
            )
        except Exception:
            pass
        for propriedade, valor in (
            (cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SELECTOR_PROBE_WIDTH),
            (cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SELECTOR_PROBE_HEIGHT),
            (cv2.CAP_PROP_FPS, CAMERA_SELECTOR_PROBE_FPS),
        ):
            try:
                capture.set(propriedade, valor)
            except Exception:
                pass

    try:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass


def abrir_camera_preview(indice: int):
    indice = int(indice)
    for backend, nome_backend in camera_backends_preferidos():
        capture = None
        try:
            capture = cv2.VideoCapture(indice, backend)
        except Exception:
            capture = None

        if capture is None or not capture.isOpened():
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            continue

        _configurar_capture_preview(capture)
        frame_valido = None
        for _ in range(CAMERA_SELECTOR_PROBE_FRAMES):
            try:
                sucesso, frame = capture.read()
            except Exception:
                sucesso, frame = False, None
            if sucesso and frame is not None and getattr(frame, "size", 0) > 0:
                frame_valido = frame
                break

        if frame_valido is None:
            try:
                capture.release()
            except Exception:
                pass
            continue

        return capture, nome_backend, frame_valido

    return None, None, None


def criar_photo_preview_camera(frame):
    if frame is None or getattr(frame, "size", 0) == 0:
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
    dados = base64.b64encode(buffer).decode("ascii")
    return tk.PhotoImage(data=dados)


def criar_classe_camera_indice_estrito(classe_base: type) -> type:
    classe_original = getattr(
        classe_base,
        "_odin_camera_selector_base_class",
        classe_base,
    )
    if classe_original in _CAMERA_STRICT_CLASS_CACHE:
        return _CAMERA_STRICT_CLASS_CACHE[classe_original]

    class CameraServiceIndiceEstrito(classe_original):
        _odin_camera_selector_base_class = classe_original
        _odin_camera_selector_strict = True

        def _indices_candidatos(self):
            indice = int(
                getattr(
                    self,
                    "_indice_camera_solicitado",
                    getattr(self, "indice_camera", 0),
                )
            )
            return (indice,)

        def _candidatos_linux(self):
            candidatos = super()._candidatos_linux()
            indice = int(
                getattr(
                    self,
                    "_indice_camera_solicitado",
                    getattr(self, "indice_camera", 0),
                )
            )
            return tuple(
                candidato
                for candidato in candidatos
                if getattr(candidato, "indice", None) is not None
                and int(candidato.indice) == indice
            )

    CameraServiceIndiceEstrito.__name__ = (
        f"{classe_original.__name__}IndiceEstrito"
    )
    CameraServiceIndiceEstrito.__qualname__ = (
        CameraServiceIndiceEstrito.__name__
    )
    _CAMERA_STRICT_CLASS_CACHE[classe_original] = CameraServiceIndiceEstrito
    return CameraServiceIndiceEstrito


class CameraSelectionMixin:
    """Escolhe visualmente a câmera antes de iniciar parametrização/operação."""

    def __init__(self, *args, **kwargs) -> None:
        self.indice_camera_selecionada: int | None = None
        self._camera_selector_window = None
        self._camera_selector_captures: dict[int, object] = {}
        self._camera_selector_after_id = None
        self._camera_selector_cards: dict[int, dict] = {}
        self._camera_service_base_selecao = None
        super().__init__(*args, **kwargs)

    def alternar_tela_ao_vivo(self) -> None:
        if getattr(self, "camera_ativa", False):
            super().alternar_tela_ao_vivo()
            return
        self.abrir_seletor_camera(
            ao_selecionar=lambda _indice: self.iniciar_tela_ao_vivo()
        )

    def abrir_tela_operacao(self) -> None:
        if getattr(self, "camera_ativa", False):
            super().abrir_tela_operacao()
            return

        def abrir_apos_escolha(_indice: int) -> None:
            super(CameraSelectionMixin, self).abrir_tela_operacao()

        self.abrir_seletor_camera(ao_selecionar=abrir_apos_escolha)

    def iniciar_tela_ao_vivo(self) -> None:
        indice = self.indice_camera_selecionada
        if indice is None:
            indice = 0
            self.indice_camera_selecionada = indice

        self._preparar_camera_selecionada_estrita(indice)
        super().iniciar_tela_ao_vivo()

    def _preparar_camera_selecionada_estrita(self, indice: int) -> None:
        if self._camera_service_base_selecao is None:
            atual = getattr(self, "CAMERA_SERVICE_CLASS", None)
            if atual is None:
                raise RuntimeError("Composição desktop sem CAMERA_SERVICE_CLASS.")
            self._camera_service_base_selecao = getattr(
                atual,
                "_odin_camera_selector_base_class",
                atual,
            )

        classe_estrita = criar_classe_camera_indice_estrito(
            self._camera_service_base_selecao
        )
        self.CAMERA_SERVICE_CLASS = classe_estrita
        self.indice_camera_selecionada = int(indice)

    def abrir_seletor_camera(self, ao_selecionar=None) -> None:
        janela_existente = self._camera_selector_window
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

        largura_janela = 900
        altura_janela = 390
        pos_x = self.root.winfo_rootx() + max(
            0,
            (self.root.winfo_width() - largura_janela) // 2,
        )
        pos_y = self.root.winfo_rooty() + max(
            0,
            (self.root.winfo_height() - altura_janela) // 2,
        )
        janela.geometry(
            f"{largura_janela}x{altura_janela}+{pos_x}+{pos_y}"
        )

        tk.Label(
            janela,
            text="Selecionar câmera para o ODIN",
            font=("Segoe UI", 16, "bold"),
            fg="#F9FAFB",
            bg="#07111F",
        ).pack(anchor="w", padx=22, pady=(18, 3))
        tk.Label(
            janela,
            text=(
                "Compare as imagens ao vivo e escolha a câmera que será usada "
                "na parametrização e na produção."
            ),
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#07111F",
        ).pack(anchor="w", padx=22, pady=(0, 12))

        frame_previews = tk.Frame(janela, bg="#07111F")
        frame_previews.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 12))

        status = tk.Label(
            janela,
            text="Procurando câmeras disponíveis...",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#07111F",
            anchor="w",
        )
        status.pack(fill=tk.X, padx=22, pady=(0, 6))

        frame_rodape = tk.Frame(janela, bg="#07111F")
        frame_rodape.pack(fill=tk.X, padx=22, pady=(0, 16))
        tk.Button(
            frame_rodape,
            text="Cancelar",
            command=self._fechar_seletor_camera,
            font=("Segoe UI", 9, "bold"),
            bg="#1F2937",
            fg="#E5E7EB",
            activebackground="#374151",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        janela.protocol("WM_DELETE_WINDOW", self._fechar_seletor_camera)
        janela.bind("<Escape>", lambda _event: self._fechar_seletor_camera())

        self._camera_selector_captures = {}
        self._camera_selector_cards = {}

        def iniciar_busca() -> None:
            disponiveis = []
            for indice in range(CAMERA_SELECTOR_SCAN_MAX_INDEX + 1):
                if len(disponiveis) >= CAMERA_SELECTOR_MAX_PREVIEWS:
                    break
                capture, backend, primeiro_frame = abrir_camera_preview(indice)
                if capture is None:
                    continue
                disponiveis.append((indice, capture, backend, primeiro_frame))

            if not disponiveis:
                status.configure(
                    text="Nenhuma câmera disponível foi encontrada nos índices 0 a 3.",
                    fg="#FCA5A5",
                )
                tk.Label(
                    frame_previews,
                    text="NENHUMA CÂMERA DISPONÍVEL",
                    font=("Segoe UI", 11, "bold"),
                    fg="#FCA5A5",
                    bg="#07111F",
                ).pack(expand=True)
                return

            status.configure(
                text=(
                    f"{len(disponiveis)} câmera(s) disponível(is). "
                    "Selecione pelo preview."
                ),
                fg="#86EFAC",
            )

            for indice, capture, backend, primeiro_frame in disponiveis:
                self._camera_selector_captures[indice] = capture
                self._criar_card_camera(
                    frame_previews,
                    indice,
                    backend,
                    primeiro_frame,
                    ao_selecionar,
                )

            self._atualizar_previews_seletor_camera()

        janela.after(40, iniciar_busca)

    def _criar_card_camera(
        self,
        parent,
        indice: int,
        backend: str,
        primeiro_frame,
        ao_selecionar,
    ) -> None:
        card = tk.Frame(
            parent,
            bg="#0B1728",
            highlightthickness=1,
            highlightbackground="#253247",
        )
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6)

        topo = tk.Frame(card, bg="#0B1728")
        topo.pack(fill=tk.X, padx=10, pady=(8, 5))
        tk.Label(
            topo,
            text=f"CÂMERA {indice}",
            font=("Segoe UI", 10, "bold"),
            fg="#F9FAFB",
            bg="#0B1728",
        ).pack(side=tk.LEFT)
        tk.Label(
            topo,
            text=str(backend or ""),
            font=("Segoe UI", 7),
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
        canvas.pack(padx=10)

        botao = tk.Button(
            card,
            text=f"Usar câmera {indice}",
            command=lambda i=indice: self._confirmar_camera_selecionada(
                i,
                ao_selecionar,
            ),
            font=("Segoe UI", 9, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=12,
            pady=7,
            cursor="hand2",
        )
        botao.pack(fill=tk.X, padx=10, pady=(7, 9))

        self._camera_selector_cards[indice] = {
            "canvas": canvas,
            "photo": None,
        }
        self._desenhar_frame_camera_no_card(indice, primeiro_frame)

    def _desenhar_frame_camera_no_card(self, indice: int, frame) -> None:
        card = self._camera_selector_cards.get(int(indice))
        if not card:
            return
        canvas = card["canvas"]
        photo = criar_photo_preview_camera(frame)
        if photo is None:
            return
        card["photo"] = photo
        canvas.delete("all")
        largura = int(photo.width())
        altura = int(photo.height())
        x = (CAMERA_SELECTOR_PREVIEW_WIDTH - largura) / 2.0
        y = (CAMERA_SELECTOR_PREVIEW_HEIGHT - altura) / 2.0
        canvas.create_image(x, y, image=photo, anchor="nw")

    def _atualizar_previews_seletor_camera(self) -> None:
        janela = self._camera_selector_window
        if janela is None:
            return
        try:
            if not janela.winfo_exists():
                return
        except tk.TclError:
            return

        for indice, capture in tuple(self._camera_selector_captures.items()):
            try:
                sucesso, frame = capture.read()
            except Exception:
                sucesso, frame = False, None
            if sucesso and frame is not None and getattr(frame, "size", 0) > 0:
                self._desenhar_frame_camera_no_card(indice, frame)

        self._camera_selector_after_id = janela.after(
            CAMERA_SELECTOR_REFRESH_MS,
            self._atualizar_previews_seletor_camera,
        )

    def _confirmar_camera_selecionada(self, indice: int, callback=None) -> None:
        self.indice_camera_selecionada = int(indice)
        self._fechar_seletor_camera()
        try:
            self.view.atualizar_status(
                f"Câmera {indice} selecionada para esta sessão."
            )
        except Exception:
            pass
        if callback is not None:
            # Algumas câmeras USB precisam de alguns centenas de milissegundos
            # para o Windows liberar o handle usado pela preview. Reabrir em
            # apenas 20 ms podia iniciar exatamente o ciclo conecta/reconecta.
            self.root.after(
                CAMERA_SELECTOR_RELEASE_GRACE_MS,
                lambda: callback(int(indice)),
            )

    def _fechar_seletor_camera(self) -> None:
        janela = self._camera_selector_window
        if janela is not None and self._camera_selector_after_id is not None:
            try:
                janela.after_cancel(self._camera_selector_after_id)
            except Exception:
                pass
        self._camera_selector_after_id = None

        for capture in tuple(self._camera_selector_captures.values()):
            try:
                capture.release()
            except Exception:
                pass
        self._camera_selector_captures = {}
        self._camera_selector_cards = {}

        self._camera_selector_window = None
        if janela is not None:
            try:
                if janela.winfo_exists():
                    janela.grab_release()
                    janela.destroy()
            except tk.TclError:
                pass
