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
