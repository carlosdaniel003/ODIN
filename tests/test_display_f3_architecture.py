from __future__ import annotations

import inspect
import unittest

import numpy as np

from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.desktop_production_app import DesktopProductionApp
from src.ui.desktop_operation_window import DesktopOperationWindow


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls = []
        self.cancel_calls = []
        self.idle_calls = []
        self.focus_calls = 0
        self._next_id = 0

    def after(self, delay, callback):
        self._next_id += 1
        ident = f"after-{self._next_id}"
        self.after_calls.append((ident, int(delay), callback))
        return ident

    def after_cancel(self, ident):
        self.cancel_calls.append(ident)

    def after_idle(self, callback):
        self.idle_calls.append(callback)
        return "idle-1"

    def focus_force(self):
        self.focus_calls += 1


class _FakeView:
    def __init__(self) -> None:
        self.status = []

    def atualizar_status(self, texto):
        self.status.append(str(texto))


class _FakeF2Window:
    def __init__(self) -> None:
        self.visible = False


class _FakeF3Window:
    def __init__(self) -> None:
        self.visible = False
        self.waiting_calls = 0
        self.frames = []
        self.freeze_calls = 0
        self.release_calls = 0
        self.waiting_new_plate_calls = 0
        self.result_calls = []
        self.sequence_calls = []
        self._display_ng_evidence_frozen = False

    def show_waiting_camera(self):
        self.waiting_calls += 1

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def update_camera_preview(self, frame):
        if self._display_ng_evidence_frozen:
            return True
        self.frames.append(frame)
        return True

    def freeze_ng_evidence(self):
        self.freeze_calls += 1
        self._display_ng_evidence_frozen = True

    def release_ng_evidence(self):
        self.release_calls += 1
        self._display_ng_evidence_frozen = False

    def show_waiting_new_plate(self, snapshot=None):
        self.waiting_new_plate_calls += 1
        self.sequence_calls.append(dict(snapshot or {}))

    def show_plate_result(self, is_ok, snapshot, discarded=False):
        self.result_calls.append((bool(is_ok), bool(discarded), dict(snapshot or {})))

    def set_check_sequence(self, snapshot):
        self.sequence_calls.append(dict(snapshot or {}))


class _FakeEngine:
    def __init__(self) -> None:
        self.marker = object()


class _FakeBase:
    def __init__(self) -> None:
        self.root = _FakeRoot()
        self.view = _FakeView()
        self.camera_ativa = True
        self.camera_frame_atual = np.zeros((480, 640, 3), dtype=np.uint8)
        self.camera_service = object()
        self.camera_start_calls = 0
        self.camera_stop_calls = 0

        # Sentinelas do F2: o F3 não pode usar nem modificar estes campos.
        self.operacao_ativa = False
        self.operacao_total = 37
        self.operacao_ok = 31
        self.operacao_ng = 6
        self.operacao_engine = _FakeEngine()
        self.operacao_window = _FakeF2Window()
        self.f2_open_calls = 0
        self.f2_prepare_calls = 0
        self.f2_trigger_calls = 0
        self.f2_close_calls = 0

    def iniciar_tela_ao_vivo(self):
        self.camera_start_calls += 1
        self.camera_ativa = True

    def parar_tela_ao_vivo(self, *_args, **_kwargs):
        self.camera_stop_calls += 1
        self.camera_ativa = False

    def abrir_tela_operacao(self):
        self.f2_open_calls += 1

    def preparar_tela_operacao(self):
        self.f2_prepare_calls += 1

    def disparar_inspecao_operacao(self):
        self.f2_trigger_calls += 1

    def fechar_tela_operacao(self):
        self.f2_close_calls += 1


class _FakeApp(DisplayProductionF3Mixin, _FakeBase):
    def _instalar_modo_display_f3(self) -> None:
        self.display_f3_window = _FakeF3Window()


class _FakeAppComSeletor(_FakeApp):
    def __init__(self) -> None:
        self.selector_calls = 0
        self.selector_callback = None
        super().__init__()

    def abrir_seletor_camera(self, ao_selecionar=None):
        self.selector_calls += 1
        self.selector_callback = ao_selecionar


