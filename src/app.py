from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from config import CONFIG_DIR, CONFIG_FILE, DEFAULT_RADIUS_PX
from src.core.classifier import ReferenceLedClassifier
from src.core.debug_formatter import formatar_painel_inicial, formatar_resultado_textual_multiplos
from src.core.feature_extractor import extrair_features_led, extrair_features_referencia_led, validar_centro_led
from src.core.visual_renderer import criar_imagem_resultados_visuais, criar_pacote_renderizacoes_visuais
from src.infra.config_repository import ConfigRepository
from src.infra.image_io import carregar_imagem_opencv
from src.infra.result_repository import ResultRepository
from src.models.led_selection import LedSelection
from src.ui.main_window import LumusPCIView


RAIO_MAXIMO_LED_PX = 15


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
        self.resultados_led_atual = []
        self.configuracao_atual = {}

        self.config_repository = ConfigRepository()
        self.result_repository = ResultRepository()
        self.salvar_resultados_analise = self.config_repository.obter_salvar_resultados_analise()

        self.criar_pastas()
        self.carregar_referencias_automaticamente_se_necessario()
        self.view = LumusPCIView(
            root=self.root,
            callbacks=self.criar_callbacks(),
            raio_atual_px=self.raio_atual_px,
        )
        self.view.atualizar_estado_selecao_led(False)
        self.atualizar_painel_inicial()

    def criar_callbacks(self) -> dict:
        return {
            "carregar_referencia_led_aceso": self.carregar_referencia_led_aceso,
            "carregar_referencia_led_apagado": self.carregar_referencia_led_apagado,
            "salvar_referencias": self.salvar_referencias,
            "carregar_configuracao": self.carregar_configuracao,
            "carregar_imagem": self.carregar_imagem,
            "iniciar_selecao_led": self.iniciar_selecao_led,
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
        self.view.abrir_janela_configuracoes(
            salvar_resultados_analise=self.salvar_resultados_analise,
            callback_salvar=self.salvar_configuracoes_sistema,
        )

    def salvar_configuracoes_sistema(self, salvar_resultados_analise: bool) -> None:
        self.salvar_resultados_analise = bool(salvar_resultados_analise)
        self.configuracao_atual = self.config_repository.salvar_configuracoes_sistema(
            salvar_resultados_analise=self.salvar_resultados_analise,
        )

        status = "ativado" if self.salvar_resultados_analise else "desativado"
        self.view.atualizar_status(f"salvamento automático {status}.")
        self.atualizar_painel_inicial()

    def atualizar_renderizacoes_visuais(self, alvo=None) -> None:
        if self.imagem_original is None:
            self.view.limpar_renderizacoes_visuais()
            return

        renderizacoes_visuais = criar_pacote_renderizacoes_visuais(self.imagem_original, alvo)
        self.view.exibir_renderizacoes_visuais(renderizacoes_visuais)

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
            max(3, int(configuracao.get("default_radius_px", self.raio_atual_px))),
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

    def iniciar_selecao_led(self) -> None:
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

    def evento_clique_esquerdo(self, evento) -> None:
        if self.imagem_original is None:
            return

        if self.modo_atual == "selecionar_leds_analise":
            self.selecionar_led_para_analise(evento.x, evento.y)

    def selecionar_led_para_analise(self, canvas_x: int, canvas_y: int) -> None:
        coordenadas_imagem = self.view.converter_canvas_para_imagem_original(canvas_x, canvas_y)

        if coordenadas_imagem is None:
            self.view.atualizar_status("clique ignorado: fora da imagem exibida.")
            return

        centro_x, centro_y = coordenadas_imagem
        raio = min(RAIO_MAXIMO_LED_PX, self.raio_atual_px)

        if self.raio_atual_px != raio:
            self.raio_atual_px = raio
            self.view.atualizar_label_raio(self.raio_atual_px)

        if not validar_centro_led(centro_x, centro_y, raio, self.largura_original, self.altura_original):
            self.view.atualizar_status("clique ignorado: LED fora da área válida da imagem.")
            return

        id_led = f"LED_{len(self.leds_selecionados) + 1:03d}"
        self.leds_selecionados.append(
            LedSelection(
                id=id_led,
                centro_x=centro_x,
                centro_y=centro_y,
                raio=raio,
            )
        )
        self.resultados_led_atual = []

        self.view.preparar_imagem_para_exibicao(self.imagem_original)
        self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
        self.atualizar_renderizacoes_visuais(self.leds_selecionados)
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status(f"{id_led} selecionado. Continue clicando ou clique em Analisar.")
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

        if self.leds_selecionados:
            for led_selecionado in self.leds_selecionados:
                led_selecionado.raio = self.raio_atual_px
            self.resultados_led_atual = []
            self.view.preparar_imagem_para_exibicao(self.imagem_original)
            self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
            self.atualizar_renderizacoes_visuais(self.leds_selecionados)
            self.view.atualizar_faixa_resultado()

        self.view.atualizar_status(f"raio ajustado para {self.raio_atual_px}px.")
        self.atualizar_painel_inicial()

    def diminuir_raio(self) -> None:
        self.raio_atual_px = max(3, self.raio_atual_px - 1)
        self.view.atualizar_label_raio(self.raio_atual_px)

        if self.leds_selecionados:
            for led_selecionado in self.leds_selecionados:
                led_selecionado.raio = self.raio_atual_px
            self.resultados_led_atual = []
            self.view.preparar_imagem_para_exibicao(self.imagem_original)
            self.view.desenhar_canvas(self.leds_selecionados, self.resultados_led_atual)
            self.atualizar_renderizacoes_visuais(self.leds_selecionados)
            self.view.atualizar_faixa_resultado()

        self.view.atualizar_status(f"raio ajustado para {self.raio_atual_px}px.")
        self.atualizar_painel_inicial()

    def limpar_tela(self) -> None:
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
