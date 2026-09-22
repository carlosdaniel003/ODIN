import threading
import unittest
from types import SimpleNamespace

import cv2

from src.platform.camera_live_settings import CameraLiveSettingsMixin
from src.platform.camera_live_control_service import CameraLiveControlServiceMixin
from src.platform.live_fixed_full_hd_camera_service import LiveFixedFullHdCameraService
from src.platform.verified_live_camera_service import VerifiedCameraControlMixin


class _ServicePerfilFake:
    indice_camera = 1
    _backend_name = "Media Foundation"

    def obter_snapshot(self):
        return SimpleNamespace(
            resolucao=(640, 480),
            fps_real=30.0,
            formato_real="MJPG",
        )

    def obter_diagnostico_fluxo(self):
        return {
            "backend_ativo": "Media Foundation",
            "fps_medido": 29.8,
            "backend_formato": "MJPG",
        }


class _CaptureRecusaFoco:
    def get(self, prop):
        if prop == cv2.CAP_PROP_FOCUS:
            return 120.0
        return 0.0

    def set(self, prop, value):
        if prop == cv2.CAP_PROP_FOCUS:
            return False
        return True


class _BaseFake:
    def __init__(self):
        self._lock = threading.RLock()
        self._capture = _CaptureRecusaFoco()
        self._configuracoes_camera = {}
        self._controles_pendentes = False
        self._status_controles_camera = {}

    def _registrar_status_controle(self, nome, status, valor_solicitado=None, valor_lido=None):
        self._status_controles_camera[nome] = {
            "status": status,
            "valor_solicitado": valor_solicitado,
            "valor_lido": valor_lido,
        }


class _ServicoVerificadoFake(
    VerifiedCameraControlMixin,
    CameraLiveControlServiceMixin,
    _BaseFake,
):
    pass


class CameraRuntimeProfileAndSupportTests(unittest.TestCase):
    def test_perfil_da_interface_reflete_stream_real(self):
        perfil = CameraLiveSettingsMixin._obter_perfil_camera_real(
            _ServicePerfilFake()
        )
        self.assertEqual((640, 480), perfil["resolucao"])
        self.assertEqual(30.0, perfil["fps"])
        self.assertEqual("MJPG", perfil["formato"])
        self.assertEqual("Media Foundation", perfil["backend"])
        self.assertEqual(1, perfil["indice"])

    def test_servico_final_tem_controle_pontual_ao_vivo(self):
        self.assertTrue(
            issubclass(
                LiveFixedFullHdCameraService,
                CameraLiveControlServiceMixin,
            )
        )
        self.assertTrue(
            hasattr(
                LiveFixedFullHdCameraService,
                "atualizar_configuracoes_camera_ao_vivo",
            )
        )
        self.assertIs(
            LiveFixedFullHdCameraService._aplicar_habilitacao_manual,
            VerifiedCameraControlMixin._aplicar_habilitacao_manual,
        )
        self.assertIs(
            LiveFixedFullHdCameraService._aplicar_valor_manual,
            VerifiedCameraControlMixin._aplicar_valor_manual,
        )

    def test_todos_controles_visiveis_possuem_propriedade_opencv_mapeada(self):
        service = _ServicoVerificadoFake()
        for nome, atributo in service._PROPRIEDADES_MANUAIS.items():
            self.assertTrue(hasattr(cv2, atributo), nome)
            self.assertIsNotNone(service._propriedade_manual(nome), nome)

        for chave, (_manual, _status, atributo) in service._CONTROLES_AUTOMATICOS.items():
            self.assertTrue(hasattr(cv2, atributo), chave)

    def test_tentativa_recusada_nao_e_equivalente_a_sem_suporte(self):
        fonte = __import__(
            "inspect"
        ).getsource(VerifiedCameraControlMixin._aplicar_valor_manual)
        self.assertIn('"ignorado_driver"', fonte)
        self.assertIn("bloqueado", fonte)
        self.assertNotIn(
            '"O driver recusou o novo valor."',
            fonte,
        )

    def test_habilitar_manual_nao_bloqueia_por_reescrita_do_baseline(self):
        service = _ServicoVerificadoFake()
        service._aplicar_habilitacao_manual(
            service._capture,
            "focus",
            True,
        )
        status = service._status_controles_camera["focus"]
        self.assertEqual("manual_pronto", status["status"])
        self.assertFalse(status["bloqueado"])


if __name__ == "__main__":
    unittest.main()
