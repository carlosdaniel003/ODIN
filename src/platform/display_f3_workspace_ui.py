from __future__ import annotations

"""Layout desktop consistente para as janelas exclusivas do Display F3.

A camada é aplicada somente no bootstrap F3. Ela evita que diferentes extensões
Tk disputem a geometria da mesma Toplevel durante a montagem e mantém um único
pedido de maximização depois que os widgets já foram criados.
"""

from src.platform.display_check_editor import (
    DisplayCheckManagerWindow,
    DisplayCheckMaskEditorWindow,
)
from src.platform.display_mask_editor import DisplayMaskEditorWindow
from src.platform.display_project_config import DisplayProjectConfigWindow
from src.platform.display_reference_learning import DisplayReferenceConfigWindow
from src.platform.display_reference_roi import DisplayReferenceRoiDialog


F3_DESKTOP_MIN_WIDTH = 900
F3_DESKTOP_MIN_HEIGHT = 620
F3_PROJECT_NAV_WIDTH = 300
F3_CHECK_NAV_WIDTH = 380
F3_WORKSPACE_MAX_WIDTH = 1180
F3_EDITOR_REDRAW_DELAY_MS = 90

# O F3 roda também em notebooks/estações com 1366x768 e em Windows com barra de
# tarefas sobreposta/auto-ocultável. Mesmo quando o zoom nativo respeita a área
# útil, controles encostados no limite inferior podem ficar atrás da barra.
# Reservamos uma faixa operacional sem mudar a hierarquia visual das telas.
F3_BOTTOM_SAFE_INSET = 48
F3_FALLBACK_SYSTEM_RESERVED_PX = 72


def _screen_size(window) -> tuple[int, int]:
    try:
        width = max(1, int(window.winfo_screenwidth()))
        height = max(1, int(window.winfo_screenheight()))
        return width, height
    except Exception:
        return F3_DESKTOP_MIN_WIDTH, F3_DESKTOP_MIN_HEIGHT + F3_FALLBACK_SYSTEM_RESERVED_PX


def maximizar_janela_workspace_f3(window) -> str:
    """Maximiza com barra de título sem forçar um flush síncrono do Tk."""
    try:
        window.resizable(True, True)
    except Exception:
        pass

    screen_width, screen_height = _screen_size(window)
    usable_height_hint = max(480, screen_height - F3_FALLBACK_SYSTEM_RESERVED_PX)
    try:
        window.minsize(
            min(F3_DESKTOP_MIN_WIDTH, max(640, screen_width)),
            min(F3_DESKTOP_MIN_HEIGHT, usable_height_hint),
        )
    except Exception:
        pass

    # update_idletasks() não é usado aqui. Em uma janela ainda sendo montada ele
    # reentra no layout/paint do Tk e pode expor frames parcialmente renderizados.
    try:
        window.state("zoomed")
        return "state_zoomed"
    except Exception:
        pass
    try:
        window.attributes("-zoomed", True)
        return "attribute_zoomed"
    except Exception:
        pass

    # Último fallback: nunca usa a altura física inteira da tela. A geometria
    # antiga ia até screenheight e podia deixar a última ação atrás da taskbar.
    try:
        width = max(640, screen_width)
        height = max(480, screen_height - F3_FALLBACK_SYSTEM_RESERVED_PX)
        window.geometry(f"{width}x{height}+0+0")
        return "screen_geometry_safe"
    except Exception:
        return "unavailable"


def _pad_pair(value) -> tuple[int, int]:
    if isinstance(value, (tuple, list)) and value:
        try:
            if len(value) >= 2:
                return int(float(value[0])), int(float(value[1]))
            item = int(float(value[0]))
            return item, item
        except (TypeError, ValueError):
            return 0, 0
    try:
        text = str(value or "0").replace("{", " ").replace("}", " ")
        parts = [part for part in text.split() if part]
        if len(parts) >= 2:
            return int(float(parts[0])), int(float(parts[1]))
        if parts:
            item = int(float(parts[0]))
            return item, item
    except (TypeError, ValueError):
        pass
    return 0, 0


