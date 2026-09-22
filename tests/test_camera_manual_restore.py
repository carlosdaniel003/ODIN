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


class DirectShowAdvancedCaptureFake:
    """Simula propriedades avançadas com passos e retornos DirectShow imperfeitos."""

    MANUAL_PROPS = {
        cv2.CAP_PROP_PAN: 0.0,
        cv2.CAP_PROP_TILT: 0.0,
        cv2.CAP_PROP_CONTRAST: 100.0,
        cv2.CAP_PROP_SHARPNESS: 100.0,
        cv2.CAP_PROP_SATURATION: 100.0,
        cv2.CAP_PROP_EXPOSURE: -6.0,
        cv2.CAP_PROP_GAIN: 20.0,
        cv2.CAP_PROP_FOCUS: 100.0,
        cv2.CAP_PROP_WB_TEMPERATURE: 4500.0,
        cv2.CAP_PROP_BRIGHTNESS: 120.0,
        cv2.CAP_PROP_GAMMA: 100.0,
    }

    AUTO_PROPS = {
        cv2.CAP_PROP_AUTO_EXPOSURE: 0.75,
        cv2.CAP_PROP_AUTOFOCUS: 1.0,
        cv2.CAP_PROP_AUTO_WB: 1.0,
    }

    STEPS = {
        cv2.CAP_PROP_FOCUS: 5,
        cv2.CAP_PROP_WB_TEMPERATURE: 100,
        cv2.CAP_PROP_GAIN: 5,
        cv2.CAP_PROP_BRIGHTNESS: 5,
        cv2.CAP_PROP_CONTRAST: 5,
        cv2.CAP_PROP_SHARPNESS: 5,
        cv2.CAP_PROP_SATURATION: 5,
        cv2.CAP_PROP_GAMMA: 5,
        cv2.CAP_PROP_PAN: 5,
        cv2.CAP_PROP_TILT: 5,
        cv2.CAP_PROP_EXPOSURE: 1,
    }

    def __init__(self):
        self.props = dict(self.MANUAL_PROPS)
        self.props.update(self.AUTO_PROPS)
        self.sets = []

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def set(self, prop, value):
        value = float(value)
        self.sets.append((prop, value))

        if prop in self.AUTO_PROPS:
            # Simula backend que aplica, mas devolve False.
            self.props[prop] = value
            return False

        if prop not in self.MANUAL_PROPS:
            return False

        if prop == cv2.CAP_PROP_FOCUS and self.props[cv2.CAP_PROP_AUTOFOCUS] != 0.0:
            return False
        if prop == cv2.CAP_PROP_EXPOSURE and self.props[cv2.CAP_PROP_AUTO_EXPOSURE] not in (0.0, 0.25, 1.0):
            return False
        if prop == cv2.CAP_PROP_WB_TEMPERATURE and self.props[cv2.CAP_PROP_AUTO_WB] != 0.0:
            return False

        step = int(self.STEPS[prop])
        if int(round(value)) % step != 0:
            return False

        # Também retorna False mesmo aplicando, para exercitar confirmação por get().
        self.props[prop] = value
        return False


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
        self.assertEqual(
            "ajustado_driver",
            service._status_controles_camera["focus"]["status"],
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

    def test_todos_controles_avancados_habilitam_sem_escrita_de_probe(self):
        service = ServiceFake()
        service._capture = DirectShowAdvancedCaptureFake()

        for nome in service._PROPRIEDADES_MANUAIS:
            service._capture.sets.clear()
            service._aplicar_habilitacao_manual(
                service._capture,
                nome,
                True,
            )
            self.assertEqual(
                "manual_pronto",
                service._status_controles_camera[nome]["status"],
                nome,
            )
            propriedade = service._propriedade_manual(nome)
            writes = [
                item for item in service._capture.sets
                if item[0] == propriedade
            ]
            self.assertEqual([], writes, nome)

    def test_todos_controles_avancados_confirmam_por_readback_e_passo(self):
        service = ServiceFake()
        service._capture = DirectShowAdvancedCaptureFake()

        # Desliga automáticos antes dos três controles acoplados.
        for chave in ("focus_auto", "exposure_auto", "white_balance_auto"):
            service._aplicar_automatico(service._capture, chave, False)

        solicitados = {
            "pan": 7.0,
            "tilt": 7.0,
            "contrast": 137.0,
            "sharpness": 137.0,
            "saturation": 137.0,
            "exposure": -5.0,
            "gain": 37.0,
            "focus": 137.0,
            "white_balance": 4370.0,
            "brightness": 137.0,
            "gamma": 137.0,
        }

        for nome, valor in solicitados.items():
            service._configuracoes_camera = {
                f"{nome}_enabled": True,
                nome: valor,
            }
            service._aplicar_valor_manual(
                service._capture,
                nome,
                service._configuracoes_camera,
            )
            self.assertIn(
                service._status_controles_camera[nome]["status"],
                {"aplicado", "ajustado_driver"},
                nome,
            )

        self.assertEqual(135.0, service._capture.props[cv2.CAP_PROP_FOCUS])
        self.assertEqual(35.0, service._capture.props[cv2.CAP_PROP_GAIN])
        self.assertEqual(4400.0, service._capture.props[cv2.CAP_PROP_WB_TEMPERATURE])

    def test_automaticos_nao_sao_falsamente_marcados_sem_suporte_quando_set_retorna_false(self):
        service = ServiceFake()
        service._capture = DirectShowAdvancedCaptureFake()

        cases = (
            ("focus_auto", "autofocus"),
            ("exposure_auto", "auto_exposure"),
            ("white_balance_auto", "auto_white_balance"),
        )
        for chave, status_key in cases:
            service._aplicar_automatico(service._capture, chave, True)
            self.assertEqual(
                "aplicado",
                service._status_controles_camera[status_key]["status"],
                chave,
            )
            service._aplicar_automatico(service._capture, chave, False)
            self.assertEqual(
                "aplicado",
                service._status_controles_camera[status_key]["status"],
                chave,
            )

    def test_valor_recusado_nao_bloqueia_controle_como_nao_suportado(self):
        service = ServiceFake()
        service._capture = DirectShowAdvancedCaptureFake()
        service._capture.set = lambda prop, value: False
        service._configuracoes_camera = {
            "gain_enabled": True,
            "gain": 199.0,
        }
        service._aplicar_valor_manual(
            service._capture,
            "gain",
            service._configuracoes_camera,
        )
        self.assertEqual(
            "ignorado_driver",
            service._status_controles_camera["gain"]["status"],
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
