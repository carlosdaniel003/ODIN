from __future__ import annotations

import math

from src.platform.display_f3_check_reference_zoom import (
    F3_CHECK_REFERENCE_ZOOM_MAX,
    F3_CHECK_REFERENCE_ZOOM_MIN,
    calcular_centro_zoom_ancorado_referencia_f3,
    calcular_escala_ajuste_referencia_f3,
    limitar_zoom_referencia_f3,
)


def test_escala_ajuste_preserva_proporcao_da_foto() -> None:
    scale = calcular_escala_ajuste_referencia_f3(
        image_width=1920,
        image_height=1080,
        viewport_width=1280,
        viewport_height=720,
    )

    assert math.isclose(scale, 2.0 / 3.0, rel_tol=1e-6)
    assert math.isclose(1920 * scale, 1280.0, rel_tol=1e-6)
    assert math.isclose(1080 * scale, 720.0, rel_tol=1e-6)


def test_zoom_e_limitado_para_evitar_estado_invalido() -> None:
    assert limitar_zoom_referencia_f3(0.001) == F3_CHECK_REFERENCE_ZOOM_MIN
    assert limitar_zoom_referencia_f3(100.0) == F3_CHECK_REFERENCE_ZOOM_MAX
    assert limitar_zoom_referencia_f3(1.75) == 1.75


def test_zoom_ancorado_mantem_pixel_sob_ponteiro() -> None:
    viewport_width = 1200
    viewport_height = 700
    pointer_x = 900.0
    pointer_y = 250.0
    old_scale = 1.0
    new_scale = 2.0
    center_x = 960.0
    center_y = 540.0

    source_before_x = center_x + (pointer_x - viewport_width / 2.0) / old_scale
    source_before_y = center_y + (pointer_y - viewport_height / 2.0) / old_scale

    new_center_x, new_center_y = calcular_centro_zoom_ancorado_referencia_f3(
        center_x=center_x,
        center_y=center_y,
        old_scale=old_scale,
        new_scale=new_scale,
        pointer_x=pointer_x,
        pointer_y=pointer_y,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )

    source_after_x = new_center_x + (pointer_x - viewport_width / 2.0) / new_scale
    source_after_y = new_center_y + (pointer_y - viewport_height / 2.0) / new_scale

    assert math.isclose(source_before_x, source_after_x, rel_tol=1e-9)
    assert math.isclose(source_before_y, source_after_y, rel_tol=1e-9)
