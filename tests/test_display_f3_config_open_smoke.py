from __future__ import annotations

import tempfile
import tkinter as tk
import traceback
import unittest
from pathlib import Path

from src.platform.display_f3_heavy_executor import F3HeavyVisionExecutor
from src.platform.display_f3_tracking_orientation_ui import (
    instalar_ui_rastreamento_objetos_display_f3,
)
from src.platform.display_project_repository import DisplayProjectRepository
from src.platform.display_visual_reference_status import instalar_status_referencias_visuais_display
from src.platform.display_reference_roi import instalar_roi_referencias_display_f3
from src.platform.display_f3_fast_expected_gate import instalar_gate_rapido_check_esperado_display_f3
import src.platform.display_production_f3 as production_module


class DisplayF3ConfigOpenSmokeTests(unittest.TestCase):
    def test_final_config_window_opens_with_real_tk(self):
        root = tk.Tk()
        root.withdraw()
        created = None
        executor = None
        try:
            instalar_status_referencias_visuais_display()
            instalar_roi_referencias_display_f3()
            instalar_gate_rapido_check_esperado_display_f3()
            # Produção real instala esta camada depois da composição base.
            # O smoke precisa abrir exatamente a classe final usada pelo botão
            # CONFIGURAR, inclusive com o executor pesado compartilhado.
            instalar_ui_rastreamento_objetos_display_f3()

            with tempfile.TemporaryDirectory() as directory:
                repository = DisplayProjectRepository(Path(directory) / "display.json")
                repository.adicionar_projeto("CM_500_L", (1920, 1080))
                repository.definir_projeto_ativo("CM_500_L")
                executor = F3HeavyVisionExecutor()
                try:
                    created = production_module.DisplayProjectConfigWindow(
                        root=root,
                        repository=repository,
                        frame_provider=lambda: None,
                        heavy_executor=executor,
                        on_change=lambda: None,
                        on_close=lambda: None,
                    )
                    root.update_idletasks()
                    root.update()
                except Exception:
                    traceback.print_exc()
                    raise

                self.assertTrue(created.visible)
                self.assertIs(created.repository, repository)
        finally:
            if created is not None:
                try:
                    created.close()
                except Exception:
                    pass
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_pending=True)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
