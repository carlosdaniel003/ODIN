from __future__ import annotations

import cv2


F3_SOFTWARE_ZOOM_MIN = 1.0
F3_SOFTWARE_ZOOM_MAX = 5.0
F3_SOFTWARE_ZOOM_CENTER_DEFAULT = 0.5


def _clamp_float(value, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return min(float(maximum), max(float(minimum), number))


def normalizar_centro_zoom_software_display_f3(
    zoom: float,
    center_x: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
    center_y: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
) -> tuple[float, float]:
    zoom = _clamp_float(
        zoom,
        F3_SOFTWARE_ZOOM_MIN,
        F3_SOFTWARE_ZOOM_MAX,
        F3_SOFTWARE_ZOOM_MIN,
    )
    if zoom <= 1.0001:
        return (
            F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
            F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
        )

    margin = min(0.5, 0.5 / zoom)
    x = _clamp_float(center_x, margin, 1.0 - margin, 0.5)
    y = _clamp_float(center_y, margin, 1.0 - margin, 0.5)
    return float(x), float(y)


def calcular_recorte_zoom_software_display_f3(
    frame_shape,
    zoom: float,
    center_x: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
    center_y: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
) -> tuple[int, int, int, int, float, float]:
    if frame_shape is None or len(frame_shape) < 2:
        return (0, 0, 0, 0, 0.5, 0.5)

    height = max(1, int(frame_shape[0]))
    width = max(1, int(frame_shape[1]))
    zoom = _clamp_float(
        zoom,
        F3_SOFTWARE_ZOOM_MIN,
        F3_SOFTWARE_ZOOM_MAX,
        F3_SOFTWARE_ZOOM_MIN,
    )
    center_x, center_y = normalizar_centro_zoom_software_display_f3(
        zoom,
        center_x,
        center_y,
    )

    if zoom <= 1.0001:
        return (0, 0, width, height, center_x, center_y)

    crop_width = max(2, min(width, int(round(width / zoom))))
    crop_height = max(2, min(height, int(round(height / zoom))))

    cx_px = float(center_x) * float(width)
    cy_px = float(center_y) * float(height)
    x0 = int(round(cx_px - crop_width / 2.0))
    y0 = int(round(cy_px - crop_height / 2.0))
    x0 = min(max(0, x0), max(0, width - crop_width))
    y0 = min(max(0, y0), max(0, height - crop_height))
    x1 = min(width, x0 + crop_width)
    y1 = min(height, y0 + crop_height)

    effective_x = (x0 + (x1 - x0) / 2.0) / float(width)
    effective_y = (y0 + (y1 - y0) / 2.0) / float(height)
    return (
        int(x0),
        int(y0),
        int(x1),
        int(y1),
        float(effective_x),
        float(effective_y),
    )


def aplicar_zoom_software_frame_display_f3(
    frame,
    zoom: float,
    center_x: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
    center_y: float = F3_SOFTWARE_ZOOM_CENTER_DEFAULT,
):
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame

    height, width = frame.shape[:2]
    x0, y0, x1, y1, _center_x, _center_y = (
        calcular_recorte_zoom_software_display_f3(
            frame.shape,
            zoom,
            center_x,
            center_y,
        )
    )
    if x0 <= 0 and y0 <= 0 and x1 >= width and y1 >= height:
        return frame

    crop = frame[y0:y1, x0:x1]
    if crop is None or getattr(crop, "size", 0) == 0:
        return frame

    return cv2.resize(
        crop,
        (int(width), int(height)),
        interpolation=cv2.INTER_LINEAR,
    )


def calcular_viewport_efetivo_display_f3(
    frame_shape,
    camera_zoom: float = 1.0,
    software_zoom: float = 1.0,
    camera_center_x: float = 0.5,
    camera_center_y: float = 0.5,
    software_center_x: float = 0.5,
    software_center_y: float = 0.5,
) -> tuple[int, int, int, int, float, float, float]:
    """Retorna o campo final do F3 sobre a visão completa 1x.

    O zoom físico acontece primeiro e o crop ODIN acontece dentro do frame
    entregue pela câmera. O retângulo calculado representa a composição dos
    dois, sempre na orientação natural da câmera.
    """
    camera_zoom = _clamp_float(
        camera_zoom,
        F3_SOFTWARE_ZOOM_MIN,
        F3_SOFTWARE_ZOOM_MAX,
        F3_SOFTWARE_ZOOM_MIN,
    )
    software_zoom = _clamp_float(
        software_zoom,
        F3_SOFTWARE_ZOOM_MIN,
        F3_SOFTWARE_ZOOM_MAX,
        F3_SOFTWARE_ZOOM_MIN,
    )
    camera_center_x, camera_center_y = (
        normalizar_centro_zoom_software_display_f3(
            camera_zoom,
            camera_center_x,
            camera_center_y,
        )
    )
    software_center_x, software_center_y = (
        normalizar_centro_zoom_software_display_f3(
            software_zoom,
            software_center_x,
            software_center_y,
        )
    )

    effective_zoom = float(camera_zoom) * float(software_zoom)
    effective_center_x = (
        float(camera_center_x)
        + (float(software_center_x) - 0.5) / float(camera_zoom)
    )
    effective_center_y = (
        float(camera_center_y)
        + (float(software_center_y) - 0.5) / float(camera_zoom)
    )
    effective_center_x, effective_center_y = (
        normalizar_centro_zoom_software_display_f3(
            effective_zoom,
            effective_center_x,
            effective_center_y,
        )
    )
    x0, y0, x1, y1, effective_center_x, effective_center_y = (
        calcular_recorte_zoom_software_display_f3(
            frame_shape,
            effective_zoom,
            effective_center_x,
            effective_center_y,
        )
    )
    return (
        x0,
        y0,
        x1,
        y1,
        effective_center_x,
        effective_center_y,
        effective_zoom,
    )


def centro_camera_para_pan_tilt_display_f3(
    camera_zoom: float,
    center_x: float,
    center_y: float,
    *,
    pan_limit: float = 180.0,
    tilt_limit: float = 180.0,
) -> tuple[float, float]:
    """Mapeia o centro visual normalizado para PAN/TILT UVC.

    X cresce para a direita. Y da imagem cresce para baixo, enquanto tilt UVC
    positivo normalmente aponta para cima, por isso o eixo vertical é invertido.
    """
    camera_zoom = _clamp_float(
        camera_zoom,
        F3_SOFTWARE_ZOOM_MIN,
        F3_SOFTWARE_ZOOM_MAX,
        F3_SOFTWARE_ZOOM_MIN,
    )
    center_x, center_y = normalizar_centro_zoom_software_display_f3(
        camera_zoom,
        center_x,
        center_y,
    )
    if camera_zoom <= 1.0001:
        return 0.0, 0.0

    margin = min(0.5, 0.5 / camera_zoom)
    travel = max(1e-9, 0.5 - margin)
    nx = min(1.0, max(-1.0, (center_x - 0.5) / travel))
    ny = min(1.0, max(-1.0, (center_y - 0.5) / travel))
    return (
        float(nx) * abs(float(pan_limit)),
        -float(ny) * abs(float(tilt_limit)),
    )

