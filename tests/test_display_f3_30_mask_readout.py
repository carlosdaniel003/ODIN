"""Regressões do VISOR F3: 28 barras + FM + ponto decimal configuráveis."""
from __future__ import annotations

import unittest

from src.platform.display_mask_geometry import (
    mapear_indicadores_circulares_display,
    mapear_slots_sete_segmentos_display,
)
from src.platform.display_live_roi_overlay import (
    montar_contexto_overlay_snapshot_display_f3,
)
from src.platform.display_production_f3_window import DisplayProductionF3Window


def _masks_30():
    # Deliberadamente: as 28 barras antigas também são círculos. A seleção
    # dos dois indicadores não pode excluir barras por tipo geométrico.
    offsets = (
        (0, -48), (28, -24), (28, 24), (0, 48),
        (-28, 24), (-28, -24), (0, 0),
    )
    masks = []
    for digit_index, center_x in enumerate((110, 260, 480, 630)):
        for segment_index, (dx, dy) in enumerate(offsets):
            mask_id = f"MASK_{digit_index * 7 + segment_index + 1:03d}"
            masks.append({
                "id": mask_id, "type": "circle",
                "cx": center_x + dx, "cy": 90 + dy, "radius": 7,
            })
    # Os IDs não determinam a função: MASK_029 é o ponto; MASK_030, o FM.
    masks.extend((
        {"id": "MASK_029", "type": "circle", "cx": 367, "cy": 146, "radius": 5},
        {"id": "MASK_030", "type": "circle", "cx": 26, "cy": 68, "radius": 7},
    ))
    return list(reversed(masks))


class _Canvas:
    def __init__(self):
        self.ovals = []
        self.polygons = []
        self.texts = []

    def winfo_width(self):
        return 420

    def winfo_height(self):
        return 108

    def create_oval(self, *coords, **kwargs):
        self.ovals.append({**kwargs, "coords": coords})

    def create_polygon(self, *coords, **kwargs):
        self.polygons.append(kwargs)

    def create_text(self, *coords, **kwargs):
        self.texts.append(kwargs)


def _window(context):
    window = DisplayProductionF3Window.__new__(DisplayProductionF3Window)
    window._display_readout_frozen = False
    window._redraw_display_readout = lambda: None
    window.set_display_readout_context(context)
    window.display_readout_canvas = _Canvas()
    return window


