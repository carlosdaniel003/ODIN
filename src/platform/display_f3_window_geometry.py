from __future__ import annotations

"""Geometria segura para janelas do Display F3.

Evita fullscreen real e dimensões maiores que a área útil do desktop no
Linux/Raspberry. Mantém sempre margem inferior suficiente para botões/toolbar.
"""


F3_WINDOW_MARGIN_X = 64
F3_WINDOW_MARGIN_Y = 118


def fit_f3_toplevel(
    window,
    root=None,
    *,
    preferred_width: int | None = None,
    preferred_height: int | None = None,
    width_ratio: float = 0.92,
    height_ratio: float = 0.84,
    min_width: int = 720,
    min_height: int = 500,
) -> None:
    try:
        sw = max(1, int(window.winfo_screenwidth()))
        sh = max(1, int(window.winfo_screenheight()))
        available_w = max(480, sw - F3_WINDOW_MARGIN_X)
        available_h = max(420, sh - F3_WINDOW_MARGIN_Y)

        target_w = (
            int(preferred_width)
            if preferred_width is not None
            else int(round(sw * float(width_ratio)))
        )
        target_h = (
            int(preferred_height)
            if preferred_height is not None
            else int(round(sh * float(height_ratio)))
        )

        width = min(available_w, max(min_width, target_w))
        height = min(available_h, max(min_height, target_h))

        if root is not None:
            try:
                rx = int(root.winfo_rootx())
                ry = int(root.winfo_rooty())
                rw = max(1, int(root.winfo_width()))
                rh = max(1, int(root.winfo_height()))
                x = rx + max(0, (rw - width) // 2)
                y = ry + max(0, (rh - height) // 2)
            except Exception:
                x = max(0, (sw - width) // 2)
                y = max(8, (sh - height) // 2 - 8)
        else:
            x = max(0, (sw - width) // 2)
            y = max(8, (sh - height) // 2 - 8)

        x = min(max(0, x), max(0, sw - width))
        y = min(max(8, y), max(8, sh - height - 8))
        window.attributes("-fullscreen", False)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.maxsize(available_w, available_h)
    except Exception:
        pass
