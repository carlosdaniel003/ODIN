from __future__ import annotations

import sys
import unicodedata

from src.platform.camera_selection import (
    CAMERA_SELECTOR_RELEASE_GRACE_MS,
    CameraSelectionMixin,
)


_PATCH_INSTALADO = False
# O worker já confirmou release(), mas alguns drivers UVC/MSMF ainda mantêm a
# sessão USB por alguns centenas de milissegundos. O atraso é exclusivo Windows.
WINDOWS_POST_RELEASE_SETTLE_MS = 1800
WINDOWS_RELEASE_STATUS_AFTER_MS = 2500
WINDOWS_RELEASE_POLL_MS = 50
WINDOWS_HIGH_RES_MIN_WIDTH = 1280
WINDOWS_HIGH_RES_MIN_HEIGHT = 720


def _normalizar_backend(nome: str | None) -> str:
    texto = unicodedata.normalize("NFKD", str(nome or ""))
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return " ".join(texto.lower().split())


def priorizar_backend_windows(
    backends,
    backend_preferido: str | None,
    plataforma: str | None = None,
):
    """Move para frente somente o backend comprovado pelo preview no Windows."""
    itens = tuple(backends or ())
    plataforma = str(plataforma or sys.platform).lower()
    if not plataforma.startswith("win") or not backend_preferido:
        return itens

    preferido = _normalizar_backend(backend_preferido)
    correspondentes = [
        item
        for item in itens
        if len(item) >= 2 and _normalizar_backend(item[1]) == preferido
    ]
    if not correspondentes:
        return itens

    primeiro = correspondentes[0]
    return (primeiro,) + tuple(item for item in itens if item != primeiro)


def ordenar_backends_servico_windows(
    backends,
    backend_preview: str | None,
    resolucao_solicitada=None,
    perfil_automatico: bool = False,
    plataforma: str | None = None,
):
    """Escolhe uma ordem segura para o serviço principal no Windows.

    O preview só comprova que um backend entrega alguma imagem. Isso não prova
    que o mesmo backend tolera renegociação para 1920x1080 após ser reaberto.
    Em alta resolução explícita priorizamos DirectShow, que é mais previsível
    para webcams UVC Logitech via OpenCV. Em modo automático ou baixa resolução
    continuamos respeitando o backend que funcionou no preview.
    """
    itens = tuple(backends or ())
    plataforma = str(plataforma or sys.platform).lower()
    if not plataforma.startswith("win"):
        return itens

    preferidos = priorizar_backend_windows(
        itens,
        backend_preview,
        plataforma=plataforma,
    )
    if bool(perfil_automatico):
        return preferidos

    try:
        largura = int(resolucao_solicitada[0])
        altura = int(resolucao_solicitada[1])
    except (TypeError, ValueError, IndexError):
        return preferidos

    if (
        largura < WINDOWS_HIGH_RES_MIN_WIDTH
        or altura < WINDOWS_HIGH_RES_MIN_HEIGHT
    ):
        return preferidos

    directshow = next(
        (
            item
            for item in preferidos
            if len(item) >= 2
            and _normalizar_backend(item[1]) == "directshow"
        ),
        None,
    )
    if directshow is None:
        return preferidos

    automaticos = tuple(
        item
        for item in preferidos
        if item != directshow
        and _normalizar_backend(item[1])
        in ("automatico", "automatic", "auto")
    )
    restantes = tuple(
        item
        for item in preferidos
        if item != directshow and item not in automaticos
    )
    return (directshow,) + automaticos + restantes


def pode_iniciar_camera_apos_preview(
    liberada: bool,
    espera_ms: int,
    limite_ms: int,
    plataforma: str | None = None,
) -> bool:
    """No Windows nunca abre a câmera enquanto o preview ainda possui o handle.

    O comportamento legado de limite continua disponível fora do Windows para
    preservar integralmente o handoff já estável do Linux.
    """
    if bool(liberada):
        return True
    plataforma = str(plataforma or sys.platform).lower()
    if plataforma.startswith("win"):
        return False
    return int(espera_ms) >= int(limite_ms)


def _registrar_backend_preview_windows(self, indice: int, backend: str | None) -> None:
    if not sys.platform.startswith("win"):
        return
    mapa = getattr(self, "_odin_windows_backend_por_indice", None)
    if not isinstance(mapa, dict):
        mapa = {}
        self._odin_windows_backend_por_indice = mapa
    mapa[int(indice)] = str(backend or "")


