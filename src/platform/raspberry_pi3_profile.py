from __future__ import annotations

import time
import tkinter as tk

from src.app import (
    CAMERA_ALTURA_MINIMA,
    CAMERA_ESPERA_APOS_ABRIR_S,
    CAMERA_FALHAS_ANTES_AVISO,
    CAMERA_FRAMES_AQUECIMENTO,
    CAMERA_FRAMES_ESTABILIDADE,
    CAMERA_INTERVALO_RECONEXAO_S,
    CAMERA_LARGURA_MINIMA,
    INDICE_CAMERA_PADRAO,
    LIMITE_FRAME_PRETO_DESVIO,
    LIMITE_FRAME_PRETO_MEDIA,
    ODINApp,
)
from src.core.operation_engine import (
    OperationEngine,
    OperationPreparationError,
)
from src.platform.raspberry_camera_service import (
    RaspberryPi3CameraService,
)
from src.platform.raspberry_pi3_settings import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    FRAME_INTERVAL_MS,
    OPERATION_PREVIEW_HEIGHT,
    OPERATION_PREVIEW_INTERVAL_MS,
    OPERATION_PREVIEW_WIDTH,
    PARAMETERIZATION_PREVIEW_INTERVAL_MS,
)
from src.ui.operation_window import OperationWindow


