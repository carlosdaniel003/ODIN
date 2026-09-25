from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time


_TRUE_VALUES = {"1", "true", "yes", "on", "sim"}
_LOG_LOCK = threading.RLock()
_PATCH_INSTALADO = False


def camera_debug_enabled() -> bool:
    """Ativa diagnóstico somente no Windows e mediante variável de ambiente."""
    if not sys.platform.startswith("win"):
        return False
    valor = str(os.environ.get("ODIN_CAMERA_DEBUG", "")).strip().lower()
    return valor in _TRUE_VALUES


def _normalizar_valor(valor):
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, (tuple, list)):
        return [_normalizar_valor(item) for item in valor]
    if isinstance(valor, dict):
        return {str(chave): _normalizar_valor(item) for chave, item in valor.items()}
    return repr(valor)


def camera_debug(evento: str, **dados) -> None:
    """Imprime uma linha curta no PowerShell e mantém cópia em arquivo.

    Não altera nenhum estado da câmera. Fora do Windows ou sem
    ``ODIN_CAMERA_DEBUG=1`` retorna imediatamente.
    """
    if not camera_debug_enabled():
        return

    agora = datetime.now().astimezone()
    payload = {
        "ts": agora.isoformat(timespec="milliseconds"),
        "thread": threading.current_thread().name,
        "event": str(evento),
    }
    for chave, valor in dados.items():
        payload[str(chave)] = _normalizar_valor(valor)

    linha = "[ODIN-CAMERA] " + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )

    with _LOG_LOCK:
        print(linha, flush=True)
        try:
            pasta = Path("data") / "logs"
            pasta.mkdir(parents=True, exist_ok=True)
            with (pasta / "windows_camera_debug.log").open(
                "a",
                encoding="utf-8",
            ) as arquivo:
                arquivo.write(linha + "\n")
        except Exception:
            # Debug nunca pode interferir no funcionamento da câmera.
            pass


def camera_debug_snapshot(service, evento: str = "snapshot") -> None:
    if not camera_debug_enabled() or service is None:
        return
    try:
        snapshot = service.obter_snapshot()
    except Exception as erro:
        camera_debug(
            evento + "_erro",
            erro=type(erro).__name__,
            detalhe=str(erro),
        )
        return

    try:
        diagnostico = service.obter_diagnostico_fluxo()
    except Exception:
        diagnostico = {}

    camera_debug(
        evento,
        estado=getattr(snapshot, "estado", None),
        mensagem=getattr(snapshot, "mensagem", None),
        frame_id=getattr(snapshot, "frame_id", None),
        resolucao=getattr(snapshot, "resolucao", None),
        resolucao_solicitada=getattr(snapshot, "resolucao_solicitada", None),
        fps_real=getattr(snapshot, "fps_real", None),
        backend=diagnostico.get("backend_ativo"),
        backend_tipo=diagnostico.get("backend_tipo"),
        thread_ativa=diagnostico.get("thread_ativa"),
        frames_lidos=diagnostico.get("frames_lidos_total"),
        falhas_leitura=diagnostico.get("leituras_falhas_total"),
        frames_validos=diagnostico.get("frames_validos_sessao"),
        probe_timeouts=diagnostico.get("windows_probe_timeout_total"),
        ultimo_probe_timeout=diagnostico.get("windows_ultimo_probe_timeout"),
        resolucao_travada=diagnostico.get("resolucao_mestra_travada"),
    )


def _wrap_method(classe, nome: str, wrapper_factory) -> None:
    original = getattr(classe, nome, None)
    if not callable(original):
        return
    marcador = f"_odin_windows_debug_{nome}"
    if getattr(classe, marcador, False):
        return
    setattr(classe, nome, wrapper_factory(original))
    setattr(classe, marcador, True)


