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


instalar_correcao_referencias_mascaras_f3()
instalar_correcao_confianca_mascaras_display_f3()
instalar_zoom_foto_check_display_f3()
instalar_melhor_correspondencia_visual_display_f3()
instalar_preview_claro_display_f3()
instalar_guias_mascaras_inicio_display_f3()
instalar_numeros_editor_mascaras_display_f3()


def main() -> None:
    root = tk.Tk()
    RaspberryPi3ProductionApp(root)
    # Alguns instaladores históricos do F3 são executados durante __init__ e
    # podem substituir renderizadores/globals. Reafirmamos somente as autoridades
    # finais depois que toda a composição terminou, sem criar timers ou leituras
    # extras de câmera.
    instalar_preview_claro_display_f3()
    instalar_guias_mascaras_inicio_display_f3()
    instalar_evidencia_energia_mesma_mascara_display_f3()
    instalar_autoridade_energia_final_display_f3()
    # Autoridade literal mais externa do F3: a análise bruta do CHECK atual prova
    # energia; OFF↔ON em BGR/S/V/pixels é somente proteção secundária. Isso também
    # fecha o DEBUG por CHECK com proveniência explícita da foto usada.
    instalar_autoridade_energia_unificada_display_f3()
    # Consumidores históricos do DEBUG/guards recebem a mesma semântica de energia
    # e deixam de publicar uma segunda verdade baseada somente em brilho.
    instalar_compatibilidade_energia_unificada_debug_f3()
    root.mainloop()


if __name__ == "__main__":
    main()
