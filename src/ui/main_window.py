
from src.ui.main_window_parts.updates.atualizar_estado_tela_ao_vivo import atualizar_estado_tela_ao_vivo
from src.ui.main_window_parts.canvas.desenhar_guias_leds_camera import desenhar_guias_leds_camera
from src.ui.main_window_parts.lifecycle.init_view import __init__ as init_view
from src.ui.main_window_parts.lifecycle.maximizar_janela import maximizar_janela
from src.ui.main_window_parts.lifecycle.alternar_tela_cheia import alternar_tela_cheia
from src.ui.main_window_parts.lifecycle.sair_tela_cheia import sair_tela_cheia
from src.ui.main_window_parts.lifecycle.configurar_atalhos_tela import configurar_atalhos_tela
from src.ui.main_window_parts.lifecycle.obter_geometria_monitor_atual import obter_geometria_monitor_atual
from src.ui.main_window_parts.layout.criar_layout import criar_layout
from src.ui.main_window_parts.layout.criar_barra_metadados import criar_barra_metadados
from src.ui.main_window_parts.layout.criar_area_dashboard import criar_area_dashboard
from src.ui.main_window_parts.panels.criar_painel_principal import criar_painel_principal
from src.ui.main_window_parts.panels.criar_painel_central import criar_painel_central
from src.ui.main_window_parts.panels.criar_painel_direito import criar_painel_direito
from src.ui.main_window_parts.panels.criar_tabela_inferior import criar_tabela_inferior
from src.ui.main_window_parts.layout.criar_faixa_resultado import criar_faixa_resultado
from src.ui.main_window_parts.widgets.criar_botao_topo import criar_botao_topo
from src.ui.main_window_parts.widgets.criar_item_metadado import criar_item_metadado
from src.ui.main_window_parts.widgets.criar_card import criar_card
from src.ui.main_window_parts.widgets.criar_titulo_card import criar_titulo_card
from src.ui.main_window_parts.widgets.criar_kpi import criar_kpi
from src.ui.main_window_parts.widgets.configurar_estilo_tabela import configurar_estilo_tabela
from src.ui.main_window_parts.updates.atualizar_status import atualizar_status
from src.ui.main_window_parts.updates.atualizar_estado_selecao_led import atualizar_estado_selecao_led
from src.ui.main_window_parts.updates.escrever_resultados import escrever_resultados
from src.ui.main_window_parts.updates.atualizar_faixa_resultado import atualizar_faixa_resultado
from src.ui.main_window_parts.image.obter_tamanho_canvas_principal import obter_tamanho_canvas_principal
from src.ui.main_window_parts.image.atualizar_imagem_principal_redimensionada import atualizar_imagem_principal_redimensionada
from src.ui.main_window_parts.image.preparar_imagem_para_exibicao import preparar_imagem_para_exibicao
from src.ui.main_window_parts.image.converter_canvas_para_imagem_original import converter_canvas_para_imagem_original
from src.ui.main_window_parts.image.evento_redimensionar_canvas_principal import evento_redimensionar_canvas_principal
from src.ui.main_window_parts.image.redesenhar_imagem_principal_apos_redimensionamento import redesenhar_imagem_principal_apos_redimensionamento
from src.ui.main_window_parts.updates.atualizar_painel_resultado import atualizar_painel_resultado
from src.ui.main_window_parts.history.criar_observacao_resultado import criar_observacao_resultado
from src.ui.main_window_parts.history.desenhar_barra_confianca import desenhar_barra_confianca
from src.ui.main_window_parts.canvas.desenhar_placeholders_laterais import desenhar_placeholders_laterais
from src.ui.main_window_parts.updates.limpar_renderizacoes_visuais import limpar_renderizacoes_visuais
from src.ui.main_window_parts.updates.exibir_renderizacoes_visuais import exibir_renderizacoes_visuais
from src.ui.main_window_parts.image.exibir_imagem_em_canvas import exibir_imagem_em_canvas
from src.ui.main_window_parts.canvas.desenhar_placeholder import desenhar_placeholder
from src.ui.main_window_parts.state._normalizar_leds_selecionados import _normalizar_leds_selecionados
from src.ui.main_window_parts.state._normalizar_resultados_led import _normalizar_resultados_led
from src.ui.main_window_parts.layout.criar_topo_profissional import criar_topo_profissional
from src.ui.main_window_parts.settings.abrir_janela_configuracoes import abrir_janela_configuracoes
from src.ui.main_window_parts.widgets.criar_botao_config import criar_botao_config
from src.ui.main_window_parts.updates.atualizar_label_raio import atualizar_label_raio
from src.ui.main_window_parts.updates.atualizar_faixa_resultado_multiplos import atualizar_faixa_resultado_multiplos
from src.ui.main_window_parts.canvas.desenhar_canvas import desenhar_canvas
from src.ui.main_window_parts.canvas.desenhar_leds_selecionados import desenhar_leds_selecionados
from src.ui.main_window_parts.canvas.desenhar_led_selecionado import desenhar_led_selecionado
from src.ui.main_window_parts.canvas.desenhar_resultados_led import desenhar_resultados_led
from src.ui.main_window_parts.canvas.desenhar_resultado_led import desenhar_resultado_led
from src.ui.main_window_parts.updates.atualizar_painel_resultado_multiplos import atualizar_painel_resultado_multiplos
from src.ui.main_window_parts.updates.atualizar_resumo_selecoes import atualizar_resumo_selecoes
from src.ui.main_window_parts.updates.atualizar_resumo_selecao import atualizar_resumo_selecao
from src.ui.main_window_parts.updates.atualizar_resumo_sem_analise import atualizar_resumo_sem_analise
from src.ui.main_window_parts.history.adicionar_resultado_historico import adicionar_resultado_historico
from src.ui.main_window_parts.history.obter_data_hora import obter_data_hora
from src.ui.main_window_parts.lifecycle.init_view import __init__ as init_view
from src.ui.main_window_parts.clock.iniciar_relogio_sistema import iniciar_relogio_sistema
from src.ui.main_window_parts.clock.atualizar_relogio_sistema import atualizar_relogio_sistema
from src.ui.main_window_parts.clock.atualizar_estado_relogio import atualizar_estado_relogio
from src.ui.main_window_parts.clock.alternar_visibilidade_relogio import alternar_visibilidade_relogio
from src.ui.main_window_parts.brand.carregar_logo_sistema import carregar_logo_sistema
from src.ui.main_window_parts.magnifier.atualizar_lupa_canvas import atualizar_lupa_canvas
from src.ui.main_window_parts.magnifier.desenhar_lupa_canvas import desenhar_lupa_canvas
from src.ui.main_window_parts.magnifier.limpar_lupa_canvas import limpar_lupa_canvas