class RaspberryPi3ODINApp(ODINApp):
    """ODIN com parametrização leve e operação rápida no Raspberry Pi 3."""

    def __init__(self, root: tk.Tk) -> None:
        self._ultima_renderizacao_parametrizacao_s = 0.0
        self.operacao_ativa = False
        self.operacao_processando = False
        self.operacao_total = 0
        self.operacao_ok = 0
        self.operacao_ng = 0
        self.operacao_engine = OperationEngine()
        self.operacao_window = None
        self.operacao_leds_preview = []
        self._operacao_preparo_after_id = None
        self._operacao_preview_after_id = None

        super().__init__(root)
        self._instalar_tela_operacao()

    def _instalar_tela_operacao(self) -> None:
        self.operacao_window = OperationWindow(
            root=self.root,
            on_trigger=self.disparar_inspecao_operacao,
            on_close=self.fechar_tela_operacao,
            preview_width=OPERATION_PREVIEW_WIDTH,
            preview_height=OPERATION_PREVIEW_HEIGHT,
        )
        self.botao_operacao = tk.Button(
            self.root,
            text="OPERAÇÃO  F2",
            command=self.abrir_tela_operacao,
            font=("DejaVu Sans", 10, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        )
        self.botao_operacao.place(
            relx=1.0,
            x=-18,
            y=16,
            anchor="ne",
        )
        self.botao_operacao.lift()
        self.root.bind(
            "<F2>",
            lambda _event: self.abrir_tela_operacao(),
            add="+",
        )

    def obter_parametros_camera_dinamicos(self) -> tuple[int, int, int]:
        return CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS

    def agendar_proximo_frame_camera(
        self,
        atraso_ms: int = FRAME_INTERVAL_MS,
    ) -> None:
        if not self.camera_ativa or self.camera_service is None:
            return
        if self.camera_after_id is not None:
            return

        self.camera_after_id = self.root.after(
            max(0, int(atraso_ms)),
            self.atualizar_frame_camera,
        )

    def iniciar_tela_ao_vivo(self) -> None:
        if self.camera_ativa:
            return

        if self.camera_service is not None:
            self.camera_service.parar()
            self.camera_service = None

        self.configuracoes_camera = dict(
            self.configuracoes_camera or {}
        )
        self.configuracoes_camera.update(
            {
                "resolution_mode": "custom",
                "width": CAMERA_WIDTH,
                "height": CAMERA_HEIGHT,
                "fps_mode": "manual",
                "fps": CAMERA_FPS,
                "format": "MJPG",
            }
        )

        largura_camera, altura_camera, fps_camera = (
            self.obter_parametros_camera_dinamicos()
        )
        self.camera_service = RaspberryPi3CameraService(
            indice_camera=INDICE_CAMERA_PADRAO,
            largura=largura_camera,
            altura=altura_camera,
            fps=fps_camera,
            intervalo_reconexao_s=CAMERA_INTERVALO_RECONEXAO_S,
            frames_aquecimento=CAMERA_FRAMES_AQUECIMENTO,
            falhas_antes_reconexao=CAMERA_FALHAS_ANTES_AVISO,
            largura_minima=CAMERA_LARGURA_MINIMA,
            altura_minima=CAMERA_ALTURA_MINIMA,
            limite_preto_media=LIMITE_FRAME_PRETO_MEDIA,
            limite_preto_desvio=LIMITE_FRAME_PRETO_DESVIO,
            frames_estabilidade=CAMERA_FRAMES_ESTABILIDADE,
            espera_apos_abrir_s=CAMERA_ESPERA_APOS_ABRIR_S,
            configuracoes_camera=self.configuracoes_camera,
        )

        self.camera_ativa = True
        self.camera_em_pausa_analise = False
        self.camera_falhas_consecutivas = 0
        self.camera_ultimo_frame_id = -1
        self.camera_estado_anterior = (
            RaspberryPi3CameraService.ESTADO_PARADA
        )
        self.camera_desconectada = False
        self.camera_frame_atual = None
        self.camera_ultima_renderizacao_auxiliar_s = 0.0
        self.modo_atual = "tela_ao_vivo"
        self.resultados_led_atual = []
        self.leds_fixos_configurados = (
            self.config_repository.carregar_leds_fixos()
        )
        self.guias_leds_fixos_visiveis = True
        self.selecao_manual_camera_ativa = False
        self.leds_manuais_camera = []
        self.leds_selecionados = []
        self.view.selecao_manual_camera_visivel = False

        self.view.atualizar_faixa_resultado()
        self.view.atualizar_estado_tela_ao_vivo(True)
        self.view.atualizar_estado_selecao_led(False)
        self.view.atualizar_status(
            f"Conectando câmera em {largura_camera}x"
            f"{altura_camera} @ {fps_camera} FPS..."
        )
        self.exibir_aviso_camera(
            "CONECTANDO CÂMERA",
            tipo="informacao",
        )
        self.camera_service.iniciar()
        self.agendar_proximo_frame_camera(0)

    def atualizar_frame_camera(self) -> None:
        if self.operacao_ativa:
            self.camera_em_pausa_analise = True
            super().atualizar_frame_camera()
            self.camera_em_pausa_analise = True
            return

        if self.camera_em_pausa_analise:
            super().atualizar_frame_camera()
            return

        agora = time.monotonic()
        intervalo_preview_s = (
            PARAMETERIZATION_PREVIEW_INTERVAL_MS / 1000.0
        )
        deve_renderizar = (
            agora - self._ultima_renderizacao_parametrizacao_s
            >= intervalo_preview_s
        )

        if deve_renderizar:
            self._ultima_renderizacao_parametrizacao_s = agora
            super().atualizar_frame_camera()
            return

        self.camera_em_pausa_analise = True
        try:
            super().atualizar_frame_camera()
        finally:
            self.camera_em_pausa_analise = False

    def atualizar_renderizacoes_camera_se_necessario(
        self,
        forcar: bool = False,
    ) -> None:
        return None

    def abrir_tela_operacao(self) -> None:
        self.operacao_ativa = True
        self.operacao_processando = False
        self.operacao_engine.invalidate()
        self.operacao_leds_preview = []
        self.operacao_window.show()

        if self.camera_frame_atual is not None:
            self.operacao_window.update_preview(
                self.camera_frame_atual,
                self.operacao_leds_preview,
            )
        else:
            self.operacao_window.clear_preview()

        self.operacao_window.show_preparing()

        if not self.camera_ativa:
            self.iniciar_tela_ao_vivo()

        self.camera_em_pausa_analise = True
        self._agendar_preparo_operacao(80)
        self._agendar_preview_operacao(0)

    def fechar_tela_operacao(self) -> None:
        self.operacao_ativa = False
        self.operacao_processando = False
        self.camera_em_pausa_analise = False

        if self._operacao_preparo_after_id is not None:
            try:
                self.root.after_cancel(
                    self._operacao_preparo_after_id
                )
            except Exception:
                pass
            self._operacao_preparo_after_id = None

        self._cancelar_preview_operacao()
        self.operacao_window.hide()
        self._ultima_renderizacao_parametrizacao_s = 0.0
        self.view.atualizar_status(
            "tela de parametrização ativa. F2 abre a operação."
        )

    def _agendar_preparo_operacao(self, atraso_ms: int) -> None:
        if not self.operacao_ativa:
            return
        self._operacao_preparo_after_id = self.root.after(
            max(20, int(atraso_ms)),
            self.preparar_tela_operacao,
        )

    def _cancelar_preview_operacao(self) -> None:
        if self._operacao_preview_after_id is None:
            return
        try:
            self.root.after_cancel(self._operacao_preview_after_id)
        except Exception:
            pass
        self._operacao_preview_after_id = None

    def _agendar_preview_operacao(
        self,
        atraso_ms: int = OPERATION_PREVIEW_INTERVAL_MS,
    ) -> None:
        if not self.operacao_ativa:
            return
        if self._operacao_preview_after_id is not None:
            return

        self._operacao_preview_after_id = self.root.after(
            max(0, int(atraso_ms)),
            self._atualizar_preview_operacao,
        )

    def _atualizar_preview_operacao(self) -> None:
        self._operacao_preview_after_id = None

        if not self.operacao_ativa:
            return

        if self.camera_desconectada:
            self.operacao_window.set_preview_status(
                "Última imagem • câmera desconectada",
                "#FCA5A5",
            )
        elif self.operacao_processando:
            self.operacao_window.set_preview_paused(True)
        elif self.camera_frame_atual is not None:
            self.operacao_window.update_preview(
                self.camera_frame_atual,
                self.operacao_leds_preview,
            )

        self._agendar_preview_operacao()

    def preparar_tela_operacao(self) -> None:
        self._operacao_preparo_after_id = None
        if not self.operacao_ativa:
            return

        if (
            not self.camera_ativa
            or self.camera_service is None
            or self.camera_frame_atual is None
        ):
            self.operacao_window.show_preparing(
                "Aguardando o primeiro frame da câmera"
            )
            self._agendar_preparo_operacao(100)
            return

        if self.camera_desconectada:
            self.operacao_window.show_preparing(
                "Câmera desconectada — reconectando"
            )
            self.operacao_window.set_preview_status(
                "Última imagem • câmera desconectada",
                "#FCA5A5",
            )
            self._agendar_preparo_operacao(250)
            return

        try:
            self.carregar_referencias_automaticamente_se_necessario()
            if not self.referencias_disponiveis():
                raise OperationPreparationError(
                    "PARAMETRIZAÇÃO NECESSÁRIA\n"
                    "Referências não carregadas"
                )

            frame = self.camera_frame_atual
            altura_frame, largura_frame = frame.shape[:2]
            self.altura_original = altura_frame
            self.largura_original = largura_frame

            leds_salvos = self.config_repository.carregar_leds_fixos()
            if not leds_salvos:
                raise OperationPreparationError(
                    "MODELO SEM CONFIGURAÇÃO\n"
                    "Nenhum LED fixo salvo"
                )

            leds_adaptados = (
                self.adaptar_leds_fixos_para_frame_camera(
                    leds_salvos
                )
            )
            self.operacao_engine.prepare(
                features_reference_on=(
                    self.features_referencia_acesa
                ),
                features_reference_off=(
                    self.features_referencia_apagada
                ),
                leds=leds_adaptados,
                frame_width=largura_frame,
                frame_height=altura_frame,
            )
            self.leds_fixos_configurados = leds_salvos
            self.operacao_leds_preview = leds_adaptados
            self.operacao_window.update_preview(
                frame,
                self.operacao_leds_preview,
            )
            self.operacao_window.show_waiting(
                led_count=self.operacao_engine.led_count,
                total=self.operacao_total,
                ok_count=self.operacao_ok,
                ng_count=self.operacao_ng,
            )
        except OperationPreparationError as erro:
            self._mostrar_erro_operacao(str(erro))
        except Exception as erro:
            self._mostrar_erro_operacao(
                "Falha ao preparar operação\n"
                f"{type(erro).__name__}: {erro}"
            )

    def disparar_inspecao_operacao(self) -> None:
        if not self.operacao_ativa or self.operacao_processando:
            return

        if self.camera_desconectada or self.camera_frame_atual is None:
            self._mostrar_erro_operacao("CÂMERA DESCONECTADA")
            return

        if not self.operacao_engine.ready:
            self.preparar_tela_operacao()
            if not self.operacao_engine.ready:
                return

        self._cancelar_preview_operacao()
        self.operacao_processando = True
        self.operacao_window.set_preview_paused(True)
        self.operacao_window.show_processing(
            total=self.operacao_total,
            ok_count=self.operacao_ok,
            ng_count=self.operacao_ng,
        )
        self.root.update_idletasks()

        try:
            frame = self.camera_frame_atual.copy()
            resultado = self.operacao_engine.analyze(frame)
        except Exception as erro:
            self.operacao_processando = False
            self.operacao_window.set_preview_paused(False)
            self._mostrar_erro_operacao(
                "FALHA NA INSPEÇÃO\n"
                f"{type(erro).__name__}: {erro}"
            )
            return

        self.operacao_processando = False
        self.operacao_total += 1

        if resultado.ok:
            self.operacao_ok += 1
        else:
            self.operacao_ng += 1

        self.operacao_window.show_result(
            is_ok=resultado.ok,
            elapsed_seconds=resultado.elapsed_seconds,
            failed_led_ids=resultado.failed_led_ids,
            total=self.operacao_total,
            ok_count=self.operacao_ok,
            ng_count=self.operacao_ng,
        )
        self.operacao_window.set_preview_paused(False)
        self._agendar_preview_operacao(
            OPERATION_PREVIEW_INTERVAL_MS
        )

    def _mostrar_erro_operacao(self, mensagem: str) -> None:
        self.operacao_processando = False
        self.operacao_window.set_preview_paused(False)
        self.operacao_window.show_error(
            mensagem,
            total=self.operacao_total,
            ok_count=self.operacao_ok,
            ng_count=self.operacao_ng,
        )
        self._agendar_preview_operacao(
            OPERATION_PREVIEW_INTERVAL_MS
        )