class DisplayF3ArchitectureTests(unittest.TestCase):
    def _snapshot_f2(self, app: _FakeApp):
        return (
            app.operacao_ativa,
            app.operacao_total,
            app.operacao_ok,
            app.operacao_ng,
            app.operacao_engine,
            app.operacao_window,
            app.f2_open_calls,
            app.f2_prepare_calls,
            app.f2_trigger_calls,
            app.f2_close_calls,
        )

    def test_f3_nao_sobrescreve_metodos_operacionais_do_f2_camera_ou_enter(self):
        proibidos = {
            "_instalar_tela_operacao",
            "abrir_tela_operacao",
            "preparar_tela_operacao",
            "disparar_inspecao_operacao",
            "fechar_tela_operacao",
            "analisar_led_selecionado",
            "iniciar_tela_ao_vivo",
            "parar_tela_ao_vivo",
            "atualizar_frame_camera",
            "_evento_enter_pressionado",
            "_evento_enter_liberado",
        }
        self.assertTrue(proibidos.isdisjoint(DisplayProductionF3Mixin.__dict__))

    def test_modulo_f3_nao_importa_engine_runtime_ou_trigger_f2(self):
        fonte = inspect.getsource(__import__(
            "src.platform.display_production_f3",
            fromlist=["DisplayProductionF3Mixin"],
        ))
        self.assertNotIn("operation_engine", fonte)
        self.assertNotIn("SegmentDisplayRuntimeMixin", fonte)
        self.assertNotIn("RaspberryEnterTriggerMixin", fonte)
        self.assertNotIn("SegmentDisplayOperationWindow", fonte)

    def test_janela_f3_reutiliza_somente_renderer_base_da_camera(self):
        self.assertTrue(issubclass(DisplayProductionF3Window, DesktopOperationWindow))
        fonte = inspect.getsource(DisplayProductionF3Window.update_camera_preview)
        self.assertIn("self.update_preview(visual_frame, leds=())", fonte)
        self.assertIn("preparar_frame_visual_display", fonte)
        self.assertNotIn("operacao_engine", fonte)
        self.assertNotIn("camera_service", fonte)

    def test_enter_e_f2_sao_consumidos_localmente_na_tela_f3(self):
        fonte = inspect.getsource(DisplayProductionF3Window.__init__)
        self.assertIn('self.container.bind("<Return>", self._ignorar_trigger)', fonte)
        self.assertIn('self.container.bind("<KP_Enter>", self._ignorar_trigger)', fonte)
        self.assertIn('self.container.bind("<F2>", self._ignorar_trigger)', fonte)
        self.assertEqual("break", DisplayProductionF3Window._ignorar_trigger())

    def test_f3_recusa_abrir_enquanto_f2_esta_ativo_sem_tocar_no_f2(self):
        app = _FakeApp()
        app.operacao_ativa = True
        antes = self._snapshot_f2(app)
        service = app.camera_service

        self.assertFalse(app.abrir_tela_producao_display_f3())

        self.assertEqual(antes, self._snapshot_f2(app))
        self.assertIs(service, app.camera_service)
        self.assertEqual(0, app.camera_start_calls)
        self.assertEqual(0, app.camera_stop_calls)
        self.assertFalse(app.display_f3_ativo)
        self.assertTrue(app.view.status)

    def test_f3_recusa_abrir_se_janela_f2_estiver_visivel(self):
        app = _FakeApp()
        app.operacao_window.visible = True
        antes = self._snapshot_f2(app)

        self.assertFalse(app.abrir_tela_producao_display_f3())

        self.assertEqual(antes, self._snapshot_f2(app))
        self.assertEqual(0, app.camera_start_calls)
        self.assertEqual(0, app.camera_stop_calls)

    def test_abrir_f3_com_camera_ativa_preserva_camera_e_estado_f2(self):
        app = _FakeApp()
        antes = self._snapshot_f2(app)
        service = app.camera_service
        frame = app.camera_frame_atual

        self.assertTrue(app.abrir_tela_producao_display_f3())

        self.assertTrue(app.display_f3_ativo)
        self.assertTrue(app.display_f3_window.visible)
        self.assertEqual(1, app.display_f3_window.waiting_calls)
        self.assertIs(service, app.camera_service)
        self.assertIs(frame, app.camera_frame_atual)
        self.assertEqual(0, app.camera_start_calls)
        self.assertEqual(0, app.camera_stop_calls)
        self.assertEqual(antes, self._snapshot_f2(app))
        self.assertEqual(1, len(app.root.after_calls))
        self.assertEqual(0, app.root.after_calls[0][1])

    def test_f3_sem_seletor_pede_camera_existente_uma_vez(self):
        app = _FakeApp()
        app.camera_ativa = False
        antes = self._snapshot_f2(app)

        self.assertTrue(app.abrir_tela_producao_display_f3())

        self.assertEqual(1, app.camera_start_calls)
        self.assertEqual(0, app.camera_stop_calls)
        self.assertTrue(app.display_f3_ativo)
        self.assertEqual(antes, self._snapshot_f2(app))

    def test_f3_reutiliza_seletor_existente_e_so_abre_depois_da_escolha(self):
        app = _FakeAppComSeletor()
        app.camera_ativa = False
        antes = self._snapshot_f2(app)

        self.assertTrue(app.abrir_tela_producao_display_f3())

        self.assertEqual(1, app.selector_calls)
        self.assertIsNotNone(app.selector_callback)
        self.assertEqual(0, app.camera_start_calls)
        self.assertFalse(app.display_f3_ativo)
        self.assertFalse(app.display_f3_window.visible)
        self.assertEqual(0, len(app.root.after_calls))
        self.assertEqual(antes, self._snapshot_f2(app))

        app.selector_callback(1)

        self.assertEqual(1, app.camera_start_calls)
        self.assertTrue(app.display_f3_ativo)
        self.assertTrue(app.display_f3_window.visible)
        self.assertEqual(1, len(app.root.after_calls))
        self.assertEqual(antes, self._snapshot_f2(app))

    def test_callback_da_camera_nao_abre_f3_se_f2_foi_ativado_no_intervalo(self):
        app = _FakeAppComSeletor()
        app.camera_ativa = False
        self.assertTrue(app.abrir_tela_producao_display_f3())
        self.assertIsNotNone(app.selector_callback)

        app.operacao_ativa = True
        app.selector_callback(1)

        self.assertEqual(0, app.camera_start_calls)
        self.assertFalse(app.display_f3_ativo)
        self.assertFalse(app.display_f3_window.visible)

    def test_preview_f3_le_exatamente_camera_frame_atual_sem_alterar_f2(self):
        app = _FakeApp()
        app.display_f3_ativo = True
        frame = app.camera_frame_atual
        copia = frame.copy()
        antes = self._snapshot_f2(app)

        app._atualizar_preview_display_f3()

        self.assertEqual(1, len(app.display_f3_window.frames))
        self.assertIs(frame, app.display_f3_window.frames[0])
        np.testing.assert_array_equal(copia, frame)
        self.assertEqual(antes, self._snapshot_f2(app))
        self.assertEqual(0, app.camera_start_calls)
        self.assertEqual(0, app.camera_stop_calls)

    def test_ng_congela_tambem_status_e_check_que_falhou(self):
        source = inspect.getsource(DisplayProductionF3Window.freeze_ng_evidence)
        sequence_source = inspect.getsource(DisplayProductionF3Window.set_check_sequence)
        preview_source = inspect.getsource(DisplayProductionF3Window.set_preview_status)

        self.assertIn("_capture_analysis_statuses", source)
        self.assertIn("_display_frozen_check_snapshot", source)
        self.assertIn("restore_frozen_analysis_statuses", source)
        self.assertIn("_display_frozen_check_snapshot", sequence_source)
        self.assertIn("_display_ng_evidence_frozen", preview_source)

    def test_ng_anexa_estado_visual_da_janela_a_evidencia(self):
        source = inspect.getsource(
            DisplayProductionF3Mixin._congelar_evidencia_ng_display_f3
        )
        self.assertIn("snapshot_debug_visual_state", source)
        self.assertIn('["visual_state"]', source)

    def test_ng_preserva_copia_bruta_para_debug_ate_retirada_da_placa(self):
        source_freeze = inspect.getsource(
            DisplayProductionF3Mixin._congelar_evidencia_ng_display_f3
        )
        source_release = inspect.getsource(
            DisplayProductionF3Mixin._liberar_evidencia_ng_display_f3
        )

        self.assertIn("_display_f3_ng_evidence_frame", source_freeze)
        self.assertIn('"frame_id": pending_frame_id', source_freeze)
        self.assertIn('"rotation": evidence_rotation', source_freeze)
        self.assertIn('"sequence":', source_freeze)
        self.assertIn("_display_f3_ng_evidence_frame = None", source_release)

    def test_ng_congela_frame_fecha_ciclo_e_nao_contabiliza_duas_vezes(self):
        app = _FakeApp()
        app.display_f3_ativo = True
        app.display_check_runtime.configurar_checks(
            [
                {"id": "CHECK_H1", "name": "H1"},
                {"id": "CHECK_BLUE", "name": "BLUE", "intermittent": True},
            ]
        )
        app.display_check_runtime.registrar_resultado_check(True)
        app._display_auto_last_analysis = {
            "ready": True,
            "project_name": "DISPLAY_TESTE",
            "check_id": "CHECK_BLUE",
            "mask_results": [
                {
                    "mask_id": "MASK_027",
                    "expected": "on",
                    "classified": "off",
                    "matched": False,
                }
            ],
        }

        event = app.registrar_resultado_check_display_f3(False)

        self.assertEqual("plate_ng", event["event"])
        self.assertTrue(app._display_f3_ng_evidence_frozen)
        self.assertEqual(1, app.display_check_runtime.total)
        self.assertEqual(1, app.display_check_runtime.ng)
        self.assertEqual(1, app.display_f3_window.freeze_calls)
        self.assertEqual(1, len(app.display_f3_window.frames))

        # O loop continua existindo, mas não substitui a imagem congelada.
        app._atualizar_preview_display_f3()
        self.assertEqual(1, len(app.display_f3_window.frames))

        # A tecla/botão DESCARTAR não pode contar a mesma placa novamente.
        self.assertIsNone(app.descartar_placa_display_f3())
        self.assertEqual(1, app.display_check_runtime.total)
        self.assertEqual(1, app.display_check_runtime.ng)

    def test_evidencia_ng_so_volta_ao_vivo_quando_rearme_a_libera(self):
        app = _FakeApp()
        app.display_f3_ativo = True
        app.display_check_runtime.configurar_checks(
            [{"id": "CHECK_H1", "name": "H1"}]
        )
        app._display_auto_last_analysis = {
            "ready": True,
            "project_name": "DISPLAY_TESTE",
            "check_id": "CHECK_H1",
            "mask_results": [],
        }
        app.registrar_resultado_check_display_f3(False)
        frozen_frames = len(app.display_f3_window.frames)

        app._liberar_evidencia_ng_display_f3()

        self.assertFalse(app._display_f3_ng_evidence_frozen)
        self.assertEqual(1, app.display_f3_window.release_calls)
        self.assertEqual(1, app.display_f3_window.waiting_new_plate_calls)

        app._atualizar_preview_display_f3()
        self.assertEqual(frozen_frames + 1, len(app.display_f3_window.frames))

    def test_fechar_f3_cancela_somente_timer_f3_e_nao_para_camera(self):
        app = _FakeApp()
        app.display_f3_ativo = True
        app.display_f3_window.visible = True
        app.display_f3_after_id = "f3-after"
        antes = self._snapshot_f2(app)
        service = app.camera_service

        app.fechar_tela_producao_display_f3()

        self.assertFalse(app.display_f3_ativo)
        self.assertFalse(app.display_f3_window.visible)
        self.assertEqual(["f3-after"], app.root.cancel_calls)
        self.assertIsNone(app.display_f3_after_id)
        self.assertIs(service, app.camera_service)
        self.assertTrue(app.camera_ativa)
        self.assertEqual(0, app.camera_stop_calls)
        self.assertEqual(antes, self._snapshot_f2(app))

    def test_integracao_preserva_instalacao_f2_e_adiciona_f3_por_mixin(self):
        self.assertTrue(issubclass(DesktopProductionApp, DisplayProductionF3Mixin))
        fonte_f2 = inspect.getsource(DesktopProductionApp._instalar_tela_operacao)
        self.assertIn("SegmentDisplayOperationWindow", fonte_f2)
        self.assertIn('"<F2>"', fonte_f2)
        self.assertIn('text="PRODUÇÃO  F2"', fonte_f2)
        self.assertIn("command=self.abrir_tela_operacao", fonte_f2)
        self.assertNotIn("display_f3", fonte_f2.lower())

    def test_responsabilidades_da_fase_1_nao_incluem_analise(self):
        self.assertEqual(
            (
                "janela_f3",
                "atalho_f3",
                "preview_camera_somente_leitura",
                "ciclo_abertura_fechamento_f3",
            ),
            DisplayProductionF3Mixin.responsabilidades_f3(),
        )


if __name__ == "__main__":
    unittest.main()
