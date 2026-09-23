from __future__ import annotations

import math
from copy import deepcopy
from types import SimpleNamespace

from config import DEFAULT_RADIUS_PX, MAX_RADIUS_PX, MIN_RADIUS_PX
from src.core.roi_geometry import (
    SEGMENTO_ALTURA_MINIMA,
    SEGMENTO_ALTURA_PADRAO,
    SEGMENTO_LARGURA_MINIMA,
    SEGMENTO_LARGURA_PADRAO,
    normalizar_angulo_segmento,
    pontos_segmento,
)
from src.platform.display_project_repository import (
    normalizar_mascaras_display,
    normalizar_resolucao_display,
)

TOOL_SEGMENT = "segment"
TOOL_CIRCLE = "circle"
TOOL_FREEFORM = "freeform"
TOOL_MASS = "mass"
DISPLAY_MASK_F2_PARITY_TOOLS = (TOOL_SEGMENT, TOOL_CIRCLE, TOOL_FREEFORM, TOOL_MASS)


def _id(mask: dict) -> str:
    return str(mask.get("id", ""))


def _area(points) -> float:
    source = () if points is None else points
    pts = [(float(p[0]), float(p[1])) for p in source]
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])
        )
    ) / 2 if len(pts) >= 3 else 0.0


def criar_segmento_display_por_arrasto(
    x1,
    y1,
    x2,
    y2,
    altura_segmento=SEGMENTO_ALTURA_PADRAO,
    id_mascara="MASK_001",
) -> dict:
    dx, dy = float(x2) - float(x1), float(y2) - float(y1)
    comprimento = math.hypot(dx, dy)
    if comprimento < SEGMENTO_LARGURA_MINIMA:
        cx = int(round(x1))
        cy = int(round(y1))
        largura = SEGMENTO_LARGURA_PADRAO
        angulo = 0.0
    else:
        cx = int(round((x1 + x2) / 2))
        cy = int(round((y1 + y2) / 2))
        largura = max(SEGMENTO_LARGURA_MINIMA, int(round(comprimento)))
        angulo = math.degrees(math.atan2(dy, dx))
    return {
        "id": str(id_mascara),
        "type": "segment",
        "cx": cx,
        "cy": cy,
        "width": largura,
        "height": max(SEGMENTO_ALTURA_MINIMA, int(altura_segmento)),
        "angle": normalizar_angulo_segmento(angulo),
    }


def criar_poligono_display_por_pontos(
    pontos,
    id_mascara: str = "MASK_001",
) -> dict:
    """Cria no F3 exatamente o contorno ponto a ponto usado como ROI real.

    Os pontos recebidos pertencem à resolução mestre e não são convertidos em
    círculo, bounding box ou segmento aproximado. Isso mantém a mesma semântica
    visual da ferramenta ``Segmento por pontos`` do Selecionar LEDs.
    """
    vertices = []
    source = () if pontos is None else pontos
    for ponto in source:
        try:
            if len(ponto) < 2:
                continue
            vertices.append(
                [int(round(float(ponto[0]))), int(round(float(ponto[1])))]
            )
        except (TypeError, ValueError, IndexError):
            continue
    if len(vertices) < 3 or _area(vertices) < 4:
        raise ValueError("A máscara por pontos precisa de pelo menos 3 vértices válidos.")
    return {
        "id": str(id_mascara),
        "type": "polygon",
        "points": vertices,
    }


def _segment_points(mask: dict):
    alvo = SimpleNamespace(
        centro_x=int(mask.get("cx", 0)),
        centro_y=int(mask.get("cy", 0)),
        raio=1,
        tipo_roi="segmento",
        largura=int(mask.get("width", SEGMENTO_LARGURA_PADRAO)),
        altura=int(mask.get("height", SEGMENTO_ALTURA_PADRAO)),
        angulo=float(mask.get("angle", 0) or 0),
        pontos_segmento_livre=None,
    )
    return [(float(x), float(y)) for x, y in pontos_segmento(alvo)]