def reservar_area_inferior_workspace_f3(window, preferred_widget=None) -> None:
    """Mantém a última ação acima da borda inferior/taskbar.

    Não cria card, barra nem container novo. Apenas aumenta o `pady` inferior do
    último widget empacotado da própria Toplevel. Isso preserva a composição das
    telas existentes e faz o corpo expansível ceder espaço antes de cortar ações.
    """
    target = preferred_widget
    if target is None and window is not None:
        try:
            children = list(window.winfo_children())
        except Exception:
            children = []
        for child in reversed(children):
            try:
                if str(child.winfo_manager()) == "pack":
                    target = child
                    break
            except Exception:
                continue
    if target is None:
        return
    try:
        info = target.pack_info()
        top_pad, bottom_pad = _pad_pair(info.get("pady", 0))
        target.pack_configure(
            pady=(top_pad, max(bottom_pad, F3_BOTTOM_SAFE_INSET))
        )
    except Exception:
        pass


def _maximizar_agendado(owner) -> None:
    owner._display_f3_workspace_maximize_after_id = None
    window = getattr(owner, "window", None)
    if window is None:
        return
    try:
        if not bool(window.winfo_exists()):
            return
    except Exception:
        pass
    try:
        owner._display_f3_workspace_window_mode = maximizar_janela_workspace_f3(window)
    except Exception:
        pass


def agendar_maximizacao_workspace_f3(owner) -> None:
    """Mantém apenas um pedido de maximização pendente por Toplevel."""
    window = getattr(owner, "window", None)
    if window is None:
        return
    previous = getattr(owner, "_display_f3_workspace_maximize_after_id", None)
    if previous is not None:
        try:
            window.after_cancel(previous)
        except Exception:
            pass
    try:
        owner._display_f3_workspace_maximize_after_id = window.after_idle(
            lambda current=owner: _maximizar_agendado(current)
        )
    except Exception:
        owner._display_f3_workspace_maximize_after_id = None


