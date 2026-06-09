import tkinter as tk


def __init__(self, root: tk.Tk, callbacks: dict, raio_atual_px: int) -> None:
    self.root = root
    self.callbacks = callbacks
    self.raio_atual_px = raio_atual_px

    self.imagem_tk = None
    self.imagem_exibicao = None
    self.imagens_auxiliares_tk = {}
    self.imagem_canvas_original = None
    self.ultimo_led_selecionado = None
    self.ultimo_resultado_led_atual = None
    self.escala_exibicao = 1.0
    self.deslocamento_imagem_x = 0
    self.deslocamento_imagem_y = 0
    self.largura_imagem_exibida = 0
    self.altura_imagem_exibida = 0
    self.resolucao_atual = "--"
    self._ultimo_resultado_historico = None
    self._redimensionamento_pendente = None
    self.selecao_led_ativa = False
    self.botao_selecionar_leds = None
    self.tela_cheia_ativa = False
    self.relogio_visivel = True
    self.botao_toggle_relogio = None
    self._atualizacao_relogio_pendente = None
    self.logo_tk = None

    self.root.title("LumusPCI - Estação de Inspeção Visual de LED")
    self.root.geometry("1600x900")
    self.root.minsize(1280, 760)
    self.root.configure(bg=self.COR_FUNDO_APP)

    self.configurar_atalhos_tela()
    self.configurar_estilo_tabela()
    self.criar_layout()
    self.iniciar_relogio_sistema()

    self.root.after(120, self.maximizar_janela)