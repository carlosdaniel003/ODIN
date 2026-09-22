import inspect
import unittest

from src.platform.camera_advanced_config import normalizar_controles_avancados
from src.platform.camera_live_settings import CameraLiveSettingsMixin
from src.platform.raspberry_pi3_production_app import RaspberryPi3ProductionApp
from src.platform.reference_project_sets import ProjectReferenceSetsMixin
from src.ui.main_window_parts.settings.abrir_janela_configuracoes_ao_vivo import (
    LIVE_CAMERA_DEBOUNCE_MS,
    construir_configuracoes_camera_ao_vivo,
)


class _VarFake:
    def __init__(self, valor):
        self.valor = valor

    def get(self):
        return self.valor


class _RepositoryFake:
    def normalizar_configuracoes_camera(self, configuracoes):
        return dict(configuracoes or {})


class _CameraServiceFake:
    ESTADO_CONECTADA = "conectada"

    def __init__(self):
        self.atualizacoes = []
        self.paradas = 0
        self.inicios = 0

    def atualizar_configuracoes_camera_ao_vivo(self, configuracoes, chaves):
        self.atualizacoes.append((dict(configuracoes), list(chaves)))

    def obter_status_controles_camera(self):
        return {"focus": {"status": "aplicado", "valor_lido": 137.0}}

    def parar(self):
        self.paradas += 1

    def iniciar(self):
        self.inicios += 1


