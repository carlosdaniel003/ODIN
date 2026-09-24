from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from linux_local_config_bootstrap import preparar_configuracao_local_linux


if sys.platform.startswith("linux"):
    preparar_configuracao_local_linux(Path(__file__).resolve().parent)


from src.platform.raspberry_pi3_production_app import (  # noqa: E402
    RaspberryPi3ProductionApp,
)
from src.platform.f2_board_presence_mask_preview_native import (  # noqa: E402
    instalar_renderer_nativo_mascaras_previews_presenca_f2,
)
from src.platform.f2_board_shape_editor import (  # noqa: E402
    instalar_editor_contorno_placa_f2,
)
from src.platform.f2_board_shape_confirm_fix import (  # noqa: E402
    instalar_correcao_confirmacao_contorno_placa_f2,
)
from src.platform.f2_board_shape_state_isolation import (  # noqa: E402
    instalar_isolamento_estado_contorno_placa_f2,
)
from src.platform.f2_board_shape_editor_main_canvas_isolation import (  # noqa: E402
    instalar_isolamento_imagem_principal_editor_placa_f2,
)
from src.platform.f2_board_shape_precision_magnifier import (  # noqa: E402
    instalar_lupa_precisao_contorno_placa_f2,
)
from src.platform.f2_board_shape_runtime_authority import (  # noqa: E402
    instalar_autoridade_final_editor_contorno_f2,
)
from src.platform.f2_object_tracking_visual_overlay import (  # noqa: E402
    instalar_overlay_visual_rastreamento_f2,
)
from src.platform.f2_object_tracking_runtime_fix import (  # noqa: E402
    instalar_correcao_runtime_rastreamento_f2,
)
from src.platform.f2_object_tracking_multiview import (  # noqa: E402
    instalar_banco_multivista_rastreamento_f2,
)
from src.platform.f2_object_tracking_cardinal_rotation_fix import (  # noqa: E402
    instalar_correcao_rotacao_cardinal_rastreamento_f2,
)
from src.platform.f2_object_tracking_real_orientations import (  # noqa: E402
    instalar_banco_referencias_reais_orientacao_f2,
)
from src.platform.f2_tracking_orientation_references import (  # noqa: E402
    instalar_ui_referencias_reais_orientacao_f2,
)
from src.platform.f2_tracking_orientation_vertex_editor import (  # noqa: E402
    instalar_editor_vertices_referencias_orientacao_f2,
)
from src.platform.f2_tracking_orientation_vertex_transform_fix import (  # noqa: E402
    instalar_transformacao_base_editor_vertices_orientacao_f2,
)
from src.platform.f2_tracking_orientation_precision_roi_editor import (  # noqa: E402
    instalar_precisao_rois_referencias_orientacao_f2,
)
from src.platform.f2_tracking_orientation_precision_interaction_fix import (  # noqa: E402
    instalar_ajustes_interacao_precisao_orientacao_f2,
)
from src.platform.f2_tracking_orientation_editor_workflow import (  # noqa: E402
    instalar_fluxo_interacao_editor_orientacao_f2,
)
from src.platform.f2_tracking_orientation_live_capture import (  # noqa: E402
    instalar_captura_guiada_referencias_orientacao_f2,
)
from src.platform.f2_tracking_presence_status_bridge import (  # noqa: E402
    instalar_presenca_por_referencias_angulares_f2,
)
from src.platform.f2_object_tracking_hold_reacquire import (  # noqa: E402
    instalar_reaquisicao_durante_hold_f2,
)
from src.platform.f2_tracking_analysis_rois import (  # noqa: E402
    instalar_analise_em_rois_rastreadas_f2,
)
from src.platform.f2_tracking_hold_analysis_guard import (  # noqa: E402
    instalar_guarda_analise_pose_fresca_f2,
)
from src.platform.f2_result_layout_centering import (  # noqa: E402
    instalar_layout_resultado_f2_centralizado,
)
from src.platform.display_reference_roi_runtime_fix import (  # noqa: E402
    instalar_correcao_referencias_mascaras_f3,
)
from src.platform.display_f3_mask_confidence_fix import (  # noqa: E402
    instalar_correcao_confianca_mascaras_display_f3,
)
from src.platform.display_f3_check_reference_zoom import (  # noqa: E402
    instalar_zoom_foto_check_display_f3,
)
from src.platform.display_f3_visual_best_match_fix import (  # noqa: E402
    instalar_melhor_correspondencia_visual_display_f3,
)
from src.platform.display_f3_preview_clarity_fix import (  # noqa: E402
    instalar_preview_claro_display_f3,
)
from src.platform.display_f3_reference_preview_rotation import (  # noqa: E402
    instalar_rotacao_preview_referencias_display_f3,
)
from src.platform.display_f3_mask_visibility_ui import (  # noqa: E402
    instalar_guias_mascaras_inicio_display_f3,
    instalar_numeros_editor_mascaras_display_f3,
)
from src.platform.display_f3_power_authority import (  # noqa: E402
    instalar_autoridade_energia_final_display_f3,
)
from src.platform.display_f3_power_authority_v2 import (  # noqa: E402
    instalar_autoridade_energia_unificada_display_f3,
)
from src.platform.display_f3_power_debug_compat_v2 import (  # noqa: E402
    instalar_compatibilidade_energia_unificada_debug_f3,
)
from src.platform.display_f3_power_evidence_compat import (  # noqa: E402
    instalar_evidencia_energia_mesma_mascara_display_f3,
)
from src.platform.display_f3_power_visual_coherence import (  # noqa: E402
    instalar_coerencia_visual_energia_display_f3,
)
from src.platform.display_f3_presence_relative_empty_fix import (  # noqa: E402
    instalar_presenca_relativa_suporte_vazio_display_f3,
)
from src.platform.display_f3_presence_stability_fix import (  # noqa: E402
    instalar_estabilidade_presenca_placa_display_f3,
)
from src.platform.display_f3_rearm_live_refresh_fix import (  # noqa: E402
    instalar_correcao_rearme_status_live_display_f3,
)
from src.platform.display_f3_live_status_consistency_fix import (  # noqa: E402
    instalar_consistencia_status_live_display_f3,
)
from src.platform.display_f3_object_tracking import (  # noqa: E402
    instalar_autoridade_final_instancia_rastreamento_f3,
    instalar_runtime_rastreamento_objetos_display_f3,
)
from src.platform.display_f3_physical_transition_authority import (  # noqa: E402
    instalar_autoridade_transicao_fisica_checks_f3,
)
from src.platform.display_f3_tracking_orientation_ui import (  # noqa: E402
    instalar_ui_rastreamento_objetos_display_f3,
)