def _centralizar_conteudo_canvas(canvas, max_width: int = F3_WORKSPACE_MAX_WIDTH) -> None:
    """Mantém o workspace legível em 1920 px sem faixas excessivamente largas."""
    if canvas is None:
        return
    try:
        window_items = [item for item in canvas.find_all() if canvas.type(item) == "window"]
    except Exception:
        window_items = []
    if not window_items:
        return
    window_id = window_items[0]

    def fit(event) -> None:
        try:
            available = max(1, int(event.width))
            width = max(680, min(int(max_width), available - 24))
            x = max(12, (available - width) // 2)
            canvas.itemconfigure(window_id, width=width)
            canvas.coords(window_id, x, 0)
        except Exception:
            pass

    # Substitui a antiga regra de largura total do canvas. Não somamos os dois
    # callbacks porque eles escreveriam larguras diferentes no mesmo item.
    try:
        canvas.bind("<Configure>", fit)
    except Exception:
        pass


def aplicar_workspace_projeto_display_f3(owner) -> None:
    """Sidebar estreita + workspace central para o Projeto Display."""
    project_list = getattr(owner, "project_list", None)
    project_state = getattr(owner, "project_state", None)
    if project_list is None or project_state is None:
        return

    list_frame = getattr(project_list, "master", None)
    left = getattr(list_frame, "master", None)
    body = getattr(left, "master", None)

    right = getattr(project_state, "master", None)
    right_canvas = getattr(right, "master", None)
    right_shell = getattr(right_canvas, "master", None)

    if body is not None:
        try:
            body.pack_configure(fill="both", expand=True, padx=24, pady=(0, 14))
        except Exception:
            pass

    if left is not None:
        try:
            left.configure(width=F3_PROJECT_NAV_WIDTH)
            left.pack_configure(side="left", fill="y", expand=False, padx=(0, 14))
            left.pack_propagate(False)
        except Exception:
            pass

    try:
        project_list.configure(
            bg="#07111F",
            fg="#E2E8F0",
            font=("Segoe UI", 10, "bold"),
            selectbackground="#164E63",
            selectforeground="#FFFFFF",
        )
    except Exception:
        pass

    if right_shell is not None:
        try:
            right_shell.configure(bg="#07111F")
            right_shell.pack_configure(side="right", fill="both", expand=True, padx=0)
            right_shell.pack_propagate(True)
        except Exception:
            pass
    try:
        right_canvas.configure(bg="#07111F", highlightthickness=0)
    except Exception:
        pass

    _centralizar_conteudo_canvas(right_canvas)

    try:
        owner.project_title.configure(font=("Segoe UI", 18, "bold"))
        owner.project_state.configure(font=("Segoe UI", 10), wraplength=1040)
    except Exception:
        pass

    reservar_area_inferior_workspace_f3(getattr(owner, "window", None))


def aplicar_workspace_checks_display_f3(owner) -> None:
    """Lista da sequência como navegação e detalhe usando o restante da tela."""
    check_list = getattr(owner, "check_list", None)
    check_title = getattr(owner, "check_title", None)
    if check_list is None or check_title is None:
        return

    list_frame = getattr(check_list, "master", None)
    left = getattr(list_frame, "master", None)
    body = getattr(left, "master", None)
    right = getattr(check_title, "master", None)

    if body is not None:
        try:
            body.pack_configure(fill="both", expand=True, padx=24, pady=(0, 14))
        except Exception:
            pass
    if left is not None:
        try:
            left.configure(width=F3_CHECK_NAV_WIDTH)
            left.pack_configure(side="left", fill="y", expand=False, padx=(0, 14))
            left.pack_propagate(False)
        except Exception:
            pass
    if right is not None:
        try:
            right.pack_configure(side="right", fill="both", expand=True, padx=0)
            right.pack_propagate(True)
        except Exception:
            pass

        def fit_detail(event) -> None:
            status = getattr(owner, "status", None)
            if status is not None:
                try:
                    status.configure(wraplength=max(360, int(event.width) - 54))
                except Exception:
                    pass

        try:
            right.bind("<Configure>", fit_detail, add="+")
        except Exception:
            pass

    try:
        check_list.configure(
            bg="#07111F",
            fg="#E2E8F0",
            selectbackground="#164E63",
            selectforeground="#FFFFFF",
        )
        check_title.configure(font=("Segoe UI", 18, "bold"))
    except Exception:
        pass

    reservar_area_inferior_workspace_f3(getattr(owner, "window", None))


def _instalar_redraw_configuracao_debounced(cls) -> None:
    """Evita tempestade de redraw durante maximização/redimensionamento."""
    if bool(getattr(cls, "_display_f3_workspace_resize_debounce", False)):
        return
    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        self._display_f3_resize_redraw_after_id = None

        def schedule(_event=None, owner=self):
            previous = getattr(owner, "_display_f3_resize_redraw_after_id", None)
            if previous is not None:
                try:
                    owner.window.after_cancel(previous)
                except Exception:
                    pass
            try:
                owner._display_f3_resize_redraw_after_id = owner.window.after(
                    F3_EDITOR_REDRAW_DELAY_MS,
                    lambda: _finish_resize_redraw(owner),
                )
            except Exception:
                owner._display_f3_resize_redraw_after_id = None

        # Substitui o redraw imediato registrado pelo editor base.
        try:
            canvas.bind("<Configure>", schedule)
        except Exception:
            pass

    cls.__init__ = init
    cls._display_f3_workspace_resize_debounce = True


def _finish_resize_redraw(owner) -> None:
    owner._display_f3_resize_redraw_after_id = None
    try:
        owner.redraw()
    except Exception:
        pass


def _instalar_subclasses_finais() -> None:
    """Extensões de presença alteram geometria depois do init base; finaliza uma vez."""
    try:
        import src.platform.display_visual_reference_status as visual_module

        cls = visual_module.DisplayProjectConfigPresenceWindow
        if not bool(getattr(cls, "_display_f3_workspace_final_presence", False)):
            # Não reutilizar o mesmo nome de variável do wrapper de CHECK abaixo.
            # As funções aninhadas usam closure por referência; reutilizar
            # ``original_init`` fazia a janela de Projeto Display chamar, em
            # runtime, o __init__ de DisplayCheckManagerPresenceWindow.
            original_project_presence_init = cls.__init__

            def project_presence_init(
                self,
                *args,
                _original_init=original_project_presence_init,
                **kwargs,
            ):
                _original_init(self, *args, **kwargs)
                aplicar_workspace_projeto_display_f3(self)
                agendar_maximizacao_workspace_f3(self)

            cls.__init__ = project_presence_init
            cls._display_f3_workspace_final_presence = True
    except Exception:
        pass

    try:
        import src.platform.display_check_presence_reference as check_presence_module

        cls = check_presence_module.DisplayCheckManagerPresenceWindow
        if not bool(getattr(cls, "_display_f3_workspace_final_presence", False)):
            original_check_presence_init = cls.__init__

            def check_presence_init(
                self,
                *args,
                _original_init=original_check_presence_init,
                **kwargs,
            ):
                _original_init(self, *args, **kwargs)
                aplicar_workspace_checks_display_f3(self)
                agendar_maximizacao_workspace_f3(self)

            cls.__init__ = check_presence_init
            cls._display_f3_workspace_final_presence = True
    except Exception:
        pass


_INSTALLED = False


def instalar_workspace_telas_display_f3() -> None:
    """Aplica workspace responsivo a todas as telas de configuração do F3."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Base do Projeto Display. Subclasses finais são maximizadas apenas depois de
    # instalar painéis adicionais para não alternar 820px -> zoom -> 820px -> zoom.
    original_project_init = DisplayProjectConfigWindow.__init__

    def project_init(self, *args, **kwargs):
        original_project_init(self, *args, **kwargs)
        aplicar_workspace_projeto_display_f3(self)
        if type(self) is DisplayProjectConfigWindow:
            agendar_maximizacao_workspace_f3(self)

    DisplayProjectConfigWindow.__init__ = project_init

    # Base do Gerenciar CHECKS; mesma regra para a extensão de presença.
    original_manager_init = DisplayCheckManagerWindow.__init__

    def manager_init(self, *args, **kwargs):
        original_manager_init(self, *args, **kwargs)
        aplicar_workspace_checks_display_f3(self)
        if type(self) is DisplayCheckManagerWindow:
            agendar_maximizacao_workspace_f3(self)

    DisplayCheckManagerWindow.__init__ = manager_init

    # O editor pede maximização durante __init__. Apenas agendamos para after_idle,
    # quando a camada de debounce do canvas já estará instalada.
    def maximize_editor(self):
        reservar_area_inferior_workspace_f3(
            getattr(self, "window", None),
            getattr(self, "status", None),
        )
        agendar_maximizacao_workspace_f3(self)

    DisplayCheckMaskEditorWindow._maximize = maximize_editor
    DisplayMaskEditorWindow._maximize = maximize_editor

    _instalar_redraw_configuracao_debounced(DisplayCheckMaskEditorWindow)
    _instalar_redraw_configuracao_debounced(DisplayMaskEditorWindow)

    # Referências ACESO/APAGADO/POUCA LUZ.
    original_reference_init = DisplayReferenceConfigWindow.__init__

    def reference_init(self, *args, **kwargs):
        original_reference_init(self, *args, **kwargs)
        try:
            self.grid.pack_configure(fill="both", expand=True, padx=28, pady=(0, 14))
        except Exception:
            pass
        footer = getattr(getattr(self, "learning_status", None), "master", None)
        reservar_area_inferior_workspace_f3(
            getattr(self, "window", None),
            footer,
        )
        agendar_maximizacao_workspace_f3(self)

    DisplayReferenceConfigWindow.__init__ = reference_init

    # ROI das referências físicas / CHECK permanece modal, mas maximizada uma vez.
    original_roi_init = DisplayReferenceRoiDialog.__init__

    def roi_init(self, *args, **kwargs):
        original_roi_init(self, *args, **kwargs)
        reservar_area_inferior_workspace_f3(getattr(self, "window", None))
        agendar_maximizacao_workspace_f3(self)

    DisplayReferenceRoiDialog.__init__ = roi_init

    _instalar_subclasses_finais()

    for cls in (
        DisplayProjectConfigWindow,
        DisplayCheckManagerWindow,
        DisplayCheckMaskEditorWindow,
        DisplayMaskEditorWindow,
        DisplayReferenceConfigWindow,
        DisplayReferenceRoiDialog,
    ):
        cls._display_f3_workspace_ui_installed = True

    _INSTALLED = True
