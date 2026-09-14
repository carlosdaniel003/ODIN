from pathlib import Path
import unittest


class DisplayF3WorkspaceWithoutLegacyRoiTests(unittest.TestCase):
    def test_workspace_nao_importa_seletor_retangular_removido(self):
        source = Path("src/platform/display_f3_workspace_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("DisplayReferenceRoiDialog", source)
        self.assertNotIn(
            "from src.platform.display_reference_roi import DisplayReferenceRoiDialog",
            source,
        )

    def test_modulo_workspace_pode_ser_importado_sem_roi_legado(self):
        import src.platform.display_f3_workspace_ui as workspace

        self.assertTrue(hasattr(workspace, "instalar_workspace_telas_display_f3"))
        self.assertTrue(callable(workspace.instalar_workspace_telas_display_f3))


if __name__ == "__main__":
    unittest.main()