instalar_editor_contorno_placa_f2()
instalar_correcao_confirmacao_contorno_placa_f2()
instalar_isolamento_estado_contorno_placa_f2()
instalar_isolamento_imagem_principal_editor_placa_f2()
instalar_lupa_precisao_contorno_placa_f2()
instalar_overlay_visual_rastreamento_f2()
instalar_correcao_runtime_rastreamento_f2()
instalar_banco_multivista_rastreamento_f2()
instalar_correcao_rotacao_cardinal_rastreamento_f2()
instalar_banco_referencias_reais_orientacao_f2()
instalar_editor_vertices_referencias_orientacao_f2()
instalar_transformacao_base_editor_vertices_orientacao_f2()
instalar_precisao_rois_referencias_orientacao_f2()
instalar_ajustes_interacao_precisao_orientacao_f2()
instalar_fluxo_interacao_editor_orientacao_f2()
instalar_captura_guiada_referencias_orientacao_f2()
instalar_presenca_por_referencias_angulares_f2()
instalar_reaquisicao_durante_hold_f2()
instalar_analise_em_rois_rastreadas_f2()
instalar_guarda_analise_pose_fresca_f2()
instalar_layout_resultado_f2_centralizado()
instalar_correcao_referencias_mascaras_f3()
instalar_correcao_confianca_mascaras_display_f3()
instalar_zoom_foto_check_display_f3()
instalar_melhor_correspondencia_visual_display_f3()
instalar_preview_claro_display_f3()
instalar_guias_mascaras_inicio_display_f3()
instalar_numeros_editor_mascaras_display_f3()