def pontos_mascara_display(mask: dict) -> list[tuple[float, float]]:
    """Retorna o contorno efetivo desenhado/analisado pelo editor F3."""
    kind = str(mask.get("type", "")).lower()
    if kind == "segment":
        return _segment_points(mask)
    if kind == "polygon":
        return [
            (float(p[0]), float(p[1]))
            for p in mask.get("points", [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
    if kind == "rectangle":
        return pontos_mascara_display(converter_mascara_legada_para_editor(mask))
    return []


def converter_mascara_legada_para_editor(mask: dict) -> dict:
    item = deepcopy(mask)
    if str(item.get("type", "")).lower() != "rectangle":
        return item
    x = int(item.get("x", 0))
    y = int(item.get("y", 0))
    w = max(1, int(item.get("width", 1)))
    h = max(1, int(item.get("height", 1)))
    return {
        "id": _id(item),
        "type": "segment",
        "cx": int(round(x + w / 2)),
        "cy": int(round(y + h / 2)),
        "width": w,
        "height": h,
        "angle": 0.0,
    }


def _inside_poly(points, x, y) -> bool:
    pts = list(points or [])
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = map(float, pts[i])
        xj, yj = map(float, pts[j])
        if ((yi > y) != (yj > y)) and x < (
            (xj - xi) * (y - yi) / float((yj - yi) or 1e-9) + xi
        ):
            inside = not inside
        j = i
    return inside


def _centro_escala_mascara_display(mask: dict):
    item = converter_mascara_legada_para_editor(mask)
    kind = str(item.get("type") or "").lower()
    if kind == "circle":
        try:
            cx = float(item.get("cx", 0))
            cy = float(item.get("cy", 0))
            diameter = max(2.0, float(item.get("radius", 1)) * 2.0)
            return (cx, cy), diameter
        except (TypeError, ValueError):
            return None, 0.0

    points = pontos_mascara_display(item)
    if not points:
        return None, 0.0
    cx = sum(float(point[0]) for point in points) / len(points)
    cy = sum(float(point[1]) for point in points) / len(points)
    diameter = 0.0
    for index, point in enumerate(points):
        for other in points[index + 1:]:
            diameter = max(
                diameter,
                math.hypot(
                    float(other[0]) - float(point[0]),
                    float(other[1]) - float(point[1]),
                ),
            )
    return (cx, cy), max(1.0, diameter)


def _angulo_formato_mascara_display(mask: dict) -> float | None:
    item = converter_mascara_legada_para_editor(mask)
    kind = str(item.get("type") or "").lower()
    if kind == "segment":
        try:
            return float(item.get("angle", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    if kind != "polygon":
        return None
    points = pontos_mascara_display(item)
    if len(points) < 2:
        return None
    x1, y1 = points[0]
    for x2, y2 in points[1:]:
        if math.hypot(float(x2) - float(x1), float(y2) - float(y1)) > 1e-6:
            return math.degrees(
                math.atan2(float(y2) - float(y1), float(x2) - float(x1))
            )
    return None


def _mesmo_formato_mascara_display(base: dict, local: dict) -> bool:
    base_item = converter_mascara_legada_para_editor(base)
    local_item = converter_mascara_legada_para_editor(local)
    base_kind = str(base_item.get("type") or "").lower()
    local_kind = str(local_item.get("type") or "").lower()
    if base_kind != local_kind:
        return False
    if base_kind == "circle":
        return True
    if base_kind == "segment":
        return True
    if base_kind == "polygon":
        return len(pontos_mascara_display(base_item)) == len(
            pontos_mascara_display(local_item)
        )
    return False


def _formatos_compativeis_para_rotacao(base: dict, local: dict) -> bool:
    base_item = converter_mascara_legada_para_editor(base)
    local_item = converter_mascara_legada_para_editor(local)
    base_kind = str(base_item.get("type") or "").lower()
    local_kind = str(local_item.get("type") or "").lower()
    if base_kind == "segment" and local_kind == "segment":
        return True
    if base_kind == "polygon" and local_kind == "polygon":
        return len(pontos_mascara_display(base_item)) == len(
            pontos_mascara_display(local_item)
        )
    return False


def sincronizar_formato_mascara_display(
    mascara_base: dict,
    geometria_local: dict | None,
) -> dict:
    """Mantém o FORMATO canônico e reaproveita apenas a pose local.

    A máscara desenhada em "Desenhar placa e máscaras" é a autoridade do formato.
    CHECKS/rastreamento podem manter posição, escala e rotação próprias, mas um
    triângulo continua triângulo, um segmento continua segmento e um círculo
    continua círculo.
    """
    base = converter_mascara_legada_para_editor(deepcopy(mascara_base or {}))
    local = converter_mascara_legada_para_editor(
        deepcopy(geometria_local or mascara_base or {})
    )
    mask_id = str(base.get("id") or local.get("id") or "")
    if mask_id:
        base["id"] = mask_id
        local["id"] = mask_id

    # O CHECK continua livre para ajustar sua própria geometria enquanto o
    # FORMATO for o mesmo. Triângulo (3 pontos) continua triângulo, segmento
    # continua segmento e círculo continua círculo. Só corrigimos incompatíveis.
    if _mesmo_formato_mascara_display(base, local):
        return deepcopy(local)

    base_center, base_size = _centro_escala_mascara_display(base)
    local_center, local_size = _centro_escala_mascara_display(local)
    if base_center is None:
        return deepcopy(base)
    if local_center is None:
        return deepcopy(base)

    scale = (
        max(0.05, min(20.0, float(local_size) / max(1e-6, float(base_size))))
        if local_size > 0
        else 1.0
    )

    rotation = 0.0
    if _formatos_compativeis_para_rotacao(base, local):
        base_angle = _angulo_formato_mascara_display(base)
        local_angle = _angulo_formato_mascara_display(local)
        if base_angle is not None and local_angle is not None:
            rotation = float(local_angle) - float(base_angle)

    kind = str(base.get("type") or "").lower()
    if kind == "circle":
        result = deepcopy(base)
        result["cx"] = float(local_center[0])
        result["cy"] = float(local_center[1])
        result["radius"] = max(
            1.0,
            float(base.get("radius", 1)) * scale,
        )
        return result

    if kind == "segment":
        result = deepcopy(base)
        result["cx"] = float(local_center[0])
        result["cy"] = float(local_center[1])
        result["width"] = max(
            SEGMENTO_LARGURA_MINIMA,
            float(base.get("width", SEGMENTO_LARGURA_PADRAO)) * scale,
        )
        result["height"] = max(
            SEGMENTO_ALTURA_MINIMA,
            float(base.get("height", SEGMENTO_ALTURA_PADRAO)) * scale,
        )
        result["angle"] = normalizar_angulo_segmento(
            float(base.get("angle", 0.0) or 0.0) + rotation
        )
        return result

    points = pontos_mascara_display(base)
    if kind == "polygon" and len(points) >= 3:
        angle = math.radians(rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        transformed = []
        for x, y in points:
            dx = (float(x) - float(base_center[0])) * scale
            dy = (float(y) - float(base_center[1])) * scale
            transformed.append(
                [
                    float(local_center[0]) + dx * cos_a - dy * sin_a,
                    float(local_center[1]) + dx * sin_a + dy * cos_a,
                ]
            )
        return {
            "id": mask_id,
            "type": "polygon",
            "points": transformed,
        }

    return deepcopy(base)


def sincronizar_colecao_mascaras_display(
    mascaras_base,
    geometrias_locais,
    *,
    somente_ids_locais: bool = False,
) -> list[dict]:
    """Reconcilia geometrias locais com o formato atual das máscaras do projeto.

    O ID liga as duas geometrias. A máscara canônica define tipo/topologia
    (círculo, segmento, polígono e quantidade de vértices). A geometria local
    fornece a pose já ajustada naquela referência ou CHECK.

    somente_ids_locais=True preserva coleções completas como masks_reference:
    IDs ausentes continuam ausentes (exclusão local).
    """
    bases = [
        converter_mascara_legada_para_editor(deepcopy(mask))
        for mask in (mascaras_base or [])
        if isinstance(mask, dict) and str(mask.get("id") or "")
    ]
    locais = {}
    source = (
        geometrias_locais.values()
        if isinstance(geometrias_locais, dict)
        else (geometrias_locais or [])
    )
    for raw in source:
        if not isinstance(raw, dict):
            continue
        mask_id = str(raw.get("id") or "")
        if mask_id:
            locais[mask_id] = deepcopy(raw)

    resultado = []
    for base in bases:
        mask_id = str(base.get("id") or "")
        local = locais.get(mask_id)
        if local is None:
            if somente_ids_locais:
                continue
            resultado.append(deepcopy(base))
            continue
        synced = sincronizar_formato_mascara_display(base, local)
        synced["id"] = mask_id
        resultado.append(synced)
    return resultado


def mascara_display_contem_ponto(mask: dict, x, y) -> bool:
    kind = str(mask.get("type", "")).lower()
    if kind == "circle":
        return (
            (float(x) - float(mask.get("cx", 0))) ** 2
            + (float(y) - float(mask.get("cy", 0))) ** 2
            <= max(1, float(mask.get("radius", 1))) ** 2
        )
    if kind in {"segment", "polygon", "rectangle"}:
        return _inside_poly(pontos_mascara_display(mask), x, y)
    return False


def bbox_mascara_display(mask: dict):
    kind = str(mask.get("type", "")).lower()
    if kind == "circle":
        cx = float(mask.get("cx", 0))
        cy = float(mask.get("cy", 0))
        r = float(max(1, mask.get("radius", 1)))
        return cx - r, cy - r, cx + r, cy + r
    pts = pontos_mascara_display(mask)
    if not pts:
        return 0.0, 0.0, 0.0, 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def numero_mascara_display(mask_or_id, fallback_index: int | None = None) -> str:
    """Número humano derivado do MASK_ID canônico, nunca da posição na lista."""
    if isinstance(mask_or_id, dict):
        text = str(mask_or_id.get("id") or "").strip()
    else:
        text = str(mask_or_id or "").strip()

    digits = ""
    for char in reversed(text):
        if char.isdigit():
            digits = char + digits
        elif digits:
            break
    if digits:
        try:
            return str(int(digits))
        except ValueError:
            pass
    if fallback_index is not None:
        return str(max(1, int(fallback_index)))
    return text or "?"


def _centro_mascara_display(mask: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox_mascara_display(mask)
    return (float(x1 + x2) / 2.0, float(y1 + y2) / 2.0)


def mapear_slots_sete_segmentos_display(
    masks,
    *,
    digit_count: int = 4,
) -> list[str]:
    """Mapeia a geometria visível para A,B,C,D,E,F,G de cada dígito.

    A identidade é sempre o MASK_ID já criado em "Desenhar placa e máscaras".
    A posição geométrica serve apenas para descobrir em qual barra lógica do
    visor 88:88 aquele ID está. Nenhum MASK_ID é recriado ou renumerado.
    """
    expected = max(1, int(digit_count)) * 7
    items = [
        deepcopy(mask)
        for mask in (masks or ())
        if isinstance(mask, dict) and str(mask.get("id") or "").strip()
    ]
    if len(items) != expected:
        return []

    ids = [str(mask.get("id") or "").strip() for mask in items]
    if len(set(ids)) != expected:
        return []

    records = []
    for mask in items:
        points = pontos_mascara_display(mask)
        if points:
            cx = sum(float(point[0]) for point in points) / len(points)
            cy = sum(float(point[1]) for point in points) / len(points)
        else:
            cx, cy = _centro_mascara_display(mask)
        records.append({"id": str(mask.get("id") or ""), "cx": float(cx), "cy": float(cy)})

    mean_x = sum(item["cx"] for item in records) / len(records)
    mean_y = sum(item["cy"] for item in records) / len(records)
    sxx = sum((item["cx"] - mean_x) ** 2 for item in records)
    syy = sum((item["cy"] - mean_y) ** 2 for item in records)
    sxy = sum((item["cx"] - mean_x) * (item["cy"] - mean_y) for item in records)

    angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    ux, uy = math.cos(angle), math.sin(angle)
    if abs(ux) >= abs(uy):
        if ux < 0:
            ux, uy = -ux, -uy
    elif uy < 0:
        ux, uy = -ux, -uy

    vx, vy = -uy, ux
    if vy < 0:
        vx, vy = -vx, -vy

    for item in records:
        dx = item["cx"] - mean_x
        dy = item["cy"] - mean_y
        item["u"] = dx * ux + dy * uy
        item["v"] = dx * vx + dy * vy

    ordered = sorted(records, key=lambda item: (item["u"], item["v"], item["id"]))
    groups = [ordered[index:index + 7] for index in range(0, expected, 7)]
    if any(len(group) != 7 for group in groups):
        return []

    result: list[str] = []
    for group in groups:
        group_center_u = sorted(item["u"] for item in group)[3]
        horizontal = sorted(
            group,
            key=lambda item: (
                abs(item["u"] - group_center_u),
                item["v"],
                item["id"],
            ),
        )[:3]
        horizontal_ids = {item["id"] for item in horizontal}
        vertical = [item for item in group if item["id"] not in horizontal_ids]
        if len(vertical) != 4:
            return []

        top, middle, bottom = sorted(
            horizontal,
            key=lambda item: (item["v"], item["u"], item["id"]),
        )
        vertical_by_height = sorted(
            vertical,
            key=lambda item: (item["v"], item["u"], item["id"]),
        )
        upper = sorted(vertical_by_height[:2], key=lambda item: (item["u"], item["id"]))
        lower = sorted(vertical_by_height[2:], key=lambda item: (item["u"], item["id"]))
        if len(upper) != 2 or len(lower) != 2:
            return []

        segment_map = {
            "a": top["id"],
            "b": upper[1]["id"],
            "c": lower[1]["id"],
            "d": bottom["id"],
            "e": lower[0]["id"],
            "f": upper[0]["id"],
            "g": middle["id"],
        }
        result.extend(segment_map[name] for name in ("a", "b", "c", "d", "e", "f", "g"))

    return result


def _bbox(masks):
    items = list(masks)
    if not items:
        return None
    boxes = [bbox_mascara_display(m) for m in items]
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _valid(mask, w, h):
    x1, y1, x2, y2 = bbox_mascara_display(mask)
    return x1 >= 0 and y1 >= 0 and x2 < int(w) and y2 < int(h)


def _rotate_xy(x, y, cx, cy, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    dx, dy = float(x) - cx, float(y) - cy
    return cx + dx * c - dy * s, cy + dx * s + dy * c


def _move(mask, dx, dy):
    m = deepcopy(mask)
    kind = m.get("type")
    if kind in {"circle", "segment"}:
        m["cx"] = int(round(m["cx"] + dx))
        m["cy"] = int(round(m["cy"] + dy))
    elif kind == "polygon":
        m["points"] = [
            [int(round(x + dx)), int(round(y + dy))]
            for x, y in m["points"]
        ]
    return m


def _rotate(mask, cx, cy, deg):
    m = deepcopy(mask)
    kind = m.get("type")
    if kind in {"circle", "segment"}:
        x, y = _rotate_xy(m["cx"], m["cy"], cx, cy, deg)
        m["cx"], m["cy"] = int(round(x)), int(round(y))
        if kind == "segment":
            m["angle"] = normalizar_angulo_segmento(float(m.get("angle", 0)) + deg)
    elif kind == "polygon":
        m["points"] = [
            [int(round(x)), int(round(y))]
            for x, y in (
                _rotate_xy(p[0], p[1], cx, cy, deg)
                for p in m["points"]
            )
        ]
    return m


def _scale(mask, cx, cy, sx, sy):
    m = deepcopy(mask)
    kind = m.get("type")
    if kind in {"circle", "segment"}:
        m["cx"] = int(round(cx + (m["cx"] - cx) * sx))
        m["cy"] = int(round(cy + (m["cy"] - cy) * sy))
    if kind == "circle":
        m["radius"] = max(
            MIN_RADIUS_PX,
            min(
                MAX_RADIUS_PX,
                int(round(m["radius"] * min(abs(sx), abs(sy)))),
            ),
        )
    elif kind == "segment":
        m["width"] = max(
            SEGMENTO_LARGURA_MINIMA,
            int(round(m["width"] * abs(sx))),
        )
        m["height"] = max(
            SEGMENTO_ALTURA_MINIMA,
            int(round(m["height"] * abs(sy))),
        )
    elif kind == "polygon":
        m["points"] = [
            [
                int(round(cx + (x - cx) * sx)),
                int(round(cy + (y - cy) * sy)),
            ]
            for x, y in m["points"]
        ]
    return m


def instalar_suporte_segmento_mascara_display() -> None:
    """Estende apenas o subsistema Display; nenhum módulo de Produção F2 é alterado."""
    import src.platform.display_project_repository as repo

    if not getattr(repo, "_odin_display_segment_mask_support", False):
        original = repo.normalizar_mascara_display

        def normalizar(mascara: dict, indice: int = 1):
            if (
                isinstance(mascara, dict)
                and str(mascara.get("type", mascara.get("tipo", ""))).lower()
                in {"segment", "segmento"}
            ):
                try:
                    mid = str(mascara.get("id") or f"MASK_{indice:03d}")
                    cx = int(mascara.get("cx", mascara.get("centro_x")))
                    cy = int(mascara.get("cy", mascara.get("centro_y")))
                    w = int(mascara.get("width", mascara.get("largura")))
                    h = int(mascara.get("height", mascara.get("altura")))
                    a = normalizar_angulo_segmento(
                        mascara.get("angle", mascara.get("angulo", 0))
                    )
                except (TypeError, ValueError):
                    return None
                if w < SEGMENTO_LARGURA_MINIMA or h < SEGMENTO_ALTURA_MINIMA:
                    return None
                return {
                    "id": mid,
                    "type": "segment",
                    "cx": cx,
                    "cy": cy,
                    "width": w,
                    "height": h,
                    "angle": a,
                }
            return original(mascara, indice)

        repo.normalizar_mascara_display = normalizar
        repo._odin_display_segment_mask_support = True
    try:
        import src.platform.display_check_editor as checks
        cls = checks.DisplayCheckMaskEditorWindow
    except Exception:
        return
    if getattr(cls, "_odin_display_segment_mask_support", False):
        return
    old_contains, old_draw = cls._contains, cls._draw_mask
    cls._contains = staticmethod(
        lambda m, x, y: (
            mascara_display_contem_ponto(m, x, y)
            if m.get("type") == "segment"
            else old_contains(m, x, y)
        )
    )

    def draw(self, index, mask):
        if mask.get("type") == "segment":
            temp = deepcopy(mask)
            temp["type"] = "polygon"
            temp["points"] = [
                [int(round(x)), int(round(y))]
                for x, y in pontos_mascara_display(mask)
            ]
            return old_draw(self, index, temp)
        return old_draw(self, index, mask)

    cls._draw_mask = draw
    cls._odin_display_segment_mask_support = True


instalar_suporte_segmento_mascara_display()