class ODINView:
    """
    Interface principal do ODIN.

    Responsabilidade deste arquivo:
    - manter a classe pública ODINView;
    - centralizar as constantes visuais;
    - vincular métodos modularizados em src/ui/main_window_parts/;
    - não executar regra de classificação de LED.
    """

    COR_FUNDO_APP = "#030712"
    COR_TOPO = "#050B14"
    COR_CARD = "#07111F"
    COR_CARD_2 = "#0B1626"
    COR_BORDA = "#122033"
    COR_TEXTO = "#F9FAFB"
    COR_TEXTO_2 = "#CBD5E1"
    COR_TEXTO_3 = "#94A3B8"
    COR_VERDE = "#16A34A"
    COR_VERDE_CLARO = "#22C55E"
    COR_VERMELHO = "#DC2626"
    COR_VERMELHO_CLARO = "#EF4444"
    COR_AZUL = "#38BDF8"
    COR_AMARELO = "#FBBF24"
    COR_NEUTRO = "#374151"

    __init__ = init_view
    criar_layout = criar_layout
    criar_barra_metadados = criar_barra_metadados
    criar_area_dashboard = criar_area_dashboard
    criar_painel_principal = criar_painel_principal
    criar_painel_central = criar_painel_central
    criar_painel_direito = criar_painel_direito
    criar_tabela_inferior = criar_tabela_inferior
    criar_faixa_resultado = criar_faixa_resultado
    criar_botao_topo = criar_botao_topo
    criar_item_metadado = criar_item_metadado
    criar_card = criar_card
    criar_titulo_card = criar_titulo_card
    criar_kpi = criar_kpi
    configurar_estilo_tabela = configurar_estilo_tabela
    atualizar_status = atualizar_status
    atualizar_estado_selecao_led = atualizar_estado_selecao_led
    atualizar_estado_tela_ao_vivo = atualizar_estado_tela_ao_vivo
    desenhar_guias_leds_camera = desenhar_guias_leds_camera
    escrever_resultados = escrever_resultados
    atualizar_faixa_resultado = atualizar_faixa_resultado
    obter_tamanho_canvas_principal = obter_tamanho_canvas_principal
    atualizar_imagem_principal_redimensionada = atualizar_imagem_principal_redimensionada
    preparar_imagem_para_exibicao = preparar_imagem_para_exibicao
    converter_canvas_para_imagem_original = converter_canvas_para_imagem_original
    evento_redimensionar_canvas_principal = evento_redimensionar_canvas_principal
    redesenhar_imagem_principal_apos_redimensionamento = redesenhar_imagem_principal_apos_redimensionamento
    atualizar_painel_resultado = atualizar_painel_resultado
    criar_observacao_resultado = criar_observacao_resultado
    desenhar_barra_confianca = desenhar_barra_confianca
    desenhar_placeholders_laterais = desenhar_placeholders_laterais
    limpar_renderizacoes_visuais = limpar_renderizacoes_visuais
    exibir_renderizacoes_visuais = exibir_renderizacoes_visuais
    exibir_imagem_em_canvas = exibir_imagem_em_canvas
    desenhar_placeholder = desenhar_placeholder
    _normalizar_leds_selecionados = _normalizar_leds_selecionados
    _normalizar_resultados_led = _normalizar_resultados_led
    criar_topo_profissional = criar_topo_profissional
    abrir_janela_configuracoes = abrir_janela_configuracoes
    criar_botao_config = criar_botao_config
    atualizar_label_raio = atualizar_label_raio
    atualizar_faixa_resultado_multiplos = atualizar_faixa_resultado_multiplos
    desenhar_canvas = desenhar_canvas
    desenhar_leds_selecionados = desenhar_leds_selecionados
    desenhar_led_selecionado = desenhar_led_selecionado
    desenhar_resultados_led = desenhar_resultados_led
    desenhar_resultado_led = desenhar_resultado_led
    atualizar_painel_resultado_multiplos = atualizar_painel_resultado_multiplos
    atualizar_resumo_selecoes = atualizar_resumo_selecoes
    atualizar_resumo_selecao = atualizar_resumo_selecao
    atualizar_resumo_sem_analise = atualizar_resumo_sem_analise
    adicionar_resultado_historico = adicionar_resultado_historico
    obter_data_hora = obter_data_hora
    maximizar_janela = maximizar_janela
    alternar_tela_cheia = alternar_tela_cheia
    sair_tela_cheia = sair_tela_cheia
    configurar_atalhos_tela = configurar_atalhos_tela
    obter_geometria_monitor_atual = obter_geometria_monitor_atual
    iniciar_relogio_sistema = iniciar_relogio_sistema
    atualizar_relogio_sistema = atualizar_relogio_sistema
    atualizar_estado_relogio = atualizar_estado_relogio
    alternar_visibilidade_relogio = alternar_visibilidade_relogio
    carregar_logo_sistema = carregar_logo_sistema
    atualizar_lupa_canvas = atualizar_lupa_canvas
    desenhar_lupa_canvas = desenhar_lupa_canvas
    limpar_lupa_canvas = limpar_lupa_canvas