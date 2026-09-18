from __future__ import annotations

from src.platform.display_project_config import DisplayProjectConfigWindow
from src.platform.display_f3_window_geometry import fit_f3_toplevel


F3_CONFIG_MIN_WIDTH = 760
F3_CONFIG_MIN_HEIGHT = 540
F3_CONFIG_MIN_WRAP = 280


def maximizar_janela_configuracao_display_f3(window) -> str:
    """Abre grande sem ultrapassar a área útil nem esconder ações inferiores."""
    try:
        window.resizable(True, True)
        window.minsize(F3_CONFIG_MIN_WIDTH, F3_CONFIG_MIN_HEIGHT)
    except Exception:
        pass
    fit_f3_toplevel(
        window,
        getattr(window, "master", None),
        width_ratio=0.94,
        height_ratio=0.86,
        min_width=F3_CONFIG_MIN_WIDTH,
        min_height=F3_CONFIG_MIN_HEIGHT,
    )
    return "safe_workspace_geometry"


def tornar_layout_configuracao_responsivo_display_f3(owner) -> None:
    """Remove a rigidez visual 310/450 e distribui a largura disponível."""
    project_list = getattr(owner, "project_list", None)
    project_state = getattr(owner, "project_state", None)
    left = getattr(project_list, "master", None)

    # project_state -> right_inner -> right_canvas -> right_shell
    right_inner = getattr(project_state, "master", None)
    right_canvas = getattr(right_inner, "master", None)
    right_shell = getattr(right_canvas, "master", None)

    if left is not None:
        try:
            left.pack_configure(fill="both", expand=True)
            left.pack_propagate(True)
        except Exception:
            pass

    if right_shell is not None:
        try:
            right_shell.pack_configure(
                side="right",
                fill="both",
                expand=True,
                padx=(12, 0),
            )
            right_shell.pack_propagate(True)
        except Exception:
            pass

        def resize_state(event, label=project_state):
            if label is None:
                return
            try:
                label.configure(
                    wraplength=max(F3_CONFIG_MIN_WRAP, int(event.width) - 48)
                )
            except Exception:
                pass

        try:
            right_shell.bind("<Configure>", resize_state, add="+")
        except Exception:
            pass


_INSTALLED = False


def instalar_configuracao_responsiva_display_f3() -> None:
    """Faz o botão CONFIGURAR do F3 abrir maximizado e responder ao tamanho da tela."""
    global _INSTALLED
    if _INSTALLED:
        return

    cls = DisplayProjectConfigWindow
    if bool(getattr(cls, "_display_f3_responsive_config_installed", False)):
        _INSTALLED = True
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        tornar_layout_configuracao_responsivo_display_f3(self)
        self._display_f3_config_window_mode = maximizar_janela_configuracao_display_f3(
            self.window
        )

        # Reaplica depois que o gerenciador de janelas terminou de montar o
        # Toplevel. Evita que geometry/transient do Tk devolva a janela a 820x680.
        try:
            self.window.after_idle(
                lambda owner=self: maximizar_janela_configuracao_display_f3(
                    owner.window
                )
            )
        except Exception:
            pass

    cls.__init__ = init
    cls._display_f3_responsive_config_installed = True
    _INSTALLED = True
