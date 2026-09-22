import threading
import unittest

import cv2

from src.platform.camera_live_control_service import CameraLiveControlServiceMixin


class CaptureFake:
    def __init__(self):
        self.props = {
            cv2.CAP_PROP_GAIN: 42.0,
            cv2.CAP_PROP_FOCUS: 130.0,
            cv2.CAP_PROP_AUTOFOCUS: 0.0,
        }
        self.sets = []

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def set(self, prop, value):
        value = float(value)
        self.sets.append((prop, value))
        self.props[prop] = value
        return True


class DirectShowFocusCaptureFake:
    def __init__(self):
        self.props = {
            cv2.CAP_PROP_FOCUS: 100.0,
            cv2.CAP_PROP_AUTOFOCUS: 1.0,
        }
        self.sets = []

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def set(self, prop, value):
        value = float(value)
        self.sets.append((prop, value))
        if prop == cv2.CAP_PROP_AUTOFOCUS:
            self.props[prop] = value
            return True
        if prop == cv2.CAP_PROP_FOCUS:
            if self.props.get(cv2.CAP_PROP_AUTOFOCUS, 1.0) != 0.0:
                return False
            if int(round(value)) % 5 != 0:
                return False
            self.props[prop] = value
            return True
        return False


class BaseFake:
    def __init__(self):
        self._lock = threading.RLock()
        self._capture = CaptureFake()
        self._configuracoes_camera = {}
        self._controles_pendentes = False
        self._status_controles_camera = {}
        self._backend_atual = "DirectShow"

    @classmethod
    def _normalizar_configuracoes_camera(cls, config):
        return dict(config or {})

    def obter_configuracoes_camera(self):
        return dict(self._configuracoes_camera)

    def _registrar_status_controle(self, nome, status, valor_solicitado=None, valor_lido=None):
        self._status_controles_camera[nome] = {
            "status": status,
            "valor_solicitado": valor_solicitado,
            "valor_lido": valor_lido,
        }

    @staticmethod
    def _valor_auto_exposure(automatico):
        return 0.75 if automatico else 0.25

    def _aplicar_configuracoes_hardware(self):
        self._controles_pendentes = False


class ServiceFake(CameraLiveControlServiceMixin, BaseFake):
    pass


class CameraManualRestoreTests(unittest.TestCase):
    def test_habilitar_ganho_nao_escreve_e_desabilitar_restaura(self):
        service = ServiceFake()
        service.atualizar_configuracoes_camera_ao_vivo(
            {"gain_enabled": True, "gain": 128.0},
            ["gain_enabled"],
        )
        service._aplicar_configuracoes_hardware()
        self.assertEqual([], service._capture.sets)
        self.assertEqual("manual_pronto", service._status_controles_camera["gain"]["status"])

        service.atualizar_configuracoes_camera_ao_vivo(
            {"gain_enabled": True, "gain": 77.0},
            ["gain"],
        )
        service._aplicar_configuracoes_hardware()
        self.assertEqual(77.0, service._capture.props[cv2.CAP_PROP_GAIN])

        service._capture.sets.clear()
        service.atualizar_configuracoes_camera_ao_vivo(
            {"gain_enabled": False, "gain": 77.0},
            ["gain_enabled"],
        )
        service._aplicar_configuracoes_hardware()
        self.assertEqual([(cv2.CAP_PROP_GAIN, 42.0)], service._capture.sets)

    def test_foco_directshow_desliga_auto_e_encaixa_no_passo_aceito(self):
        service = ServiceFake()
        service._capture = DirectShowFocusCaptureFake()
        service.atualizar_configuracoes_camera_ao_vivo(
            {
                "focus_auto": False,
                "focus_enabled": True,
                "focus": 137.0,
            },
            ["focus_auto", "focus_enabled", "focus"],
        )
        service._aplicar_configuracoes_hardware()

        self.assertEqual(0.0, service._capture.props[cv2.CAP_PROP_AUTOFOCUS])
        self.assertEqual(135.0, service._capture.props[cv2.CAP_PROP_FOCUS])
        self.assertIn(
            service._status_controles_camera["focus"]["status"],
            {"aplicado", "ajustado_driver"},
        )

    def test_habilitar_foco_directshow_nao_reescreve_baseline_para_validar(self):
        service = ServiceFake()
        service._capture = DirectShowFocusCaptureFake()
        service.atualizar_configuracoes_camera_ao_vivo(
            {
                "focus_auto": False,
                "focus_enabled": True,
                "focus": 100.0,
            },
            ["focus_auto", "focus_enabled"],
        )
        service._aplicar_configuracoes_hardware()

        focus_sets = [
            item
            for item in service._capture.sets
            if item[0] == cv2.CAP_PROP_FOCUS
        ]
        self.assertEqual([], focus_sets)
        self.assertEqual(
            "manual_pronto",
            service._status_controles_camera["focus"]["status"],
        )

    def test_autofocus_e_enviado_ao_driver(self):
        service = ServiceFake()
        service.atualizar_configuracoes_camera_ao_vivo(
            {"focus_auto": True, "focus_enabled": False, "focus": 130.0},
            ["focus_auto"],
        )
        service._aplicar_configuracoes_hardware()
        self.assertIn((cv2.CAP_PROP_AUTOFOCUS, 1.0), service._capture.sets)
        self.assertEqual("automatico", service._status_controles_camera["focus"]["status"])


if __name__ == "__main__":
    unittest.main()