def instalar_debug_camera_windows() -> bool:
    """Instala observabilidade apenas quando o debug foi explicitamente ativado."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return True
    if not camera_debug_enabled():
        return False

    import cv2
    from src.infra.camera_service import CameraService
    from src.platform.camera_selection import CameraSelectionMixin
    from src.platform.desktop_camera_service import DesktopCameraService
    from src.platform.threaded_camera_service import ThreadedDesktopCameraService
    from src.platform.windows_camera_compatibility import WindowsCameraCompatibilityMixin
    import src.platform.responsive_camera_selection as responsive

    camera_debug(
        "debug_ativado",
        python=sys.version.split()[0],
        windows=platform.platform(),
        opencv=getattr(cv2, "__version__", "?"),
        pid=os.getpid(),
    )

    # Em modo de debug interceptamos somente a construção do objeto OpenCV.
    # Se aparecer videcapture_inicio sem videcapture_fim, o driver travou dentro
    # do próprio construtor/open, antes de isOpened(), perfil ou primeiro read().
    video_capture_original = cv2.VideoCapture
    if not getattr(video_capture_original, "_odin_windows_debug", False):
        def video_capture_debug(*args, **kwargs):
            inicio = time.monotonic()
            indice = args[0] if len(args) >= 1 else kwargs.get("index")
            backend = args[1] if len(args) >= 2 else kwargs.get("apiPreference")
            camera_debug(
                "videocapture_inicio",
                indice=indice,
                backend=backend,
                argc=len(args),
            )
            try:
                capture = video_capture_original(*args, **kwargs)
            except Exception as erro:
                camera_debug(
                    "videocapture_excecao",
                    indice=indice,
                    backend=backend,
                    erro=type(erro).__name__,
                    detalhe=str(erro),
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
                )
                raise
            camera_debug(
                "videocapture_fim",
                indice=indice,
                backend=backend,
                capture_existe=capture is not None,
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
            )
            return capture

        video_capture_debug._odin_windows_debug = True
        video_capture_debug._odin_windows_debug_original = video_capture_original
        cv2.VideoCapture = video_capture_debug

    abrir_preview_original = responsive.abrir_camera_preview
    if not getattr(abrir_preview_original, "_odin_windows_debug", False):
        def abrir_preview_debug(indice: int):
            inicio = time.monotonic()
            camera_debug("selector_probe_inicio", indice=int(indice))
            try:
                capture, backend, frame = abrir_preview_original(indice)
            except Exception as erro:
                camera_debug(
                    "selector_probe_excecao",
                    indice=int(indice),
                    erro=type(erro).__name__,
                    detalhe=str(erro),
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
                )
                raise
            resolucao = None
            if frame is not None and getattr(frame, "size", 0):
                altura, largura = frame.shape[:2]
                resolucao = (int(largura), int(altura))
            camera_debug(
                "selector_probe_fim",
                indice=int(indice),
                encontrou=capture is not None,
                backend=backend,
                resolucao=resolucao,
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
            )
            return capture, backend, frame

        abrir_preview_debug._odin_windows_debug = True
        responsive.abrir_camera_preview = abrir_preview_debug

    def wrap_confirmar(original):
        def confirmar(self, indice: int, callback=None):
            camera_debug(
                "selector_confirmar",
                indice=int(indice),
                backend_por_indice=getattr(self, "_odin_windows_backend_por_indice", {}),
                released_event_existe=getattr(self, "_selector_released_event", None) is not None,
            )
            return original(self, indice, callback)
        return confirmar

    _wrap_method(
        CameraSelectionMixin,
        "_confirmar_camera_selecionada",
        wrap_confirmar,
    )

    def wrap_preparar(original):
        def preparar(self, indice: int):
            camera_debug(
                "service_preparar_indice",
                indice=int(indice),
                backend_selecionado=getattr(self, "backend_camera_selecionado", None),
            )
            resultado = original(self, indice)
            try:
                classe = getattr(self, "CAMERA_SERVICE_CLASS", DesktopCameraService)
                classe_nome = getattr(classe, "__name__", repr(classe))
            except Exception:
                classe_nome = "?"
            camera_debug(
                "service_indice_preparado",
                indice=int(indice),
                classe=classe_nome,
            )
            return resultado
        return preparar

    _wrap_method(
        CameraSelectionMixin,
        "_preparar_camera_selecionada_estrita",
        wrap_preparar,
    )

    def wrap_estado(original):
        def definir_estado(self, estado, mensagem):
            anterior = getattr(self, "_estado", None)
            resultado = original(self, estado, mensagem)
            if anterior != estado or camera_debug_enabled():
                camera_debug(
                    "estado",
                    anterior=anterior,
                    atual=estado,
                    mensagem=mensagem,
                    indice=getattr(self, "indice_camera", None),
                    backend=getattr(self, "_backend_name", None),
                )
            return resultado
        return definir_estado

    _wrap_method(CameraService, "_definir_estado", wrap_estado)

    def wrap_reconexao(original):
        def reconectar(self, motivo: str):
            camera_debug(
                "reconexao_agendada",
                motivo=motivo,
                indice=getattr(self, "indice_camera", None),
                backend=getattr(self, "_backend_name", None),
                falhas=getattr(self, "_falhas_consecutivas", None),
            )
            return original(self, motivo)
        return reconectar

    _wrap_method(CameraService, "_agendar_reconexao", wrap_reconexao)

    def wrap_liberar(original):
        def liberar(self):
            capture_existe = getattr(self, "_capture", None) is not None
            camera_debug(
                "capture_release_inicio",
                capture_existe=capture_existe,
                indice=getattr(self, "indice_camera", None),
                backend=getattr(self, "_backend_name", None),
            )
            inicio = time.monotonic()
            resultado = original(self)
            camera_debug(
                "capture_release_fim",
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
                capture_existe=getattr(self, "_capture", None) is not None,
            )
            return resultado
        return liberar

    _wrap_method(CameraService, "_liberar_camera", wrap_liberar)

    def wrap_perfil_capture(original):
        def aplicar(self, capture):
            inicio = time.monotonic()
            camera_debug(
                "perfil_capture_inicio",
                perfil_auto=getattr(self, "perfil_automatico", None),
                largura=getattr(self, "largura", None),
                altura=getattr(self, "altura", None),
                fps=getattr(self, "fps", None),
                formato=getattr(self, "formato_camera", None),
                resolucao_travada=getattr(self, "_resolucao_mestra_travada", None),
            )
            try:
                resultado = original(self, capture)
            except Exception as erro:
                camera_debug(
                    "perfil_capture_excecao",
                    erro=type(erro).__name__,
                    detalhe=str(erro),
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
                )
                raise
            camera_debug(
                "perfil_capture_fim",
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
            )
            return resultado
        return aplicar

    _wrap_method(CameraService, "_aplicar_perfil_capture", wrap_perfil_capture)

    def wrap_abrir(original):
        def abrir(self):
            inicio = time.monotonic()
            camera_debug(
                "service_open_inicio",
                indice_solicitado=getattr(self, "_indice_camera_solicitado", None),
                indice_atual=getattr(self, "indice_camera", None),
                indices=(
                    self._indices_candidatos()
                    if callable(getattr(self, "_indices_candidatos", None))
                    else None
                ),
                backends=(
                    self._backends_preferidos()
                    if callable(getattr(self, "_backends_preferidos", None))
                    else None
                ),
                largura=getattr(self, "largura", None),
                altura=getattr(self, "altura", None),
                fps=getattr(self, "fps", None),
                formato=getattr(self, "formato_camera", None),
                perfil_auto=getattr(self, "perfil_automatico", None),
                resolucao_travada=getattr(self, "_resolucao_mestra_travada", None),
            )
            try:
                resultado = original(self)
            except Exception as erro:
                camera_debug(
                    "service_open_excecao",
                    erro=type(erro).__name__,
                    detalhe=str(erro),
                    duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
                )
                raise
            camera_debug(
                "service_open_fim",
                resultado=bool(resultado),
                indice_ativo=getattr(self, "_indice_camera_ativo", None),
                backend=getattr(self, "_backend_name", None),
                capture_existe=getattr(self, "_capture", None) is not None,
                estado=getattr(self, "_estado", None),
                mensagem=getattr(self, "_mensagem", None),
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
            )
            return resultado
        return abrir

    _wrap_method(DesktopCameraService, "_abrir_camera", wrap_abrir)

    def wrap_probe(original):
        def probe(self, capture):
            inicio = time.monotonic()
            camera_debug(
                "probe_inicial_inicio",
                indice=getattr(self, "indice_camera", None),
                exigir_resolucao=getattr(self, "_windows_exigir_resolucao_solicitada", None),
                alvo=(getattr(self, "largura", None), getattr(self, "altura", None)),
            )
            resultado = original(self, capture)
            camera_debug(
                "probe_inicial_fim",
                resultado=bool(resultado),
                ultima_resolucao=getattr(self, "_windows_ultima_resolucao_probe", None),
                timeout=getattr(self, "_windows_ultimo_probe_timeout", None),
                timeouts_total=getattr(self, "_windows_probe_timeout_total", None),
                duracao_ms=round((time.monotonic() - inicio) * 1000, 1),
            )
            return resultado
        return probe

    _wrap_method(
        WindowsCameraCompatibilityMixin,
        "_capture_entrega_frame_inicial",
        wrap_probe,
    )

    def wrap_loop(original):
        def loop(self):
            camera_debug(
                "capture_loop_inicio",
                indice=getattr(self, "indice_camera", None),
                thread=threading.current_thread().name,
            )
            try:
                return original(self)
            finally:
                camera_debug(
                    "capture_loop_fim",
                    frames_lidos=getattr(self, "_frames_lidos_total", None),
                    falhas=getattr(self, "_leituras_falhas_total", None),
                    stop=getattr(self, "_stop_event", None).is_set()
                    if getattr(self, "_stop_event", None) is not None
                    else None,
                )
        return loop

    _wrap_method(ThreadedDesktopCameraService, "_loop_captura", wrap_loop)

    def wrap_publicar(original):
        def publicar(self, frame, estavel: bool):
            contador = int(getattr(self, "_odin_debug_publicacoes", 0)) + 1
            self._odin_debug_publicacoes = contador
            if contador <= 3 or contador % 60 == 0:
                altura, largura = frame.shape[:2]
                camera_debug(
                    "frame_publicado",
                    numero=contador,
                    resolucao=(int(largura), int(altura)),
                    estavel=bool(estavel),
                    backend=getattr(self, "_backend_name", None),
                )
            return original(self, frame, estavel)
        return publicar

    _wrap_method(
        ThreadedDesktopCameraService,
        "_publicar_frame_otimizado",
        wrap_publicar,
    )

    _PATCH_INSTALADO = True
    return True


def iniciar_debug_periodico_camera_windows(app, intervalo_ms: int = 1500) -> bool:
    """Mostra snapshots periódicos para localizar exatamente onde o fluxo parou."""
    if not camera_debug_enabled():
        return False

    root = getattr(app, "root", None)
    if root is None:
        return False

    def emitir() -> None:
        try:
            service = getattr(app, "camera_service", None)
            if service is not None:
                camera_debug_snapshot(service, "snapshot_periodico")
        finally:
            try:
                root.after(max(500, int(intervalo_ms)), emitir)
            except Exception:
                pass

    camera_debug("snapshot_periodico_agendado", intervalo_ms=int(intervalo_ms))
    try:
        root.after(400, emitir)
    except Exception:
        return False
    return True
