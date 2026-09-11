import unittest
from unittest.mock import patch

from src.platform.blue_operation_window import (
    BlueRaspberryOperationWindow,
    texto_placa_analisada_f2,
)
from src.platform.raspberry_runtime_fixes import StableRaspberryOperationWindow


class _FakeLabel:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class F2PostResultTextLayoutTests(unittest.TestCase):
    def test_texto_ok_usa_linhas_curtas(self):
        self.assertEqual(
            "PLACA OK\nINSIRA UMA NOVA PLACA",
            texto_placa_analisada_f2(True),
        )

    def test_texto_ng_usa_linhas_curtas(self):
        self.assertEqual(
            "PLACA NG\nPONTOS APAGADOS\nDESTACADOS NA CÂMERA",
            texto_placa_analisada_f2(False),
        )

    def test_show_waiting_centraliza_e_desliga_wrap_antigo(self):
        window = BlueRaspberryOperationWindow.__new__(BlueRaspberryOperationWindow)
        window.detail_label = _FakeLabel()
        window._has_led_result = True
        window._last_result_ok = False

        with patch.object(
            StableRaspberryOperationWindow,
            "show_waiting",
            return_value=None,
        ):
            BlueRaspberryOperationWindow.show_waiting(
                window,
                led_count=10,
                total=1,
                ok_count=0,
                ng_count=1,
            )

        self.assertEqual("center", window.detail_label.options["justify"])
        self.assertEqual("center", window.detail_label.options["anchor"])
        self.assertEqual(0, window.detail_label.options["wraplength"])
        self.assertEqual(
            "PLACA NG\nPONTOS APAGADOS\nDESTACADOS NA CÂMERA",
            window.detail_label.options["text"],
        )


if __name__ == "__main__":
    unittest.main()
