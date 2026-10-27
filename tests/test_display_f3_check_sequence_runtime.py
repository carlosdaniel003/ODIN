from __future__ import annotations

import inspect
import unittest
from unittest.mock import Mock

from src.platform.display_check_sequence_runtime import DisplayCheckSequenceRuntime
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_result_feedback import obter_feedback_espera_display_f3


CHECKS = [
    {"id": "CHECK_001", "name": "H1"},
    {"id": "CHECK_002", "name": "BLUE"},
    {"id": "CHECK_003", "name": "AUX"},
    {"id": "CHECK_004", "name": "USB"},
]


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls = []
        self.cancel_calls = []
        self._next = 0

    def after(self, delay, callback):
        self._next += 1
        ident = f"after-{self._next}"
        self.after_calls.append((ident, int(delay), callback))
        return ident

    def after_cancel(self, ident):
        self.cancel_calls.append(ident)


class _FakeWindow:
    def __init__(self) -> None:
        self.results = []
        self.snapshots = []

    def show_plate_result(self, is_ok, snapshot, discarded=False):
        self.results.append((bool(is_ok), bool(discarded), dict(snapshot)))

    def set_check_sequence(self, snapshot):
        self.snapshots.append(dict(snapshot))


class DisplayF3CheckSequenceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = DisplayCheckSequenceRuntime()
        self.runtime.configurar_checks(CHECKS)

    def test_runtime_preserva_flag_intermitente_no_snapshot(self):
        runtime = DisplayCheckSequenceRuntime()
        runtime.configurar_checks(
            [
                {"id": "CHECK_001", "name": "H1", "intermittent": False},
                {"id": "CHECK_002", "name": "BLUE", "intermittent": True},
            ]
        )
        self.assertFalse(runtime.snapshot()["current_check"]["intermittent"])
        runtime.registrar_resultado_check(True)
        self.assertTrue(runtime.snapshot()["current_check"]["intermittent"])

    def test_check_intermediario_desativado_e_pulado_sem_ng(self):
        checks = [dict(item) for item in CHECKS]
        checks[1]["enabled"] = False
        self.assertTrue(self.runtime.configurar_checks(checks))
        snapshot = self.runtime.snapshot()
        self.assertEqual(
            ["H1", "AUX", "USB"],
            [row["name"] for row in snapshot["checks"]],
        )
        advanced = self.runtime.registrar_resultado_check(True)
        self.assertEqual(
            DisplayCheckSequenceRuntime.EVENT_ADVANCED,
            advanced["event"],
        )
        self.assertEqual("AUX", advanced["snapshot"]["current_check"]["name"])
        self.runtime.registrar_resultado_check(True)
        result = self.runtime.registrar_resultado_check(True)
        self.assertEqual(DisplayCheckSequenceRuntime.EVENT_PLATE_OK, result["event"])
        self.assertEqual(("CHECK_001", "CHECK_003", "CHECK_004"), result["completed_ids"])
        self.assertEqual((1, 1, 0), (
            self.runtime.total, self.runtime.ok, self.runtime.ng
        ))

    def test_primeiro_ou_ultimo_inativo_muda_referencia_e_terminal(self):
        checks = [
            {"id": "CHECK_001", "name": "H1", "enabled": False},
            {"id": "CHECK_002", "name": "BLUE", "enabled": True},
            {"id": "CHECK_003", "name": "AUX", "enabled": False},
            {"id": "CHECK_004", "name": "USB", "enabled": False},
        ]
        self.runtime.configurar_checks(checks)
        snapshot = self.runtime.snapshot()
        self.assertEqual(["BLUE"], [item["name"] for item in snapshot["checks"]])
        self.assertEqual("BLUE", snapshot["current_check"]["name"])
        result = self.runtime.registrar_resultado_check(True)
        self.assertEqual(DisplayCheckSequenceRuntime.EVENT_PLATE_OK, result["event"])
        self.assertEqual(("CHECK_002",), result["completed_ids"])

    def test_todos_desativados_ou_sem_checks_nao_geram_resultado(self):
        self.runtime.configurar_checks([
            {**check, "enabled": False} for check in CHECKS
        ])
        snapshot = self.runtime.snapshot()
        self.assertEqual([], snapshot["checks"])
        self.assertIsNone(snapshot["current_check"])
        self.assertEqual(
            DisplayCheckSequenceRuntime.EVENT_NO_CHECKS,
            self.runtime.registrar_resultado_check(True)["event"],
        )
        self.assertEqual(
            DisplayCheckSequenceRuntime.EVENT_NO_CHECKS,
            self.runtime.registrar_resultado_check(False)["event"],
        )
        self.assertEqual((0, 0, 0), (
            self.runtime.total, self.runtime.ok, self.runtime.ng
        ))

    def test_reativacao_restabelece_ordem_sem_zerar_contadores_sessao(self):
        self.runtime.configurar_checks([
            {**item, "enabled": item["name"] != "BLUE"}
            for item in CHECKS
        ])
        for _ in range(3):
            self.runtime.registrar_resultado_check(True)
        self.assertEqual((1, 1, 0), (
            self.runtime.total, self.runtime.ok, self.runtime.ng
        ))
        self.assertTrue(self.runtime.configurar_checks(CHECKS))
        snapshot = self.runtime.snapshot()
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertEqual(4, len(snapshot["checks"]))
        self.assertEqual((1, 1, 0), (snapshot["total"], snapshot["ok"], snapshot["ng"]))

    def test_inicia_aguardando_primeiro_check(self):
        snapshot = self.runtime.snapshot()
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertEqual(0, snapshot["current_index"])
        self.assertEqual(
            ["current", "pending", "pending", "pending"],
            [item["state"] for item in snapshot["checks"]],
        )
        self.assertEqual((0, 0, 0), (snapshot["total"], snapshot["ok"], snapshot["ng"]))

    def test_avanca_h1_blue_aux_usb_e_aprova_placa(self):
        esperado = ["BLUE", "AUX", "USB"]
        for nome in esperado:
            evento = self.runtime.registrar_resultado_check(True)
            self.assertEqual(DisplayCheckSequenceRuntime.EVENT_ADVANCED, evento["event"])
            self.assertEqual(nome, evento["snapshot"]["current_check"]["name"])

        evento = self.runtime.registrar_resultado_check(True)
        self.assertEqual(DisplayCheckSequenceRuntime.EVENT_PLATE_OK, evento["event"])
        snapshot = evento["snapshot"]
        self.assertEqual((1, 1, 0), (snapshot["total"], snapshot["ok"], snapshot["ng"]))
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertEqual(0, snapshot["current_index"])
        self.assertEqual(4, len(evento["completed_ids"]))

    def test_descartar_no_meio_soma_ng_e_reinicia_primeiro_check(self):
        self.runtime.registrar_resultado_check(True)
        self.runtime.registrar_resultado_check(True)
        self.assertEqual("AUX", self.runtime.snapshot()["current_check"]["name"])

        evento = self.runtime.descartar_placa()

        self.assertEqual(DisplayCheckSequenceRuntime.EVENT_PLATE_DISCARDED, evento["event"])
        snapshot = evento["snapshot"]
        self.assertEqual((1, 0, 1), (snapshot["total"], snapshot["ok"], snapshot["ng"]))
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertEqual((), snapshot["completed_ids"])
        self.assertIsNone(snapshot["last_result"])
        self.assertIsNone(obter_feedback_espera_display_f3(snapshot))

    def test_check_reprovado_contabiliza_ng_e_reinicia(self):
        self.runtime.registrar_resultado_check(True)
        evento = self.runtime.registrar_resultado_check(False)
        self.assertEqual(DisplayCheckSequenceRuntime.EVENT_PLATE_NG, evento["event"])
        self.assertEqual("BLUE", evento["failed_check"]["name"])
        snapshot = evento["snapshot"]
        self.assertEqual((1, 0, 1), (snapshot["total"], snapshot["ok"], snapshot["ng"]))
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertEqual("NG", snapshot["last_result"])
        self.assertEqual(
            ("NG", "Última placa: NG • aguardando H1 da próxima placa"),
            obter_feedback_espera_display_f3(snapshot),
        )

    def test_contadores_de_sessao_sao_preservados_ao_reconfigurar_checks(self):
        for _ in range(4):
            self.runtime.registrar_resultado_check(True)
        self.runtime.configurar_checks(
            [
                {"id": "CHECK_001", "name": "START"},
                {"id": "CHECK_002", "name": "FINAL"},
            ]
        )
        snapshot = self.runtime.snapshot()
        self.assertEqual((1, 1, 0), (snapshot["total"], snapshot["ok"], snapshot["ng"]))
        self.assertEqual("START", snapshot["current_check"]["name"])

    def test_resumo_producao_invalida_cache_contorno_apos_toggle(self):
        source = inspect.getsource(
            DisplayProductionF3Mixin._atualizar_resumo_projeto_display_f3
        )
        self.assertIn(
            "self._display_f3_contour_identity_reference_cache = None",
            source,
        )

    def test_nenhum_check_ativo_tem_aviso_de_configuracao(self):
        from src.platform import display_f3_status_layout_fix
        source = inspect.getsource(
            display_f3_status_layout_fix._render_check_cards_f3_fixed
        )
        self.assertIn("Nenhum CHECK ativo no F3", source)

    def test_runtime_puro_nao_importa_f2_camera_ou_tkinter(self):
        modulo = __import__(
            "src.platform.display_check_sequence_runtime",
            fromlist=["DisplayCheckSequenceRuntime"],
        )
        fonte = inspect.getsource(modulo)
        self.assertNotIn("tkinter", fonte)
        self.assertNotIn("camera_service", fonte)
        self.assertNotIn("OperationEngine", fonte)
        self.assertNotIn("SegmentDisplayRuntimeMixin", fonte)
        self.assertNotIn("operacao_window", fonte)

    def test_f3_expoe_api_de_avanco_sem_sobrescrever_trigger_f2(self):
        self.assertIn("registrar_resultado_check_display_f3", DisplayProductionF3Mixin.__dict__)
        self.assertIn("concluir_check_display_f3", DisplayProductionF3Mixin.__dict__)
        self.assertIn("descartar_placa_display_f3", DisplayProductionF3Mixin.__dict__)
        self.assertNotIn("disparar_inspecao_operacao", DisplayProductionF3Mixin.__dict__)
        self.assertNotIn("_evento_enter_pressionado", DisplayProductionF3Mixin.__dict__)

    def test_descartar_pelo_mixin_nao_altera_contadores_f2(self):
        app = DisplayProductionF3Mixin.__new__(DisplayProductionF3Mixin)
        app.display_f3_ativo = True
        app.display_check_runtime = DisplayCheckSequenceRuntime()
        app.display_check_runtime.configurar_checks(CHECKS)
        app.display_f3_window = _FakeWindow()
        app.display_f3_result_after_id = None
        app.root = _FakeRoot()

        # Sentinelas pertencentes ao F2.
        app.operacao_total = 91
        app.operacao_ok = 80
        app.operacao_ng = 11
        antes_f2 = (app.operacao_total, app.operacao_ok, app.operacao_ng)

        evento = app.descartar_placa_display_f3()

        self.assertIsNotNone(evento)
        self.assertEqual(
            DisplayCheckSequenceRuntime.EVENT_PLATE_DISCARDED,
            evento["event"],
        )
        snapshot = app.display_check_runtime.snapshot()
        self.assertEqual((1, 0, 1), (snapshot["total"], snapshot["ok"], snapshot["ng"]))
        self.assertEqual("H1", snapshot["current_check"]["name"])
        self.assertIsNone(snapshot["last_result"])
        self.assertIsNone(obter_feedback_espera_display_f3(snapshot))
        self.assertEqual(antes_f2, (app.operacao_total, app.operacao_ok, app.operacao_ng))
        self.assertEqual(1, len(app.display_f3_window.results))

    def test_avanco_real_emite_banner_sobre_camera_direita(self):
        app = DisplayProductionF3Mixin.__new__(DisplayProductionF3Mixin)
        app.display_check_runtime = DisplayCheckSequenceRuntime()
        app.display_check_runtime.configurar_checks(CHECKS)
        app.display_f3_result_after_id = None
        app.root = _FakeRoot()
        app.display_f3_window = _FakeWindow()
        app.display_f3_window.show_check_advance_notice = Mock()
        app._renderizar_fluxo_checks_display_f3 = Mock()

        event = app.registrar_resultado_check_display_f3(True)
        self.assertEqual("check_advanced", event["event"])
        app.display_f3_window.show_check_advance_notice.assert_called_once_with(
            "H1", "BLUE",
        )
        self.assertEqual("BLUE", event["snapshot"]["current_check"]["name"])

        app.display_f3_window.show_check_advance_notice.reset_mock()
        app.registrar_resultado_check_display_f3(True)
        app.display_f3_window.show_check_advance_notice.assert_called_once_with(
            "BLUE", "AUX",
        )
        app.registrar_resultado_check_display_f3(True)
        app.display_f3_window.show_check_advance_notice.reset_mock()
        final_event = app.registrar_resultado_check_display_f3(True)
        self.assertEqual("plate_ok", final_event["event"])
        app.display_f3_window.show_check_advance_notice.assert_not_called()

    def test_banner_sobre_camera_tem_ciclo_de_vida_sem_timer_periodico(self):
        banner = Mock()
        root = _FakeRoot()
        screen = DisplayProductionF3Window.__new__(DisplayProductionF3Window)
        screen.root = root
        screen.check_advance_banner = banner
        screen._check_advance_hide_after_id = None
        screen._display_ng_evidence_frozen = False
        screen._display_terminal_waiting_removal = False
        screen.container = Mock()
        screen.show_check_advance_notice("H1", "BLUE")
        banner.configure.assert_called_with(
            text="H1 APROVADO  •  PRÓXIMO: BLUE",
        )
        self.assertEqual(1700, root.after_calls[-1][1])
        self.assertEqual(0.94, banner.place.call_args.kwargs["relwidth"])

        first_id = root.after_calls[-1][0]
        screen.show_check_advance_notice("BLUE", "AUX")
        self.assertIn(first_id, root.cancel_calls)
        screen.hide()
        self.assertIn(root.after_calls[-1][0], root.cancel_calls)
        banner.place_forget.assert_called()
        screen.container.place_forget.assert_called_once()

    def test_banner_nao_sobrepoe_estado_terminal_ng(self):
        screen = DisplayProductionF3Window.__new__(DisplayProductionF3Window)
        screen.root = _FakeRoot()
        screen.check_advance_banner = Mock()
        screen._check_advance_hide_after_id = None
        screen._display_ng_evidence_frozen = True
        screen._display_terminal_waiting_removal = False
        screen.show_check_advance_notice("H1", "BLUE")
        screen.check_advance_banner.place.assert_not_called()

    def test_janela_f3_tem_tecla_1_e_botao_de_descarte(self):
        fonte = inspect.getsource(DisplayProductionF3Window.__init__)
        self.assertIn('self.container.bind("<KeyPress-1>", self._handle_discard)', fonte)
        self.assertIn('self.container.bind("<KP_1>", self._handle_discard)', fonte)
        self.assertIn('text="DESCARTAR PLACA  [1]"', fonte)

    def test_janela_f3_exibe_cards_e_contadores_separados(self):
        fonte = inspect.getsource(DisplayProductionF3Window)
        self.assertIn("check_flow_frame", fonte)
        self.assertIn("CONCLUÍDO", fonte)
        self.assertIn("AGUARDANDO", fonte)
        self.assertIn("PRÓXIMO", fonte)
        self.assertIn("self._set_counters", fonte)
        self.assertNotIn("operacao_total", fonte)
        self.assertNotIn("operacao_ok", fonte)
        self.assertNotIn("operacao_ng", fonte)


if __name__ == "__main__":
    unittest.main()