class CameraLiveSettingsTests(unittest.TestCase):
    def test_perfil_final_inclui_mixin_camera_ao_vivo(self):
        self.assertIn(CameraLiveSettingsMixin, RaspberryPi3ProductionApp.__mro__)

    def test_configuracoes_camera_cooperam_com_referencias_multiplas(self):
        mro = RaspberryPi3ProductionApp.__mro__
        self.assertIn(ProjectReferenceSetsMixin, mro)
        self.assertLess(
            mro.index(CameraLiveSettingsMixin),
            mro.index(ProjectReferenceSetsMixin),
        )
        fonte = inspect.getsource(CameraLiveSettingsMixin.abrir_configuracoes)
        self.assertIn("super().abrir_configuracoes()", fonte)
        self.assertIn("abrir_janela_configuracoes", fonte)

    def test_tela_camera_completa_serializa_todos_os_ajustes(self):
        base = {}
        variaveis = {
            "_resolution_label": _VarFake("Personalizada"),
            "_width": _VarFake(2560),
            "_height": _VarFake(1440),
            "_fps_label": _VarFake("30"),
            "_format_label": _VarFake("MJPG"),
            "_rotation_label": _VarFake("180°"),
            "pan_enabled": _VarFake(True),
            "pan": _VarFake(10),
            "tilt_enabled": _VarFake(True),
            "tilt": _VarFake(-10),
            "contrast_enabled": _VarFake(True),
            "contrast": _VarFake(137),
            "sharpness_enabled": _VarFake(True),
            "sharpness": _VarFake(138),
            "saturation_enabled": _VarFake(True),
            "saturation": _VarFake(139),
            "exposure_auto": _VarFake(False),
            "exposure_enabled": _VarFake(True),
            "exposure": _VarFake(-5),
            "gain_enabled": _VarFake(True),
            "gain": _VarFake(35),
            "focus_auto": _VarFake(False),
            "focus_enabled": _VarFake(True),
            "focus": _VarFake(135),
            "white_balance_auto": _VarFake(False),
            "white_balance_enabled": _VarFake(True),
            "white_balance": _VarFake(4400),
            "brightness_enabled": _VarFake(True),
            "brightness": _VarFake(140),
            "gamma_enabled": _VarFake(True),
            "gamma": _VarFake(105),
        }

        configuracoes = construir_configuracoes_camera_ao_vivo(
            base,
            variaveis,
        )

        esperado = {
            "resolution_mode": "custom",
            "width": 2560,
            "height": 1440,
            "fps_mode": "manual",
            "fps": 30,
            "format": "MJPG",
            "rotation": 180,
            "pan_enabled": True,
            "pan": 10.0,
            "tilt_enabled": True,
            "tilt": -10.0,
            "contrast_enabled": True,
            "contrast": 137.0,
            "sharpness_enabled": True,
            "sharpness": 138.0,
            "saturation_enabled": True,
            "saturation": 139.0,
            "exposure_auto": False,
            "exposure_enabled": True,
            "exposure": -5.0,
            "gain_enabled": True,
            "gain": 35.0,
            "focus_auto": False,
            "focus_enabled": True,
            "focus": 135.0,
            "white_balance_auto": False,
            "white_balance_enabled": True,
            "white_balance": 4400.0,
            "brightness_enabled": True,
            "brightness": 140.0,
            "gamma_enabled": True,
            "gamma": 105.0,
        }
        for chave, valor in esperado.items():
            self.assertEqual(valor, configuracoes[chave], chave)

    def test_normalizacao_avancada_preserva_auto_manual_e_limites(self):
        resultado = normalizar_controles_avancados(
            {},
            {
                "exposure_auto": False,
                "exposure_enabled": True,
                "exposure": -5,
                "gain_enabled": True,
                "gain": 9999,
                "focus_auto": False,
                "focus_enabled": True,
                "focus": 135,
                "white_balance_auto": False,
                "white_balance_enabled": True,
                "white_balance": 4400,
                "brightness_enabled": True,
                "brightness": -100,
                "gamma_enabled": True,
                "gamma": 105,
            },
        )

        self.assertFalse(resultado["exposure_auto"])
        self.assertTrue(resultado["exposure_enabled"])
        self.assertEqual(-5.0, resultado["exposure"])
        self.assertTrue(resultado["gain_enabled"])
        self.assertLessEqual(resultado["gain"], 255.0)
        self.assertFalse(resultado["focus_auto"])
        self.assertEqual(135.0, resultado["focus"])
        self.assertFalse(resultado["white_balance_auto"])
        self.assertEqual(4400.0, resultado["white_balance"])
        self.assertGreaterEqual(resultado["brightness"], 0.0)
        self.assertEqual(105.0, resultado["gamma"])

    def test_foco_manual_e_montado_imediatamente(self):
        base = {"focus_auto": True, "focus_enabled": False, "focus": 0.0}
        variaveis = {
            "focus_auto": _VarFake(False),
            "focus_enabled": _VarFake(True),
            "focus": _VarFake(137),
        }
        configuracoes = construir_configuracoes_camera_ao_vivo(base, variaveis)
        self.assertFalse(configuracoes["focus_auto"])
        self.assertTrue(configuracoes["focus_enabled"])
        self.assertEqual(137.0, configuracoes["focus"])

    def test_aplicacao_ao_vivo_envia_so_chaves_alteradas_sem_reiniciar(self):
        app = object.__new__(CameraLiveSettingsMixin)
        app.config_repository = _RepositoryFake()
        app.camera_service = _CameraServiceFake()
        app.camera_ativa = True
        app.configuracoes_camera = {
            "focus_auto": True,
            "focus_enabled": False,
            "focus": 0.0,
        }
        app._camera_live_ultima_config = dict(app.configuracoes_camera)

        aplicado = app.aplicar_configuracoes_camera_ao_vivo(
            {"focus_auto": False, "focus_enabled": True, "focus": 137.0}
        )

        self.assertTrue(aplicado)
        self.assertEqual(1, len(app.camera_service.atualizacoes))
        configuracoes, chaves = app.camera_service.atualizacoes[0]
        self.assertEqual(137.0, configuracoes["focus"])
        self.assertEqual(
            {"focus_auto", "focus_enabled", "focus"},
            set(chaves),
        )
        self.assertEqual(0, app.camera_service.paradas)
        self.assertEqual(0, app.camera_service.inicios)

    def test_cancelar_restaura_por_envio_pontual_sem_reconectar(self):
        app = object.__new__(CameraLiveSettingsMixin)
        app.config_repository = _RepositoryFake()
        app.camera_service = _CameraServiceFake()
        app.camera_ativa = True
        app.configuracoes_camera = {
            "gain_enabled": False,
            "gain": 42.0,
        }
        app._camera_live_ultima_config = {
            "gain_enabled": True,
            "gain": 90.0,
        }

        aplicado = app.restaurar_configuracoes_camera_ao_vivo(
            app.configuracoes_camera
        )
        self.assertTrue(aplicado)
        _configuracoes, chaves = app.camera_service.atualizacoes[0]
        self.assertEqual({"gain_enabled", "gain"}, set(chaves))
        self.assertEqual(0, app.camera_service.paradas)
        self.assertEqual(0, app.camera_service.inicios)

    def test_slider_mantem_debounce_curto(self):
        self.assertGreaterEqual(LIVE_CAMERA_DEBOUNCE_MS, 20)
        self.assertLessEqual(LIVE_CAMERA_DEBOUNCE_MS, 100)

    def test_mixin_nao_persiste_nem_reinicia_durante_preview(self):
        fonte = inspect.getsource(CameraLiveSettingsMixin)
        self.assertNotIn("parar_tela_ao_vivo", fonte)
        self.assertNotIn("iniciar_tela_ao_vivo", fonte)
        self.assertNotIn("salvar_configuracoes_sistema(", fonte)
        self.assertIn("atualizar_configuracoes_camera_ao_vivo", fonte)


if __name__ == "__main__":
    unittest.main()