def main() -> None:
    root = tk.Tk()
    app = RaspberryPi3ProductionApp(root)
    # Renderer F2 instalado somente depois que a aplicação inteira terminou de
    # inicializar. Ele substitui diretamente o render_settings do controller de
    # presença: ligada/desligada recebem as ROIs dos LEDs e o contorno compartilhado
    # da placa, sem timers e sem alterar os arquivos de referência.
    instalar_renderer_nativo_mascaras_previews_presenca_f2()
    # Depois do renderer final, acrescenta três slots opcionais 90/180/270 com
    # imagens reais e calibração do mesmo contorno canônico do projeto.
    instalar_ui_referencias_reais_orientacao_f2()
    # Autoridade do editor F2 realmente por último: no Linux garante SALVAR,
    # persistência não-vazia e status do contorno acima dos cards de presença.
    instalar_autoridade_final_editor_contorno_f2()
    # Alguns instaladores históricos do F3 são executados durante __init__ e
    # podem substituir renderizadores/globals. Reafirmamos somente as autoridades
    # finais depois que toda a composição terminou, sem criar timers ou leituras
    # extras de câmera.
    instalar_preview_claro_display_f3()
    # Autoridade final das miniaturas de configuração: aplica rotação visual,
    # máscaras locais e contorno da placa depois que os reparos históricos de
    # referência já substituíram store/UI durante a construção do app.
    instalar_rotacao_preview_referencias_display_f3()
    instalar_guias_mascaras_inicio_display_f3()
    instalar_evidencia_energia_mesma_mascara_display_f3()
    instalar_autoridade_energia_final_display_f3()
    # Autoridade de energia independente do CHECK lógico: usa o frame RAW e os
    # pares ON/OFF reais da mesma máscara aprendidos nas fotos dos CHECKS. Assim
    # USB/BLUE/AUX continuam provando que o display está ligado mesmo se a
    # sequência lógica ainda estiver aguardando H1.
    instalar_autoridade_energia_unificada_display_f3()
    # Consumidores históricos do DEBUG/guards recebem a mesma semântica de energia
    # e deixam de publicar uma segunda verdade baseada somente em brilho.
    instalar_compatibilidade_energia_unificada_debug_f3()
    # Última camada de apresentação: sem energia confirmada não existe defeito de
    # segmento. A preview fica somente com guias neutras e a ANÁLISE VISUAL mostra
    # PLACA DESLIGADA/ENERGIA NÃO CONFIRMADA, preservando o match global só no debug.
    instalar_coerencia_visual_energia_display_f3()
    # Autoridade de ausência: se EMPTY vencer todas as cenas com placa por uma
    # separação relativa forte, mostramos PLACA FORA DO SUPORTE.
    instalar_presenca_relativa_suporte_vazio_display_f3()
    # Autoridade final de presença: ambiguidade entre H1/BLUE/USB/AUX/OFF não pode
    # ser confundida com ausência da placa. Usa a melhor cena ocupada contra EMPTY
    # e segura poucos frames ambíguos para evitar piscar o status no startup.
    instalar_estabilidade_presenca_placa_display_f3()
    # Fecha o handoff terminal: o detector de rearme reutiliza a mesma autoridade
    # relativa de EMPTY e as duas linhas de status continuam atualizando enquanto
    # o pipeline produtivo está bloqueado após OK/NG/SEGREGAR.
    instalar_correcao_rearme_status_live_display_f3()
    # Refresh visual literalmente mais externo. Se um gate retornar antes do
    # pipeline histórico de status, a UI reaproveita o estado/energia já calculados
    # no mesmo frame e não permanece em placeholders antigos.
    instalar_consistencia_status_live_display_f3()
    # Rastreamento do Display F3 é instalado literalmente por último. Ele possui
    # flag, armazenamento, referências angulares, editor e tracker próprios.
    # Desligado, delega integralmente para o F3 atual; o F2 não é consultado nem
    # modificado por estas duas camadas.
    instalar_runtime_rastreamento_objetos_display_f3()
    instalar_ui_rastreamento_objetos_display_f3()
    # Autoridade final aplicada diretamente à instância real. Isso impede que
    # wrappers históricos da MRO escondam a bounding box móvel ou avancem CHECKS
    # por caminhos alternativos da máquina de sequência.
    instalar_autoridade_final_instancia_rastreamento_f3(app)
    # Última autoridade produtiva: energia confirma somente que o display está
    # ligado. Para avançar BLUE/USB/AUX (e CHECKS futuros), o frame precisa provar
    # fisicamente a transição do CHECK anterior para o atual.
    instalar_autoridade_transicao_fisica_checks_f3(app)
    root.mainloop()


if __name__ == "__main__":
    main()