def _instalar_preferencia_backend_na_classe(classe, backend: str | None) -> None:
    if not sys.platform.startswith("win") or not backend:
        return

    classe._odin_windows_backend_preferido = str(backend)
    if getattr(classe, "_odin_windows_backend_handoff_instalado", False):
        return

    original = getattr(classe, "_backends_preferidos", None)
    if not callable(original):
        return

    def backends_preferindo_preview(self):
        try:
            backends = original()
        except TypeError:
            backends = original(self)
        return ordenar_backends_servico_windows(
            backends,
            getattr(type(self), "_odin_windows_backend_preferido", None),
            resolucao_solicitada=getattr(
                self,
                "_resolucao_solicitada",
                None,
            ),
            perfil_automatico=bool(
                getattr(self, "perfil_automatico", False)
            ),
            plataforma=sys.platform,
        )

    classe._backends_preferidos = backends_preferindo_preview
    classe._odin_windows_backend_handoff_instalado = True


def instalar_handoff_camera_windows() -> None:
    """Corrige somente a passagem preview -> câmera real no Windows.

    Nenhuma regra de resolução, backend ou reconexão do Linux é substituída.
    Fora do Windows os wrappers chamam os métodos originais sem alterações.
    """
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # O seletor responsivo é instalado dinamicamente sobre CameraSelectionMixin.
    # Por isso envolvemos o método efetivamente usado pela aplicação final.
    criar_card_original = getattr(
        CameraSelectionMixin,
        "_criar_card_camera_responsivo",
        None,
    )
    confirmar_original = CameraSelectionMixin._confirmar_camera_selecionada
    preparar_original = CameraSelectionMixin._preparar_camera_selecionada_estrita

    if callable(criar_card_original):
        def criar_card_com_backend(self, indice, backend, ao_selecionar):
            _registrar_backend_preview_windows(self, indice, backend)
            return criar_card_original(self, indice, backend, ao_selecionar)

        CameraSelectionMixin._criar_card_camera_responsivo = criar_card_com_backend

    def confirmar_camera_com_handoff_seguro(self, indice: int, callback=None) -> None:
        if not sys.platform.startswith("win"):
            return confirmar_original(self, indice, callback)

        indice = int(indice)
        self.indice_camera_selecionada = indice
        mapa = getattr(self, "_odin_windows_backend_por_indice", {})
        self.backend_camera_selecionado = (
            str(mapa.get(indice) or "") if isinstance(mapa, dict) else ""
        )

        released_event = getattr(self, "_selector_released_event", None)
        self._fechar_seletor_camera()

        try:
            self.view.atualizar_status(
                f"Câmera {indice} selecionada. Liberando preview do Windows..."
            )
        except Exception:
            pass

        if callback is None:
            return

        def continuar(espera_ms: int = 0) -> None:
            liberada = released_event is None or released_event.is_set()
            if pode_iniciar_camera_apos_preview(
                liberada=liberada,
                espera_ms=espera_ms,
                limite_ms=0,
                plataforma=sys.platform,
            ):
                try:
                    self.view.atualizar_status(
                        f"Câmera {indice} liberada. Inicializando fluxo..."
                    )
                except Exception:
                    pass
                # O settle ocorre somente no Windows, após release() confirmado.
                self.root.after(
                    WINDOWS_POST_RELEASE_SETTLE_MS,
                    lambda: callback(indice),
                )
                return

            if espera_ms >= WINDOWS_RELEASE_STATUS_AFTER_MS:
                try:
                    self.view.atualizar_status(
                        "Aguardando o driver do Windows liberar a câmera do preview..."
                    )
                except Exception:
                    pass

            self.root.after(
                WINDOWS_RELEASE_POLL_MS,
                lambda: continuar(espera_ms + WINDOWS_RELEASE_POLL_MS),
            )

        self.root.after(CAMERA_SELECTOR_RELEASE_GRACE_MS, continuar)

    def preparar_camera_com_backend_validado(self, indice: int) -> None:
        resultado = preparar_original(self, indice)
        if not sys.platform.startswith("win"):
            return resultado

        backend = getattr(self, "backend_camera_selecionado", None)
        classe = getattr(self, "CAMERA_SERVICE_CLASS", None)
        if classe is not None:
            _instalar_preferencia_backend_na_classe(classe, backend)
        return resultado

    confirmar_camera_com_handoff_seguro._odin_windows_handoff = True
    preparar_camera_com_backend_validado._odin_windows_handoff = True

    CameraSelectionMixin._confirmar_camera_selecionada = (
        confirmar_camera_com_handoff_seguro
    )
    CameraSelectionMixin._preparar_camera_selecionada_estrita = (
        preparar_camera_com_backend_validado
    )
    CameraSelectionMixin._odin_windows_camera_handoff_instalado = True
    _PATCH_INSTALADO = True
