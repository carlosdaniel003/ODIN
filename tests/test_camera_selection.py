import inspect
import unittest

import cv2

from src.platform.camera_selection import (
    CAMERA_SELECTOR_RELEASE_GRACE_MS,
    CameraSelectionMixin,
    _configurar_capture_preview,
    camera_backends_preferidos,
    criar_classe_camera_indice_estrito,
)
from src.platform.desktop_production_app import DesktopProductionApp


class _Candidato:
    def __init__(self, indice):
        self.indice = indice


class _CameraBaseFake:
    def __init__(self, indice_camera=0):
        self.indice_camera = int(indice_camera)
        self._indice_camera_solicitado = int(indice_camera)

    def _indices_candidatos(self):
        return (1, 0, 2, 3)

    def _candidatos_linux(self):
        return tuple(_Candidato(indice) for indice in (0, 1, 2, 3))


class _CaptureFake:
    def __init__(self):
        self.definicoes = []

    def set(self, propriedade, valor):
        self.definicoes.append((propriedade, valor))
        return True


class CameraSelectionTests(unittest.TestCase):
    def test_perfil_final_inclui_seletor_camera(self):
        self.assertIn(CameraSelectionMixin, DesktopProductionApp.__mro__)

    def test_windows_prioriza_media_foundation_e_linux_v4l2(self):
        windows = camera_backends_preferidos("win32")
        linux = camera_backends_preferidos("linux")
        self.assertEqual("Media Foundation", windows[0][1])
        self.assertEqual(cv2.CAP_MSMF, windows[0][0])
        self.assertEqual("DirectShow", windows[1][1])
        self.assertEqual("V4L2", linux[0][1])

    def test_preview_windows_nao_forca_resolucao_fps_ou_fourcc(self):
        capture = _CaptureFake()
        _configurar_capture_preview(capture, plataforma="win32")
        propriedades = [item[0] for item in capture.definicoes]
        self.assertNotIn(cv2.CAP_PROP_FRAME_WIDTH, propriedades)
        self.assertNotIn(cv2.CAP_PROP_FRAME_HEIGHT, propriedades)
        self.assertNotIn(cv2.CAP_PROP_FPS, propriedades)
        self.assertNotIn(cv2.CAP_PROP_FOURCC, propriedades)

    def test_preview_linux_mantem_probe_leve_configurado(self):
        capture = _CaptureFake()
        _configurar_capture_preview(capture, plataforma="linux")
        propriedades = [item[0] for item in capture.definicoes]
        self.assertIn(cv2.CAP_PROP_FRAME_WIDTH, propriedades)
        self.assertIn(cv2.CAP_PROP_FRAME_HEIGHT, propriedades)
        self.assertIn(cv2.CAP_PROP_FPS, propriedades)
        self.assertIn(cv2.CAP_PROP_FOURCC, propriedades)

    def test_seletor_da_tempo_para_windows_liberar_handle_usb(self):
        self.assertGreaterEqual(CAMERA_SELECTOR_RELEASE_GRACE_MS, 250)
        fonte = inspect.getsource(
            CameraSelectionMixin._confirmar_camera_selecionada
        )
        self.assertIn("CAMERA_SELECTOR_RELEASE_GRACE_MS", fonte)

    def test_classe_estrita_mantem_apenas_indice_escolhido(self):
        classe = criar_classe_camera_indice_estrito(_CameraBaseFake)
        camera = classe(indice_camera=1)
        self.assertEqual((1,), camera._indices_candidatos())
        self.assertEqual(
            [1],
            [item.indice for item in camera._candidatos_linux()],
        )

    def test_classe_estrita_e_reutilizada_sem_empilhar_wrappers(self):
        primeira = criar_classe_camera_indice_estrito(_CameraBaseFake)
        segunda = criar_classe_camera_indice_estrito(primeira)
        self.assertIs(primeira, segunda)

    def test_botao_live_abre_seletor_antes_de_iniciar(self):
        fonte = inspect.getsource(CameraSelectionMixin.alternar_tela_ao_vivo)
        self.assertIn("abrir_seletor_camera", fonte)
        self.assertIn("iniciar_tela_ao_vivo", fonte)

    def test_producao_f2_tambem_abre_seletor_quando_camera_parada(self):
        fonte = inspect.getsource(CameraSelectionMixin.abrir_tela_operacao)
        self.assertIn("abrir_seletor_camera", fonte)
        self.assertIn("camera_ativa", fonte)

    def test_seletor_mantem_duas_previews_simultaneas(self):
        modulo = inspect.getmodule(CameraSelectionMixin)
        fonte = inspect.getsource(modulo)
        self.assertIn("CAMERA_SELECTOR_MAX_PREVIEWS = 2", fonte)
        self.assertIn("_atualizar_previews_seletor_camera", fonte)
        self.assertIn("Usar câmera", fonte)


if __name__ == "__main__":
    unittest.main()
