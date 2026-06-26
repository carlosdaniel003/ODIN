from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox


from config import CONFIG_DIR, CONFIG_FILE, DEFAULT_RADIUS_PX, MAX_RADIUS_PX, MIN_RADIUS_PX
from src.core.classifier import ReferenceLedClassifier
from src.core.debug_formatter import formatar_painel_inicial, formatar_resultado_textual_multiplos
from src.core.feature_extractor import extrair_features_led, extrair_features_referencia_led, validar_centro_led
from src.core.visual_renderer import criar_imagem_resultados_visuais, criar_pacote_renderizacoes_visuais
from src.infra.camera_service import CameraService
from src.infra.config_repository import ConfigRepository
from src.infra.image_io import carregar_imagem_opencv
from src.infra.result_repository import ResultRepository
from src.models.led_selection import LedSelection
from src.ui.main_window import LumusPCIView


RAIO_MAXIMO_LED_PX = MAX_RADIUS_PX
INDICE_CAMERA_PADRAO = 0
INTERVALO_CAMERA_MS = 45
INTERVALO_RENDERIZACOES_CAMERA_MS = 250
TEMPO_RESULTADO_CAMERA_MS = 3000
CAMERA_LARGURA_DESEJADA = 1280
CAMERA_ALTURA_DESEJADA = 720
CAMERA_FPS_DESEJADO = 30
LIMITE_FRAME_PRETO_MEDIA = 4.0
LIMITE_FRAME_PRETO_DESVIO = 3.0
MARGEM_GUIAS_CAMERA_PERCENTUAL = 0.05
CAMERA_FRAMES_AQUECIMENTO = 30
CAMERA_LARGURA_MINIMA = 320
CAMERA_ALTURA_MINIMA = 240
CAMERA_FALHAS_ANTES_AVISO = 3
CAMERA_INTERVALO_RECONEXAO_S = 1.0
CAMERA_FRAMES_ESTABILIDADE = 8
CAMERA_ESPERA_APOS_ABRIR_S = 0.45


class LumusPCIApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root

        self.imagem_original = None
        self.caminho_imagem_atual = None

        self.imagem_referencia_acesa = None
        self.imagem_referencia_apagada = None
        self.caminho_referencia_acesa = None
        self.caminho_referencia_apagada = None
        self.features_referencia_acesa = None
        self.features_referencia_apagada = None

        self.largura_original = 0
        self.altura_original = 0

        self.modo_atual = "ocioso"
        self.raio_atual_px = DEFAULT_RADIUS_PX

        self.leds_selecionados: list[LedSelection] = []
        self.leds_fixos_configurados: list[LedSelection] = []
        self.resultados_led_atual = []
        self.configuracao_atual = {}

        self.camera_service: CameraService | None = None
        self.camera_ativa = False
        self.camera_after_id = None
        self.camera_frame_atual = None
        self.camera_retomada_after_id = None
        self.camera_em_pausa_analise = False
        self.camera_falhas_consecutivas = 0
        self.camera_ultimo_frame_id = -1
        self.camera_estado_anterior = CameraService.ESTADO_PARADA
        self.camera_desconectada = False
        self.camera_aviso_estado: str | None = None
        self.camera_ultima_renderizacao_auxiliar_s = 0.0

        # Estado visual e temporário da seleção durante a câmera ao vivo.
        # Os LEDs fixos permanecem salvos no JSON mesmo quando suas guias
        # são ocultadas pelo botão "Limpar seleção".
        self.guias_leds_fixos_visiveis = True
        self.selecao_manual_camera_ativa = False
        self.leds_manuais_camera: list[LedSelection] = []

        self.config_repository = ConfigRepository()
        self.result_repository = ResultRepository()
        self.salvar_resultados_analise = self.config_repository.obter_salvar_resultados_analise()
        self.raio_atual_px = self.config_repository.obter_raio_padrao_led(RAIO_MAXIMO_LED_PX)
        self.leds_fixos_configurados = self.config_repository.carregar_leds_fixos()
        self.configuracoes_camera = self.config_repository.obter_configuracoes_camera()

        self.criar_pastas()
        self.carregar_referencias_automaticamente_se_necessario()
        self.view = LumusPCIView(
            root=self.root,
            callbacks=self.criar_callbacks(),
            raio_atual_px=self.raio_atual_px,
        )
        self.view.selecao_manual_camera_visivel = False
        self.view.atualizar_estado_selecao_led(False)
        self.atualizar_painel_inicial()

    def criar_callbacks(self) -> dict:
        return {
            "carregar_referencia_led_aceso": self.carregar_referencia_led_aceso,
            "carregar_referencia_led_apagado": self.carregar_referencia_led_apagado,
            "salvar_referencias": self.salvar_referencias,
            "carregar_configuracao": self.carregar_configuracao,
            "carregar_imagem": self.carregar_imagem,
            "alternar_tela_ao_vivo": self.alternar_tela_ao_vivo,
            "capturar_frame_camera_para_analise": self.capturar_frame_camera_para_analise,
            "iniciar_selecao_led": self.iniciar_selecao_led,
            "configurar_leds_fixos": self.configurar_leds_fixos,
            "salvar_leds_fixos": self.salvar_leds_fixos,
            "carregar_leds_fixos": self.carregar_leds_fixos,
            "analisar_led_selecionado": self.analisar_led_selecionado,
            "limpar_tela": self.limpar_tela,
            "diminuir_raio": self.diminuir_raio,
            "aumentar_raio": self.aumentar_raio,
            "evento_clique_esquerdo": self.evento_clique_esquerdo,
            "abrir_configuracoes": self.abrir_configuracoes,
        }

    def criar_pastas(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def atualizar_painel_inicial(self) -> None:
        texto = formatar_painel_inicial(
            features_referencia_acesa=self.features_referencia_acesa,
            features_referencia_apagada=self.features_referencia_apagada,
            leds_selecionados=self.leds_selecionados,
            raio_atual_px=self.raio_atual_px,
            salvar_resultados_analise=self.salvar_resultados_analise,
        )
        self.view.escrever_resultados(texto)

    def abrir_configuracoes(self) -> None:
        camera_conectada = (
            self.camera_ativa
            and self.camera_service is not None
            and self.camera_estado_anterior == CameraService.ESTADO_CONECTADA
        )

        status_controles_camera = {}

        if self.camera_service is not None:
            status_controles_camera = (
                self.camera_service.obter_status_controles_camera()
            )

        self.view.abrir_janela_configuracoes(
            salvar_resultados_analise=self.salvar_resultados_analise,
            raio_atual_px=self.raio_atual_px,
            configuracoes_camera=self.configuracoes_camera,
            camera_conectada=camera_conectada,
            status_controles_camera=status_controles_camera,
            callback_salvar=self.salvar_configuracoes_sistema,
        )

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_configurado_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ) -> None:
        self.salvar_resultados_analise = bool(salvar_resultados_analise)
        rotacao_anterior = int(
            self.configuracoes_camera.get("rotation", 0)
        )
        perfil_camera_anterior = self.perfil_camera_dinamico(
            self.configuracoes_camera
        )

        if raio_configurado_px is not None:
            self.raio_atual_px = min(
                RAIO_MAXIMO_LED_PX,
                max(MIN_RADIUS_PX, int(raio_configurado_px)),
            )
            self.view.atualizar_label_raio(self.raio_atual_px)

            if self.leds_selecionados:
                for led_selecionado in self.leds_selecionados:
                    led_selecionado.raio = self.raio_atual_px

                if self.imagem_original is not None:
                    self.view.preparar_imagem_para_exibicao(
                        self.imagem_original
                    )
                    self.view.desenhar_canvas(
                        self.leds_selecionados,
                        self.resultados_led_atual,
                    )

                    if self.camera_ativa:
                        self.atualizar_renderizacoes_camera_se_necessario(
                            forcar=True
                        )
                    else:
                        self.atualizar_renderizacoes_visuais(
                            self.leds_selecionados
                        )

        self.configuracao_atual = (
            self.config_repository.salvar_configuracoes_sistema(
                salvar_resultados_analise=self.salvar_resultados_analise,
                raio_atual_px=self.raio_atual_px,
                configuracoes_camera=configuracoes_camera,
            )
        )
        self.configuracoes_camera = (
            self.config_repository.obter_configuracoes_camera()
        )
        perfil_camera_atual = self.perfil_camera_dinamico(
            self.configuracoes_camera
        )
        perfil_camera_alterado = perfil_camera_atual != perfil_camera_anterior

        if self.camera_service is not None and not perfil_camera_alterado:
            self.camera_service.atualizar_configuracoes_camera(
                self.configuracoes_camera
            )

        rotacao_atual = int(
            self.configuracoes_camera.get("rotation", 0)
        )
        rotacao_alterada = rotacao_atual != rotacao_anterior

        if rotacao_alterada:
            # As posições salvas pertencem à orientação anterior da imagem.
            # Elas são apenas ocultadas; o arquivo JSON não é apagado.
            self.guias_leds_fixos_visiveis = False
            self.selecao_manual_camera_ativa = False
            self.leds_manuais_camera = []
            self.leds_selecionados = []
            self.resultados_led_atual = []
            self.view.selecao_manual_camera_visivel = False
            self.view.atualizar_estado_selecao_led(False)
            self.view.atualizar_faixa_resultado()

        if perfil_camera_alterado and self.camera_ativa:
            self.parar_tela_ao_vivo(manter_imagem=True)
            self.root.after(250, self.iniciar_tela_ao_vivo)

        status_salvamento = (
            "ativado"
            if self.salvar_resultados_analise
            else "desativado"
        )

        if perfil_camera_alterado:
            largura_camera, altura_camera, fps_camera = (
                self.obter_parametros_camera_dinamicos()
            )
            fps_texto = "AUTO" if fps_camera <= 0 else f"{fps_camera} FPS"
            mensagem = (
                "perfil da câmera salvo. Reiniciando câmera com "
                f"{largura_camera}x{altura_camera} @ {fps_texto}."
            )
        elif rotacao_alterada:
            mensagem = (
                f"configurações salvas. Rotação alterada para "
                f"{rotacao_atual}°. Reconfigure ou recarregue as posições "
                "dos LEDs para a nova orientação."
            )
        elif self.camera_ativa:
            mensagem = (
                "configurações salvas e enviadas à câmera. "
                f"Salvamento automático {status_salvamento}."
            )
        else:
            mensagem = (
                "configurações salvas. Os ajustes da câmera serão "
                "aplicados ao iniciar a tela ao vivo."
            )

        self.view.atualizar_status(mensagem)
        self.atualizar_painel_inicial()

    def atualizar_renderizacoes_visuais(self, alvo=None) -> None:
        if self.imagem_original is None:
            self.view.limpar_renderizacoes_visuais()
            return

        renderizacoes_visuais = (
            criar_pacote_renderizacoes_visuais(
                self.imagem_original,
                alvo,
            )
        )
        self.view.exibir_renderizacoes_visuais(
            renderizacoes_visuais
        )

    def atualizar_renderizacoes_camera_se_necessario(
        self,
        forcar: bool = False,
    ) -> None:
        """
        Atualiza os painéis auxiliares da câmera em frequência reduzida.

        A imagem principal continua no intervalo normal da câmera. Canal V,
        heatmap, máscara e ROI debug são atualizados a cada 250 ms para não
        sobrecarregar o Tkinter com quatro codificações PNG por frame.
        """
        if (
            not self.camera_ativa
            or self.imagem_original is None
            or self.camera_em_pausa_analise
        ):
            return

        agora = time.monotonic()
        intervalo_s = (
            INTERVALO_RENDERIZACOES_CAMERA_MS
            / 1000.0
        )

        if (
            not forcar
            and agora
            - self.camera_ultima_renderizacao_auxiliar_s
            < intervalo_s
        ):
            return

        alvo = (
            self.resultados_led_atual
            if self.resultados_led_atual
            else self.leds_selecionados
        )

        self.atualizar_renderizacoes_visuais(alvo)
        self.camera_ultima_renderizacao_auxiliar_s = agora


    def obter_parametros_camera_dinamicos(self) -> tuple[int, int, int]:
        configuracoes = (
            self.configuracoes_camera
            if isinstance(self.configuracoes_camera, dict)
            else {}
        )

        try:
            largura = int(
                configuracoes.get("width", CAMERA_LARGURA_DESEJADA)
            )
        except (TypeError, ValueError):
            largura = CAMERA_LARGURA_DESEJADA

        try:
            altura = int(
                configuracoes.get("height", CAMERA_ALTURA_DESEJADA)
            )
        except (TypeError, ValueError):
            altura = CAMERA_ALTURA_DESEJADA

        try:
            fps = int(configuracoes.get("fps", CAMERA_FPS_DESEJADO))
        except (TypeError, ValueError):
            fps = CAMERA_FPS_DESEJADO

        if str(configuracoes.get("fps_mode", "manual")).lower() == "auto":
            fps = 0

        return max(1, largura), max(1, altura), max(0, fps)

    @staticmethod
    def perfil_camera_dinamico(configuracoes_camera: dict | None) -> tuple:
        configuracoes = (
            configuracoes_camera
            if isinstance(configuracoes_camera, dict)
            else {}
        )
        return (
            str(configuracoes.get("resolution_mode", "auto")),
            int(configuracoes.get("width", CAMERA_LARGURA_DESEJADA)),
            int(configuracoes.get("height", CAMERA_ALTURA_DESEJADA)),
            str(configuracoes.get("fps_mode", "manual")),
            int(configuracoes.get("fps", CAMERA_FPS_DESEJADO)),
            str(configuracoes.get("format", "MJPG")).upper(),
        )

    def selecionar_imagem(self, titulo: str):
        caminho_imagem = filedialog.askopenfilename(
            title=titulo,
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.bmp"),
                ("Todos os arquivos", "*.*"),
            ],
        )

        if not caminho_imagem:
            return None, None

        imagem = carregar_imagem_opencv(caminho_imagem)

        if imagem is None:
            messagebox.showerror(
                "Erro",
                "Não foi possível carregar a imagem.\n\nUse PNG, JPG, JPEG ou BMP.",
            )
            return None, None

        return imagem, caminho_imagem

    def carregar_referencia_led_aceso(self) -> None:
        imagem, caminho_imagem = self.selecionar_imagem("Selecione a imagem fixa do LED aceso")

        if imagem is None:
            return

        self.imagem_referencia_acesa = imagem
        self.caminho_referencia_acesa = caminho_imagem
        self.features_referencia_acesa = extrair_features_referencia_led(imagem)
        self.resultados_led_atual = []

        self.salvar_referencias_automaticamente_se_completas()
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("referência de LED aceso carregada.")
        self.atualizar_painel_inicial()

    def carregar_referencia_led_apagado(self) -> None:
        imagem, caminho_imagem = self.selecionar_imagem("Selecione a imagem fixa do LED apagado")

        if imagem is None:
            return

        self.imagem_referencia_apagada = imagem
        self.caminho_referencia_apagada = caminho_imagem
        self.features_referencia_apagada = extrair_features_referencia_led(imagem)
        self.resultados_led_atual = []

        self.salvar_referencias_automaticamente_se_completas()
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("referência de LED apagado carregada.")
        self.atualizar_painel_inicial()

    def salvar_referencias_automaticamente_se_completas(self) -> None:
        if self.features_referencia_acesa is None or self.features_referencia_apagada is None:
            return

        self.configuracao_atual = self.config_repository.salvar_referencias(
            caminho_referencia_acesa=self.caminho_referencia_acesa,
            features_referencia_acesa=self.features_referencia_acesa,
            caminho_referencia_apagada=self.caminho_referencia_apagada,
            features_referencia_apagada=self.features_referencia_apagada,
            raio_atual_px=self.raio_atual_px,
        )

    def salvar_referencias(self) -> None:
        if self.features_referencia_acesa is None:
            messagebox.showwarning("Atenção", "Carregue a referência do LED aceso antes de salvar.")
            return

        if self.features_referencia_apagada is None:
            messagebox.showwarning("Atenção", "Carregue a referência do LED apagado antes de salvar.")
            return

        self.salvar_referencias_automaticamente_se_completas()
        self.view.atualizar_status("referências salvas.")
        self.atualizar_painel_inicial()
        messagebox.showinfo("LumusPCI", f"Referências salvas em:\n{CONFIG_FILE}")

    def carregar_configuracao(self) -> None:
        if not CONFIG_FILE.exists():
            messagebox.showwarning("Atenção", "Nenhuma configuração encontrada.")
            return

        referencia_acesa, referencia_apagada, configuracao = self.config_repository.carregar_referencias()
        self.configuracao_atual = configuracao
        self.salvar_resultados_analise = self.config_repository.obter_salvar_resultados_analise()

        self.caminho_referencia_acesa = referencia_acesa.image_path
        self.caminho_referencia_apagada = referencia_apagada.image_path
        self.raio_atual_px = min(
            RAIO_MAXIMO_LED_PX,
            max(MIN_RADIUS_PX, int(configuracao.get("default_radius_px", self.raio_atual_px))),
        )
        self.view.atualizar_label_raio(self.raio_atual_px)

        self.imagem_referencia_acesa = self.recarregar_imagem_referencia(self.caminho_referencia_acesa)
        self.imagem_referencia_apagada = self.recarregar_imagem_referencia(self.caminho_referencia_apagada)

        if self.imagem_referencia_acesa is not None:
            self.features_referencia_acesa = extrair_features_referencia_led(self.imagem_referencia_acesa)
        else:
            self.features_referencia_acesa = referencia_acesa.features

        if self.imagem_referencia_apagada is not None:
            self.features_referencia_apagada = extrair_features_referencia_led(self.imagem_referencia_apagada)
        else:
            self.features_referencia_apagada = referencia_apagada.features

        self.resultados_led_atual = []
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("referências carregadas.")
        self.atualizar_painel_inicial()

    def recarregar_imagem_referencia(self, caminho_imagem):
        if not caminho_imagem:
            return None

        if not Path(caminho_imagem).exists():
            return None

        return carregar_imagem_opencv(caminho_imagem)

    def carregar_imagem(self) -> None:
        if self.camera_ativa:
            self.parar_tela_ao_vivo(manter_imagem=True)

        imagem, caminho_imagem = self.selecionar_imagem("Selecione a imagem da PCI para análise")

        if imagem is None:
            return

        self.caminho_imagem_atual = caminho_imagem
        self.imagem_original = imagem
        self.altura_original, self.largura_original = self.imagem_original.shape[:2]
        self.leds_selecionados = []
        self.resultados_led_atual = []
        self.modo_atual = "ocioso"
        self.view.atualizar_estado_selecao_led(False)

        self.view.preparar_imagem_para_exibicao(self.imagem_original)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais()
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("imagem carregada. Clique em Selecionar LEDs.")
        self.atualizar_painel_inicial()

    def alternar_tela_ao_vivo(self) -> None:
        if self.camera_ativa:
            self.parar_tela_ao_vivo(manter_imagem=True)
            return

        self.iniciar_tela_ao_vivo()

    def iniciar_tela_ao_vivo(self) -> None:
        if self.camera_ativa:
            return

        if self.camera_service is not None:
            self.camera_service.parar()
            self.camera_service = None

        largura_camera, altura_camera, fps_camera = (
            self.obter_parametros_camera_dinamicos()
        )

        self.camera_service = CameraService(
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
        self.camera_estado_anterior = CameraService.ESTADO_PARADA
        self.camera_desconectada = False
        self.camera_frame_atual = None
        self.camera_ultima_renderizacao_auxiliar_s = 0.0
        self.modo_atual = "tela_ao_vivo"
        self.resultados_led_atual = []
        self.leds_fixos_configurados = self.config_repository.carregar_leds_fixos()

        # Ao iniciar a câmera, as guias fixas voltam ao comportamento padrão.
        self.guias_leds_fixos_visiveis = True
        self.selecao_manual_camera_ativa = False
        self.leds_manuais_camera = []
        self.leds_selecionados = []
        self.view.selecao_manual_camera_visivel = False

        self.view.atualizar_faixa_resultado()
        self.view.atualizar_estado_tela_ao_vivo(True)
        self.view.atualizar_estado_selecao_led(False)
        fps_texto = "AUTO" if fps_camera <= 0 else f"{fps_camera} FPS"
        self.view.atualizar_status(
            f"Conectando câmera em {largura_camera}x{altura_camera} @ {fps_texto}..."
        )
        self.exibir_aviso_camera(
            "CONECTANDO CÂMERA",
            tipo="informacao",
        )

        self.camera_service.iniciar()
        self.agendar_proximo_frame_camera(0)


    def parar_tela_ao_vivo(self, manter_imagem: bool = True) -> None:
        if self.camera_after_id is not None:
            try:
                self.root.after_cancel(self.camera_after_id)
            except Exception:
                pass
            self.camera_after_id = None

        if self.camera_retomada_after_id is not None:
            try:
                self.root.after_cancel(self.camera_retomada_after_id)
            except Exception:
                pass
            self.camera_retomada_after_id = None

        if self.camera_service is not None:
            self.camera_service.parar()
            self.camera_service = None

        self.camera_ativa = False
        self.camera_em_pausa_analise = False
        self.camera_falhas_consecutivas = 0
        self.camera_ultimo_frame_id = -1
        self.camera_estado_anterior = CameraService.ESTADO_PARADA
        self.camera_desconectada = False
        self.camera_ultima_renderizacao_auxiliar_s = 0.0
        self.guias_leds_fixos_visiveis = True
        self.selecao_manual_camera_ativa = False
        self.leds_manuais_camera = []
        self.view.selecao_manual_camera_visivel = False

        self.view.atualizar_estado_tela_ao_vivo(False)
        self.view.atualizar_estado_selecao_led(False)
        self.view.atualizar_faixa_resultado()
        self.ocultar_aviso_camera()

        if not manter_imagem:
            self.camera_frame_atual = None

        if self.modo_atual in ["tela_ao_vivo", "selecionar_leds_camera"]:
            self.modo_atual = "ocioso"

        self.view.atualizar_status("tela ao vivo desativada.")


    def agendar_proximo_frame_camera(
        self,
        atraso_ms: int = INTERVALO_CAMERA_MS,
    ) -> None:
        if not self.camera_ativa or self.camera_service is None:
            return

        if self.camera_after_id is not None:
            return

        self.camera_after_id = self.root.after(
            max(0, int(atraso_ms)),
            self.atualizar_frame_camera,
        )

    def exibir_aviso_camera(
        self,
        texto: str,
        tipo: str = "erro",
    ) -> None:
        """Exibe um aviso não bloqueante sobre a imagem principal."""
        if self.camera_aviso_estado == texto:
            return

        canvas = getattr(self.view, "canvas", None)

        if canvas is None:
            return

        largura_canvas, _ = self.view.obter_tamanho_canvas_principal()
        margem = 24
        x_inicial = margem
        x_final = max(x_inicial + 1, largura_canvas - margem)
        y_inicial = 20
        y_final = 88

        cores = {
            "erro": ("#7F1D1D", "#FECACA"),
            "aviso": ("#78350F", "#FDE68A"),
            "informacao": ("#1E3A5F", "#BFDBFE"),
        }
        cor_fundo, cor_texto = cores.get(tipo, cores["informacao"])

        canvas.delete("aviso_camera")
        canvas.create_rectangle(
            x_inicial,
            y_inicial,
            x_final,
            y_final,
            fill=cor_fundo,
            outline=cor_texto,
            width=2,
            tags=("aviso_camera",),
        )
        canvas.create_text(
            largura_canvas / 2,
            (y_inicial + y_final) / 2,
            text=texto,
            fill=cor_texto,
            font=("Segoe UI", 14, "bold"),
            justify="center",
            tags=("aviso_camera",),
        )
        canvas.tag_raise("aviso_camera")
        self.camera_aviso_estado = texto

    def ocultar_aviso_camera(self) -> None:
        canvas = getattr(self.view, "canvas", None)

        if canvas is not None:
            canvas.delete("aviso_camera")

        self.camera_aviso_estado = None

    def atualizar_frame_camera(self) -> None:
        self.camera_after_id = None

        if not self.camera_ativa or self.camera_service is None:
            return

        snapshot = self.camera_service.obter_snapshot(
            self.camera_ultimo_frame_id
        )
        estado_anterior = self.camera_estado_anterior
        estado_mudou = snapshot.estado != estado_anterior
        self.camera_estado_anterior = snapshot.estado

        if snapshot.estado == CameraService.ESTADO_DESCONECTADA:
            primeira_notificacao = not self.camera_desconectada
            self.camera_desconectada = True
            self.camera_em_pausa_analise = False

            if primeira_notificacao and self.camera_retomada_after_id is not None:
                try:
                    self.root.after_cancel(self.camera_retomada_after_id)
                except Exception:
                    pass
                self.camera_retomada_after_id = None

            self.view.atualizar_faixa_resultado()
            self.view.atualizar_status(
                "Câmera desconectada. Reconectando automaticamente..."
            )
            self.exibir_aviso_camera(
                "CÂMERA DESCONECTADA\nReconectando automaticamente...",
                tipo="erro",
            )

        elif snapshot.estado == CameraService.ESTADO_CONECTANDO:
            if not self.camera_em_pausa_analise:
                self.view.atualizar_status("Conectando câmera...")
                self.exibir_aviso_camera(
                    "CONECTANDO CÂMERA",
                    tipo="informacao",
                )

        elif snapshot.estado == CameraService.ESTADO_ESTABILIZANDO:
            if not self.camera_em_pausa_analise:
                self.view.atualizar_status(snapshot.mensagem)

                if self.camera_desconectada:
                    self.exibir_aviso_camera(
                        "CÂMERA RECONECTADA\nEstabilizando imagem...",
                        tipo="aviso",
                    )
                else:
                    self.exibir_aviso_camera(
                        "CÂMERA CONECTADA\nEstabilizando imagem...",
                        tipo="informacao",
                    )

        elif snapshot.estado == CameraService.ESTADO_CONECTADA:
            foi_reconectada = self.camera_desconectada
            self.camera_desconectada = False
            self.ocultar_aviso_camera()

            if not self.camera_em_pausa_analise and (estado_mudou or foi_reconectada):
                if foi_reconectada:
                    resolucao_texto = ""
                    if snapshot.resolucao is not None:
                        resolucao_texto = (
                            f" Resolução real: {snapshot.resolucao[0]}x{snapshot.resolucao[1]}."
                        )
                    self.view.atualizar_status(
                        "Câmera reconectada." + resolucao_texto + " Pressione ENTER para analisar."
                    )
                else:
                    resolucao_texto = ""
                    if snapshot.resolucao is not None:
                        resolucao_texto = (
                            f" Resolução real: {snapshot.resolucao[0]}x{snapshot.resolucao[1]}."
                        )
                    self.view.atualizar_status(
                        "tela ao vivo ativa." + resolucao_texto + " Pressione ENTER para capturar e analisar."
                    )

        if snapshot.frame is not None:
            self.camera_ultimo_frame_id = snapshot.frame_id
            self.camera_frame_atual = snapshot.frame

            if not self.camera_em_pausa_analise:
                self.imagem_original = snapshot.frame.copy()
                self.caminho_imagem_atual = "camera_usb"
                self.altura_original, self.largura_original = (
                    self.imagem_original.shape[:2]
                )

                if self.leds_manuais_camera:
                    self.leds_selecionados = [
                        LedSelection(
                            id=led.id,
                            centro_x=led.centro_x,
                            centro_y=led.centro_y,
                            raio=led.raio,
                        )
                        for led in self.leds_manuais_camera
                    ]
                    self.view.selecao_manual_camera_visivel = True
                elif (
                    self.guias_leds_fixos_visiveis
                    and self.leds_fixos_configurados
                ):
                    self.leds_selecionados = (
                        self.adaptar_leds_fixos_para_frame_camera(
                            self.leds_fixos_configurados
                        )
                    )
                    self.view.selecao_manual_camera_visivel = False
                else:
                    self.leds_selecionados = []
                    self.view.selecao_manual_camera_visivel = False

                self.resultados_led_atual = []

                self.view.preparar_imagem_para_exibicao(
                    self.imagem_original
                )
                self.view.desenhar_canvas(
                    self.leds_selecionados,
                    self.resultados_led_atual,
                )
                self.atualizar_renderizacoes_camera_se_necessario()

        self.agendar_proximo_frame_camera()


    def obter_leds_fixos_validos_para_imagem(
        self,
        leds_fixos: list[LedSelection],
    ) -> list[LedSelection]:
        leds_fixos_validos = []

        for led_fixo in leds_fixos:
            led_adaptado = led_fixo.adaptar_para_resolucao(
                largura_destino=self.largura_original,
                altura_destino=self.altura_original,
                raio_minimo=MIN_RADIUS_PX,
                raio_maximo=RAIO_MAXIMO_LED_PX,
            )

            if validar_centro_led(
                led_adaptado.centro_x,
                led_adaptado.centro_y,
                led_adaptado.raio,
                self.largura_original,
                self.altura_original,
            ):
                leds_fixos_validos.append(led_adaptado)

        return leds_fixos_validos

    def adaptar_leds_fixos_para_frame_camera(
        self,
        leds_fixos: list[LedSelection],
    ) -> list[LedSelection]:
        if not leds_fixos or self.largura_original <= 0 or self.altura_original <= 0:
            return []

        if all(
            led_fixo.possui_coordenadas_normalizadas()
            for led_fixo in leds_fixos
        ):
            leds_adaptados_normalizados = []

            for led_fixo in leds_fixos:
                led_adaptado = led_fixo.adaptar_para_resolucao(
                    largura_destino=self.largura_original,
                    altura_destino=self.altura_original,
                    raio_minimo=MIN_RADIUS_PX,
                    raio_maximo=RAIO_MAXIMO_LED_PX,
                )

                if not validar_centro_led(
                    led_adaptado.centro_x,
                    led_adaptado.centro_y,
                    led_adaptado.raio,
                    self.largura_original,
                    self.altura_original,
                ):
                    break

                leds_adaptados_normalizados.append(led_adaptado)

            if len(leds_adaptados_normalizados) == len(leds_fixos):
                return leds_adaptados_normalizados

        todos_validos_sem_escala = all(
            validar_centro_led(
                led_fixo.centro_x,
                led_fixo.centro_y,
                led_fixo.raio,
                self.largura_original,
                self.altura_original,
            )
            for led_fixo in leds_fixos
        )

        if todos_validos_sem_escala:
            return [
                LedSelection(
                    id=led_fixo.id,
                    centro_x=led_fixo.centro_x,
                    centro_y=led_fixo.centro_y,
                    raio=led_fixo.raio,
                )
                for led_fixo in leds_fixos
            ]

        limite_esquerdo = min(
            led_fixo.centro_x - led_fixo.raio
            for led_fixo in leds_fixos
        )
        limite_superior = min(
            led_fixo.centro_y - led_fixo.raio
            for led_fixo in leds_fixos
        )
        limite_direito = max(
            led_fixo.centro_x + led_fixo.raio
            for led_fixo in leds_fixos
        )
        limite_inferior = max(
            led_fixo.centro_y + led_fixo.raio
            for led_fixo in leds_fixos
        )

        largura_padrao = max(1, limite_direito - limite_esquerdo)
        altura_padrao = max(1, limite_inferior - limite_superior)

        margem_x = max(
            12,
            int(self.largura_original * MARGEM_GUIAS_CAMERA_PERCENTUAL),
        )
        margem_y = max(
            12,
            int(self.altura_original * MARGEM_GUIAS_CAMERA_PERCENTUAL),
        )

        largura_util = max(1, self.largura_original - (margem_x * 2))
        altura_util = max(1, self.altura_original - (margem_y * 2))

        escala = min(
            largura_util / largura_padrao,
            altura_util / altura_padrao,
        )

        largura_padrao_escalada = largura_padrao * escala
        altura_padrao_escalada = altura_padrao * escala

        deslocamento_x = (
            (self.largura_original - largura_padrao_escalada) / 2
            - (limite_esquerdo * escala)
        )
        deslocamento_y = (
            (self.altura_original - altura_padrao_escalada) / 2
            - (limite_superior * escala)
        )

        leds_adaptados = []

        for led_fixo in leds_fixos:
            centro_x = int(round((led_fixo.centro_x * escala) + deslocamento_x))
            centro_y = int(round((led_fixo.centro_y * escala) + deslocamento_y))
            raio = max(
                MIN_RADIUS_PX,
                int(round(led_fixo.raio * escala)),
            )

            if validar_centro_led(
                centro_x,
                centro_y,
                raio,
                self.largura_original,
                self.altura_original,
            ):
                leds_adaptados.append(
                    LedSelection(
                        id=led_fixo.id,
                        centro_x=centro_x,
                        centro_y=centro_y,
                        raio=raio,
                    )
                )

        return leds_adaptados

    def capturar_frame_camera_para_analise(self, evento=None) -> None:
        if not self.camera_ativa or self.camera_em_pausa_analise:
            return

        if (
            self.camera_service is None
            or self.camera_desconectada
            or self.camera_estado_anterior
            != CameraService.ESTADO_CONECTADA
        ):
            self.view.atualizar_status(
                "Câmera desconectada. Aguarde a reconexão automática."
            )
            return

        if self.camera_frame_atual is None:
            self.view.atualizar_status(
                "aguarde a câmera terminar de estabilizar."
            )
            return

        self.camera_em_pausa_analise = True
        frame_capturado = self.camera_frame_atual.copy()

        self.imagem_original = frame_capturado
        self.caminho_imagem_atual = "camera_usb"
        self.altura_original, self.largura_original = (
            self.imagem_original.shape[:2]
        )

        if self.leds_manuais_camera and not self.guias_leds_fixos_visiveis:
            leds_validos = []

            for led in self.leds_manuais_camera:
                if validar_centro_led(
                    led.centro_x,
                    led.centro_y,
                    led.raio,
                    self.largura_original,
                    self.altura_original,
                ):
                    leds_validos.append(
                        LedSelection(
                            id=led.id,
                            centro_x=led.centro_x,
                            centro_y=led.centro_y,
                            raio=led.raio,
                        )
                    )
        elif self.guias_leds_fixos_visiveis:
            self.leds_fixos_configurados = (
                self.config_repository.carregar_leds_fixos()
            )
            leds_validos = self.adaptar_leds_fixos_para_frame_camera(
                self.leds_fixos_configurados
            )
        else:
            leds_validos = []

        if not leds_validos:
            self.camera_em_pausa_analise = False
            self.view.atualizar_status(
                "Nenhum LED selecionado. Use Carregar LEDs ou Selecionar LEDs."
            )
            return

        self.leds_selecionados = leds_validos
        self.resultados_led_atual = []

        self.view.preparar_imagem_para_exibicao(
            self.imagem_original
        )
        self.view.desenhar_canvas(
            self.leds_selecionados,
            self.resultados_led_atual,
        )
        self.view.atualizar_status(
            "frame capturado. Executando análise..."
        )

        self.analisar_led_selecionado()

        if not self.camera_ativa:
            return

        if self.camera_desconectada:
            self.camera_em_pausa_analise = False
            self.view.atualizar_faixa_resultado()
            self.view.atualizar_status(
                "Câmera desconectada. Reconectando automaticamente..."
            )
            return

        self.view.atualizar_status(
            "análise concluída. Retornando à câmera em 3 segundos..."
        )

        if self.camera_retomada_after_id is not None:
            try:
                self.root.after_cancel(self.camera_retomada_after_id)
            except Exception:
                pass

        self.camera_retomada_after_id = self.root.after(
            TEMPO_RESULTADO_CAMERA_MS,
            self.retomar_tela_ao_vivo_apos_analise,
        )


    def retomar_tela_ao_vivo_apos_analise(self) -> None:
        self.camera_retomada_after_id = None

        if not self.camera_ativa or self.camera_service is None:
            return

        self.camera_em_pausa_analise = False
        self.resultados_led_atual = []
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_estado_tela_ao_vivo(True)

        if self.selecao_manual_camera_ativa:
            self.modo_atual = "selecionar_leds_camera"
            self.view.selecao_manual_camera_visivel = True
            self.view.atualizar_estado_selecao_led(True)
        else:
            self.modo_atual = "tela_ao_vivo"
            self.view.selecao_manual_camera_visivel = bool(
                self.leds_manuais_camera
            )
            self.view.atualizar_estado_selecao_led(False)

        self.atualizar_renderizacoes_camera_se_necessario(
            forcar=True
        )

        if self.camera_desconectada:
            self.view.atualizar_status(
                "Câmera desconectada. Reconectando automaticamente..."
            )
        elif self.selecao_manual_camera_ativa:
            self.view.atualizar_status(
                "seleção manual ativa na câmera. Clique nos LEDs ou pressione ENTER."
            )
        else:
            self.view.atualizar_status(
                "tela ao vivo ativa. Pressione ENTER para capturar e analisar."
            )


    def iniciar_selecao_led(self) -> None:
        if self.camera_ativa:
            if (
                self.camera_desconectada
                or self.camera_estado_anterior
                != CameraService.ESTADO_CONECTADA
            ):
                self.view.atualizar_status(
                    "Aguarde a câmera conectar antes de selecionar LEDs."
                )
                return

            if self.selecao_manual_camera_ativa:
                self.selecao_manual_camera_ativa = False
                self.modo_atual = "tela_ao_vivo"
                self.view.atualizar_estado_selecao_led(False)
                self.view.selecao_manual_camera_visivel = bool(
                    self.leds_manuais_camera
                )
                self.view.desenhar_canvas(
                    self.leds_selecionados,
                    self.resultados_led_atual,
                )
                self.view.atualizar_status(
                    "seleção manual desativada. As seleções temporárias foram mantidas."
                )
                return

            # Durante o teste manual, as guias fixas ficam ocultas sem serem
            # removidas do arquivo de configuração.
            self.guias_leds_fixos_visiveis = False
            self.selecao_manual_camera_ativa = True
            self.modo_atual = "selecionar_leds_camera"
            self.resultados_led_atual = []
            self.leds_selecionados = [
                LedSelection(
                    id=led.id,
                    centro_x=led.centro_x,
                    centro_y=led.centro_y,
                    raio=led.raio,
                )
                for led in self.leds_manuais_camera
            ]

            self.view.selecao_manual_camera_visivel = True
            self.view.atualizar_estado_selecao_led(True)
            self.view.preparar_imagem_para_exibicao(self.imagem_original)
            self.view.desenhar_canvas(
                self.leds_selecionados,
                self.resultados_led_atual,
            )
            self.view.atualizar_faixa_resultado()
            self.view.atualizar_status(
                "seleção manual ativa na câmera: clique nos LEDs e pressione ENTER para analisar."
            )
            return

        if self.imagem_original is None:
            messagebox.showwarning("Atenção", "Carregue a imagem da PCI antes de selecionar LEDs.")
            return

        if self.modo_atual == "selecionar_leds_analise":
            self.modo_atual = "ocioso"
            self.view.atualizar_estado_selecao_led(False)
            self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
            self.atualizar_renderizacoes_visuais(self.leds_selecionados)
            self.view.atualizar_status("modo seleção desativado.")
            self.atualizar_painel_inicial()
            return

        self.modo_atual = "selecionar_leds_analise"
        self.resultados_led_atual = []
        self.view.atualizar_estado_selecao_led(True)
        self.view.preparar_imagem_para_exibicao(self.imagem_original)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais(self.leds_selecionados)
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("modo seleção ativo: clique em um ou mais LEDs. Depois clique em Analisar.")
        self.atualizar_painel_inicial()


    def configurar_leds_fixos(self) -> None:
        if self.camera_ativa:
            self.parar_tela_ao_vivo(manter_imagem=True)

        if self.imagem_original is None:
            messagebox.showwarning("Atenção", "Carregue a imagem da PCI antes de configurar LEDs fixos.")
            return

        self.modo_atual = "configurar_leds_fixos"
        self.leds_selecionados = []
        self.resultados_led_atual = []

        self.view.atualizar_estado_selecao_led(True)
        self.view.preparar_imagem_para_exibicao(self.imagem_original)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais(self.leds_selecionados)
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("modo configuração de LEDs fixos: clique nos LEDs e depois salve nas configurações.")
        self.atualizar_painel_inicial()

    def salvar_leds_fixos(self) -> None:
        if not self.leds_selecionados:
            messagebox.showwarning("Atenção", "Nenhum LED foi selecionado para salvar como posição fixa.")
            return

        self.leds_fixos_configurados = [
            LedSelection(
                id=led_selecionado.id,
                centro_x=led_selecionado.centro_x,
                centro_y=led_selecionado.centro_y,
                raio=led_selecionado.raio,
            ).com_normalizacao(
                largura_base=self.largura_original,
                altura_base=self.altura_original,
            )
            for led_selecionado in self.leds_selecionados
        ]

        self.configuracao_atual = self.config_repository.salvar_leds_fixos(
            self.leds_fixos_configurados,
            largura_base=self.largura_original,
            altura_base=self.altura_original,
        )

        self.modo_atual = "ocioso"
        self.view.atualizar_estado_selecao_led(False)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais(self.leds_selecionados)
        self.view.atualizar_status(f"{len(self.leds_fixos_configurados)} LEDs fixos salvos.")
        self.atualizar_painel_inicial()

        messagebox.showinfo("LumusPCI", f"{len(self.leds_fixos_configurados)} LEDs fixos salvos com sucesso.")

    def carregar_leds_fixos(self) -> None:
        if self.imagem_original is None:
            messagebox.showwarning(
                "Atenção",
                "Carregue a imagem da PCI antes de carregar LEDs fixos.",
            )
            return

        self.leds_fixos_configurados = self.config_repository.carregar_leds_fixos()

        if not self.leds_fixos_configurados:
            messagebox.showwarning(
                "Atenção",
                "Nenhum LED fixo configurado foi encontrado.",
            )
            return

        if self.camera_ativa:
            self.guias_leds_fixos_visiveis = True
            self.selecao_manual_camera_ativa = False
            self.leds_manuais_camera = []
            self.view.selecao_manual_camera_visivel = False

            leds_fixos_validos = self.adaptar_leds_fixos_para_frame_camera(
                self.leds_fixos_configurados
            )
        else:
            leds_fixos_validos = self.obter_leds_fixos_validos_para_imagem(
                self.leds_fixos_configurados
            )

        if not leds_fixos_validos:
            messagebox.showwarning(
                "Atenção",
                "Os LEDs fixos salvos não são válidos para a imagem carregada.",
            )
            return

        self.leds_selecionados = leds_fixos_validos
        self.resultados_led_atual = []

        if self.camera_ativa:
            self.modo_atual = "tela_ao_vivo"
            self.view.atualizar_estado_tela_ao_vivo(True)
            self.view.atualizar_estado_selecao_led(False)
            self.view.atualizar_status(
                f"{len(self.leds_selecionados)} guias de LEDs carregadas para a câmera."
            )
        else:
            self.modo_atual = "ocioso"
            self.view.atualizar_estado_selecao_led(False)
            self.view.atualizar_status(
                f"{len(self.leds_selecionados)} LEDs fixos carregados. Clique em Analisar."
            )

        self.view.preparar_imagem_para_exibicao(self.imagem_original)
        self.view.desenhar_canvas(
            self.leds_selecionados,
            self.resultados_led_atual,
        )

        if self.camera_ativa:
            self.atualizar_renderizacoes_camera_se_necessario(
                forcar=True
            )
        else:
            self.atualizar_renderizacoes_visuais(
                self.leds_selecionados
            )

        self.view.atualizar_faixa_resultado()
        self.atualizar_painel_inicial()


    def evento_clique_esquerdo(self, evento) -> None:
        if self.imagem_original is None:
            return

        if self.modo_atual in [
            "selecionar_leds_analise",
            "configurar_leds_fixos",
            "selecionar_leds_camera",
        ]:
            self.selecionar_led_para_analise(evento.x, evento.y)


    def _obter_led_ja_selecionado_proximo(
        self,
        centro_x: int,
        centro_y: int,
        raio: int,
    ):
        """
        Retorna um LED existente quando o novo clique ocorre praticamente
        sobre uma seleção já registrada.

        Isso impede que vários cliques no mesmo LED criem TESTE_001,
        TESTE_002, TESTE_003... na mesma posição.
        """
        if self.modo_atual == "selecionar_leds_camera":
            leds_existentes = self.leds_manuais_camera
        else:
            leds_existentes = self.leds_selecionados

        for led in leds_existentes:
            raio_existente = max(
                1,
                int(getattr(led, "raio", raio)),
            )
            limite_distancia = max(
                10,
                int(max(raio, raio_existente) * 0.85),
            )

            delta_x = int(led.centro_x) - centro_x
            delta_y = int(led.centro_y) - centro_y

            if (
                delta_x * delta_x + delta_y * delta_y
                <= limite_distancia * limite_distancia
            ):
                return led

        return None

    def _mostrar_confirmacao_selecao_na_lupa(
        self,
        canvas_x: int,
        canvas_y: int,
        led,
        tipo: str,
    ) -> None:
        """
        Registra e redesenha imediatamente o feedback visual da lupa.

        tipo:
        - "selecionado": novo LED confirmado;
        - "duplicado": clique sobre um LED já selecionado.
        """
        if led is None:
            return

        self.view._lupa_confirmacao = {
            "tipo": tipo,
            "id": str(getattr(led, "id", "LED")),
            "centro_x": int(led.centro_x),
            "centro_y": int(led.centro_y),
            "total": len(self.leds_selecionados),
            "expira_em": time.monotonic() + 1.25,
        }

        # O clique pode ocorrer sem movimento posterior do mouse. Por isso,
        # a lupa é redesenhada aqui, em vez de esperar outro evento <Motion>.
        self.view.desenhar_lupa_canvas(
            canvas_x=canvas_x,
            canvas_y=canvas_y,
            imagem_x=int(led.centro_x),
            imagem_y=int(led.centro_y),
        )

    def selecionar_led_para_analise(
        self,
        canvas_x: int,
        canvas_y: int,
    ) -> None:
        coordenadas_imagem = (
            self.view.converter_canvas_para_imagem_original(
                canvas_x,
                canvas_y,
            )
        )

        if coordenadas_imagem is None:
            self.view.atualizar_status(
                "clique ignorado: fora da imagem exibida."
            )
            return

        centro_x, centro_y = coordenadas_imagem
        raio = min(
            RAIO_MAXIMO_LED_PX,
            self.raio_atual_px,
        )

        if self.raio_atual_px != raio:
            self.raio_atual_px = raio
            self.view.atualizar_label_raio(
                self.raio_atual_px
            )

        if not validar_centro_led(
            centro_x,
            centro_y,
            raio,
            self.largura_original,
            self.altura_original,
        ):
            self.view.atualizar_status(
                "clique ignorado: LED fora da área válida da imagem."
            )
            return

        led_duplicado = (
            self._obter_led_ja_selecionado_proximo(
                centro_x,
                centro_y,
                raio,
            )
        )

        if led_duplicado is not None:
            self._mostrar_confirmacao_selecao_na_lupa(
                canvas_x=canvas_x,
                canvas_y=canvas_y,
                led=led_duplicado,
                tipo="duplicado",
            )
            self.view.atualizar_status(
                f"{led_duplicado.id} já está selecionado. "
                f"Total mantido: {len(self.leds_selecionados)}."
            )
            return

        if self.modo_atual == "selecionar_leds_camera":
            id_led = (
                f"TESTE_"
                f"{len(self.leds_manuais_camera) + 1:03d}"
            )
            led_confirmado = LedSelection(
                id=id_led,
                centro_x=centro_x,
                centro_y=centro_y,
                raio=raio,
            )
            self.leds_manuais_camera.append(
                led_confirmado
            )
            self.leds_selecionados = [
                LedSelection(
                    id=led.id,
                    centro_x=led.centro_x,
                    centro_y=led.centro_y,
                    raio=led.raio,
                )
                for led in self.leds_manuais_camera
            ]
            self.guias_leds_fixos_visiveis = False
            self.view.selecao_manual_camera_visivel = True
        else:
            id_led = (
                f"LED_"
                f"{len(self.leds_selecionados) + 1:03d}"
            )
            led_confirmado = LedSelection(
                id=id_led,
                centro_x=centro_x,
                centro_y=centro_y,
                raio=raio,
            )
            self.leds_selecionados.append(
                led_confirmado
            )

        self.resultados_led_atual = []

        self.view.preparar_imagem_para_exibicao(
            self.imagem_original
        )
        self.view.desenhar_canvas(
            self.leds_selecionados,
            self.resultados_led_atual,
        )

        if self.camera_ativa:
            self.atualizar_renderizacoes_camera_se_necessario(
                forcar=True
            )
        else:
            self.atualizar_renderizacoes_visuais(
                self.leds_selecionados
            )

        self.view.atualizar_faixa_resultado()

        # A confirmação é desenhada depois da atualização do Canvas para
        # permanecer acima da imagem e das marcações principais.
        self._mostrar_confirmacao_selecao_na_lupa(
            canvas_x=canvas_x,
            canvas_y=canvas_y,
            led=led_confirmado,
            tipo="selecionado",
        )

        total_selecionado = len(
            self.leds_selecionados
        )

        if self.modo_atual == "configurar_leds_fixos":
            self.view.atualizar_status(
                f"{id_led} fixo selecionado. "
                f"Total: {total_selecionado}. "
                "Depois salve em Configurações > Salvar LEDs."
            )
        elif self.modo_atual == "selecionar_leds_camera":
            self.view.atualizar_status(
                f"{id_led} selecionado para teste. "
                f"Total: {total_selecionado}. "
                "Continue clicando ou pressione ENTER."
            )
        else:
            self.view.atualizar_status(
                f"{id_led} selecionado. "
                f"Total: {total_selecionado}. "
                "Continue clicando ou clique em Analisar."
            )

        self.atualizar_painel_inicial()


    def referencias_disponiveis(self) -> bool:
        return self.features_referencia_acesa is not None and self.features_referencia_apagada is not None

    def carregar_referencias_automaticamente_se_necessario(self) -> None:
        if self.referencias_disponiveis():
            return

        if not CONFIG_FILE.exists():
            return

        referencia_acesa, referencia_apagada, configuracao = self.config_repository.carregar_referencias()
        self.configuracao_atual = configuracao
        self.salvar_resultados_analise = self.config_repository.obter_salvar_resultados_analise()
        self.features_referencia_acesa = referencia_acesa.features
        self.features_referencia_apagada = referencia_apagada.features
        self.caminho_referencia_acesa = referencia_acesa.image_path
        self.caminho_referencia_apagada = referencia_apagada.image_path

    def analisar_led_selecionado(self) -> None:
        # Durante a câmera ao vivo, o botão Analisar usa o mesmo fluxo seguro
        # do ENTER: congela o frame, analisa e retorna após três segundos.
        if self.camera_ativa and not self.camera_em_pausa_analise:
            self.capturar_frame_camera_para_analise()
            return

        if self.imagem_original is None:
            messagebox.showwarning("Atenção", "Carregue uma imagem da PCI antes de analisar.")
            return

        if not self.leds_selecionados:
            messagebox.showwarning("Atenção", "Selecione um ou mais LEDs na imagem da PCI antes de analisar.")
            return

        self.carregar_referencias_automaticamente_se_necessario()

        if not self.referencias_disponiveis():
            messagebox.showwarning(
                "Atenção",
                "Carregue ou salve as duas referências fixas antes de analisar.\n\n"
                "São necessárias uma referência de LED aceso e uma referência de LED apagado.",
            )
            return

        classificador = ReferenceLedClassifier(
            features_referencia_acesa=self.features_referencia_acesa,
            features_referencia_apagada=self.features_referencia_apagada,
        )

        resultados_led = []

        for led_selecionado in self.leds_selecionados:
            features_atual = extrair_features_led(
                self.imagem_original,
                led_selecionado.centro_x,
                led_selecionado.centro_y,
                led_selecionado.raio,
            )

            resultado_led = classificador.classificar_led_por_referencia(
                features_atual=features_atual,
                centro_x=led_selecionado.centro_x,
                centro_y=led_selecionado.centro_y,
                raio=led_selecionado.raio,
            )
            resultado_led.id = led_selecionado.id
            resultados_led.append(resultado_led)

        self.resultados_led_atual = resultados_led
        self.modo_atual = "ocioso"
        self.view.atualizar_estado_selecao_led(False)
        output_paths = self.result_repository.salvar_resultado_analise_multiplos(
            imagem_original=self.imagem_original,
            resultados_led=resultados_led,
            caminho_imagem_atual=self.caminho_imagem_atual,
            caminho_referencia_acesa=self.caminho_referencia_acesa,
            caminho_referencia_apagada=self.caminho_referencia_apagada,
            features_referencia_acesa=self.features_referencia_acesa,
            features_referencia_apagada=self.features_referencia_apagada,
            leds_selecionados=self.leds_selecionados,
            salvar_resultados_analise=self.salvar_resultados_analise,
        )

        imagem_resultado = criar_imagem_resultados_visuais(self.imagem_original, resultados_led)
        self.view.preparar_imagem_para_exibicao(imagem_resultado)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais(resultados_led)
        self.view.escrever_resultados(formatar_resultado_textual_multiplos(resultados_led, output_paths))
        self.view.atualizar_faixa_resultado_multiplos(resultados_led)
        self.view.atualizar_status("análise concluída.")


    def aumentar_raio(self) -> None:
        self.raio_atual_px = min(RAIO_MAXIMO_LED_PX, self.raio_atual_px + 1)
        self.view.atualizar_label_raio(self.raio_atual_px)

        if self.camera_ativa and self.leds_manuais_camera:
            for led in self.leds_manuais_camera:
                led.raio = self.raio_atual_px

            self.leds_selecionados = [
                LedSelection(
                    id=led.id,
                    centro_x=led.centro_x,
                    centro_y=led.centro_y,
                    raio=led.raio,
                )
                for led in self.leds_manuais_camera
            ]
        elif self.leds_selecionados:
            for led_selecionado in self.leds_selecionados:
                led_selecionado.raio = self.raio_atual_px

        if self.leds_selecionados:
            self.resultados_led_atual = []
            self.view.preparar_imagem_para_exibicao(self.imagem_original)
            self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)

            if self.camera_ativa:
                self.atualizar_renderizacoes_camera_se_necessario(
                    forcar=True
                )
            else:
                self.atualizar_renderizacoes_visuais(
                    self.leds_selecionados
                )

            self.view.atualizar_faixa_resultado()

        self.view.atualizar_status(f"raio ajustado para {self.raio_atual_px}px.")
        self.atualizar_painel_inicial()


    def diminuir_raio(self) -> None:
        self.raio_atual_px = max(MIN_RADIUS_PX, self.raio_atual_px - 1)
        self.view.atualizar_label_raio(self.raio_atual_px)

        if self.camera_ativa and self.leds_manuais_camera:
            for led in self.leds_manuais_camera:
                led.raio = self.raio_atual_px

            self.leds_selecionados = [
                LedSelection(
                    id=led.id,
                    centro_x=led.centro_x,
                    centro_y=led.centro_y,
                    raio=led.raio,
                )
                for led in self.leds_manuais_camera
            ]
        elif self.leds_selecionados:
            for led_selecionado in self.leds_selecionados:
                led_selecionado.raio = self.raio_atual_px

        if self.leds_selecionados:
            self.resultados_led_atual = []
            self.view.preparar_imagem_para_exibicao(self.imagem_original)
            self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)

            if self.camera_ativa:
                self.atualizar_renderizacoes_camera_se_necessario(
                    forcar=True
                )
            else:
                self.atualizar_renderizacoes_visuais(
                    self.leds_selecionados
                )

            self.view.atualizar_faixa_resultado()

        self.view.atualizar_status(f"raio ajustado para {self.raio_atual_px}px.")
        self.atualizar_painel_inicial()


    def limpar_tela(self) -> None:
        if self.camera_ativa:
            # Limpa apenas os elementos temporários da inspeção. A câmera e
            # os LEDs fixos salvos no JSON continuam ativos/disponíveis.
            if self.camera_retomada_after_id is not None:
                try:
                    self.root.after_cancel(self.camera_retomada_after_id)
                except Exception:
                    pass
                self.camera_retomada_after_id = None

            self.camera_em_pausa_analise = False
            self.guias_leds_fixos_visiveis = False
            self.selecao_manual_camera_ativa = False
            self.leds_manuais_camera = []
            self.leds_selecionados = []
            self.resultados_led_atual = []
            self.modo_atual = "tela_ao_vivo"

            self.view.selecao_manual_camera_visivel = False
            self.view.atualizar_estado_selecao_led(False)
            self.view.atualizar_faixa_resultado()

            if self.camera_frame_atual is not None:
                self.imagem_original = self.camera_frame_atual.copy()
                self.altura_original, self.largura_original = (
                    self.imagem_original.shape[:2]
                )
                self.view.preparar_imagem_para_exibicao(
                    self.imagem_original
                )

            self.view.desenhar_canvas([], [])
            self.view.atualizar_status(
                "seleção e guias fixas removidas. Use Selecionar LEDs para testar ou Carregar LEDs para restaurar as guias."
            )
            self.atualizar_painel_inicial()
            return

        self.modo_atual = "ocioso"
        self.view.atualizar_estado_selecao_led(False)
        self.leds_selecionados = []
        self.resultados_led_atual = []

        if self.imagem_original is not None:
            self.view.preparar_imagem_para_exibicao(self.imagem_original)

        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais()
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status("seleção limpa. A imagem e as referências foram mantidas.")
        self.atualizar_painel_inicial()