class DisplayF3Readout30MasksTests(unittest.TestCase):
    def test_layout_identifica_os_dois_circulos_sem_renumerar_28_barras(self):
        masks = _masks_30()
        for source in (masks, list(reversed(masks))):
            with self.subTest(reversed=source is not masks):
                slots = mapear_slots_sete_segmentos_display(source)
                indicators = mapear_indicadores_circulares_display(source)
                self.assertEqual(28, len(slots))
                self.assertEqual(28, len(set(slots)))
                self.assertEqual(
                    {f"MASK_{number:03d}" for number in range(1, 29)},
                    set(slots),
                )
                self.assertEqual(
                    {"fm": "MASK_030", "decimal": "MASK_029"},
                    indicators,
                )

    def test_snapshot_tracking_off_conserva_30_ids_e_topologia_em_0_e_180(self):
        masks = _masks_30()
        project = {
            "name": "DISPLAY",
            "master_resolution": (750, 180),
            "masks": masks,
            "checks": [{
                "id": "CHECK_001",
                "name": "H1",
                "mask_states": {mask["id"]: "on" for mask in masks},
            }],
        }

        class Repository:
            def carregar_projeto(self, name):
                return project

        analysis = {
            "effective_classifications": {mask["id"]: "on" for mask in masks},
            "effective_failed_mask_ids": ("MASK_029",),
            "effective_confirmed_failed_mask_ids": ("MASK_029",),
            "effective_validating_mask_ids": (),
        }
        for rotation in (0, 180):
            with self.subTest(rotation=rotation):
                snapshot = montar_contexto_overlay_snapshot_display_f3(
                    Repository(), "DISPLAY", "CHECK_001", analysis, rotation,
                    tracking_geometry=None,
                )
                self.assertEqual(30, len(snapshot["readout_mask_ids"]))
                self.assertEqual(28, len(snapshot["readout_slot_mask_ids"]))
                self.assertEqual(
                    {"fm": "MASK_030", "decimal": "MASK_029"},
                    snapshot["readout_indicator_mask_ids"],
                )
                self.assertEqual(
                    set(snapshot["readout_slot_mask_ids"]),
                    {f"MASK_{number:03d}" for number in range(1, 29)},
                )
                window = _window(snapshot)
                self.assertEqual(
                    snapshot["readout_indicator_mask_ids"],
                    window._display_readout_context["indicator_mask_ids"],
                )
                self.assertEqual(
                    {"MASK_029"},
                    window._display_readout_context["failed_mask_ids"],
                )

    def test_circulos_espelham_emissao_falha_confirmada_e_segregacao(self):
        masks = _masks_30()
        context = {
            "readout_mask_ids": tuple(mask["id"] for mask in masks),
            "readout_slot_mask_ids": mapear_slots_sete_segmentos_display(masks),
            "readout_indicator_mask_ids": mapear_indicadores_circulares_display(masks),
            "live_luminous_only": True,
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": ("MASK_030",),
            "live_visual_classifications": {
                "MASK_030": "on",
                "MASK_029": "off",
            },
        }
        window = _window(context)

        def indicator_states():
            self.assertTrue(window._draw_live_display_readout(window._display_readout_context))
            ovals = [
                item for item in window.display_readout_canvas.ovals
                if "display-readout-indicator" in item.get("tags", ())
            ]
            self.assertEqual(2, len(ovals))
            return {
                tag: item["fill"]
                for item in ovals
                for tag in item["tags"]
                if tag.startswith("display-readout-mask:")
            }

        self.assertEqual({
            "display-readout-mask:MASK_030": window.DISPLAY_READOUT_ACTIVE,
            "display-readout-mask:MASK_029": window.DISPLAY_READOUT_OFF,
        }, indicator_states())
        self.assertTrue(any(item.get("text") == "FM" for item in window.display_readout_canvas.texts))
        circles = {
            tag: item
            for item in window.display_readout_canvas.ovals
            for tag in item.get("tags", ())
            if tag.startswith("display-readout-mask:")
        }
        fm_x = sum(circles["display-readout-mask:MASK_030"]["coords"][::2]) / 2
        decimal_x = sum(circles["display-readout-mask:MASK_029"]["coords"][::2]) / 2
        self.assertLess(fm_x, 60)  # FM fica à esquerda do primeiro dígito
        self.assertGreater(decimal_x, 300)  # 76.0: último intervalo à direita
        self.assertTrue(any(item.get("text") == "29" for item in window.display_readout_canvas.texts))
        self.assertTrue(any(item.get("text") == "30" for item in window.display_readout_canvas.texts))

        window.display_readout_canvas = _Canvas()
        window._display_readout_context["failed_mask_ids"] = {"MASK_029"}
        self.assertEqual(
            window.DISPLAY_READOUT_NG,
            indicator_states()["display-readout-mask:MASK_029"],
        )
        window.display_readout_canvas = _Canvas()
        window._display_readout_context["terminal_segregated"] = True
        self.assertTrue(all(
            value == window.DISPLAY_READOUT_NG
            for value in indicator_states().values()
        ))

    def test_perder_lock_remove_verdes_antigos_sem_perder_30_mascaras(self):
        masks = _masks_30()
        slots = mapear_slots_sete_segmentos_display(masks)
        indicators = mapear_indicadores_circulares_display(masks)
        data = {
            "readout_mask_ids": [m["id"] for m in masks],
            "readout_slot_mask_ids": slots,
            "readout_indicator_mask_ids": indicators,
            "live_luminous_only": True,
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": ("MASK_001", "MASK_030"),
            "live_visual_classifications": {
                "MASK_001": "on", "MASK_030": "on"
            },
            "power_confirmed": True,
            "energy_state": "powered",
        }
        window = _window(data)
        original = window._display_readout_context
        self.assertEqual(
            "on",
            window._display_readout_mask_state("MASK_001", original, True),
        )
        window.suspend_display_readout_live_evidence()
        stopped = window._display_readout_context
        self.assertEqual(30, len(stopped["mask_ids"]))
        self.assertEqual(tuple(slots), stopped["mask_slots"])
        self.assertEqual(indicators, stopped["indicator_mask_ids"])
        self.assertFalse(stopped["live_visual_mask_ids"])
        self.assertFalse(stopped["power_confirmed"])
        for mask_id in stopped["mask_ids"]:
            self.assertEqual(
                "neutral",
                window._display_readout_mask_state(mask_id, stopped, False),
                mask_id,
            )

        # O próximo contexto com LOCK recuperado reativa SOMENTE os segmentos
        # realmente reconhecidos na amostra publicada pela câmera.
        data["live_visual_mask_ids"] = ("MASK_024",)
        data["live_visual_classifications"] = {"MASK_024": "on"}
        window.set_display_readout_context(data)
        restored = window._display_readout_context
        self.assertEqual(
            "on",
            window._display_readout_mask_state("MASK_024", restored, True),
        )
        self.assertEqual(
            "neutral",
            window._display_readout_mask_state("MASK_001", restored, True),
        )

    def test_visor_usb_live_usa_mesma_luz_do_frame_e_nao_vermelho_stale(self):
        # A divergência do CHECK USB continua no status, mas as barras
        # do visor acompanham a luz física; o vermelho é terminal.
        masks = _masks_30()
        context = {
            "readout_mask_ids": [m["id"] for m in masks],
            "readout_slot_mask_ids": mapear_slots_sete_segmentos_display(masks),
            "live_luminous_only": True,
            "live_visual_sample_ready": True,
            "live_visual_mask_ids": (),
            "live_visual_classifications": {"MASK_001": "off"},
            "effective_confirmed_failed_mask_ids": ("MASK_001", "MASK_024"),
            "effective_classifications": {"MASK_001": "on"},
            "expected_states": {"MASK_001": "off"},
        }
        window = _window(context)
        live = window._display_readout_context
        self.assertEqual(
            "off", window._display_readout_mask_state("MASK_001", live, True)
        )
        self.assertEqual(
            "neutral", window._display_readout_mask_state("MASK_024", live, True)
        )
        context["live_visual_mask_ids"] = ("MASK_001",)
        context["live_visual_classifications"] = {"MASK_001": "on"}
        window.set_display_readout_context(context)
        live_on = window._display_readout_context
        self.assertEqual(
            "on", window._display_readout_mask_state("MASK_001", live_on, True)
        )
        # Após freeze legítimo, a mesma MASK_ID recebe vermelho terminal.
        window._display_ng_evidence_frozen = True
        self.assertEqual(
            "ng", window._display_readout_mask_state("MASK_001", live_on, True)
        )
        window._display_ng_evidence_frozen = False
        self.assertEqual(
            "on", window._display_readout_mask_state("MASK_001", live_on, True)
        )

    def test_congelamento_terminal_preserva_evidencia_vermelha(self):
        window = _window({
            "readout_mask_ids": [m["id"] for m in _masks_30()],
            "live_luminous_only": True,
            "effective_confirmed_failed_mask_ids": ("MASK_024",),
        })
        previous = window._display_readout_context
        window._display_readout_frozen = True
        window.suspend_display_readout_live_evidence()
        self.assertIs(previous, window._display_readout_context)
        self.assertEqual({"MASK_024"}, previous["failed_mask_ids"])

    def test_projeto_legado_de_28_mascaras_preserva_dois_pontos_neutros(self):
        masks = [m for m in _masks_30() if m["id"] not in {"MASK_029", "MASK_030"}]
        self.assertEqual(28, len(mapear_slots_sete_segmentos_display(masks)))
        self.assertEqual({}, mapear_indicadores_circulares_display(masks))
        window = _window({
            "readout_mask_ids": [m["id"] for m in masks],
            "readout_slot_mask_ids": mapear_slots_sete_segmentos_display(masks),
        })
        self.assertTrue(window._draw_live_display_readout(window._display_readout_context))
        self.assertFalse(window._display_readout_context["indicator_mask_ids"])
        self.assertEqual(
            2,
            sum("display-readout-colon" in item.get("tags", ())
                for item in window.display_readout_canvas.ovals),
        )


if __name__ == "__main__":
    unittest.main()
