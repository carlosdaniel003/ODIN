from __future__ import annotations

"""Overlay imediato e loop responsivo da Produção Display F3.

As máscaras já salvas no projeto são carregadas quando o F3 abre ou muda de
CHECK. O repaint da câmera não espera a análise óptica terminar. A análise é
agendada depois do frame visual, dando ao Tk/Windows oportunidade de pintar a
janela antes do trabalho de visão.
"""

import src.platform.display_f3_live_runtime_fix as live_runtime
import src.platform.display_f3_mask_status as mask_status
import src.platform.display_live_roi_overlay as overlay
from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
from src.platform.display_production_f3 import DisplayProductionF3Mixin
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_RESPONSIVE_PREVIEW_INTERVAL_MS = 80
F3_ANALYSIS_AFTER_PAINT_MS = 20


def _matches(analysis, project_name: str, check_id: str) -> bool:
    return bool(
        isinstance(analysis, dict)
        and str(analysis.get("project_name") or "") == project_name
        and str(analysis.get("check_id") or "") == check_id
    )


def _clear_geometry(app) -> None:
    window = getattr(app, "display_f3_window", None)
    if window is None:
        return
    window._display_roi_overlay_loaded_key = None
    window._display_roi_overlay_resolution = None
    window._display_roi_overlay_masks = ()


def _prepare_geometry(app, visual_rotation: int | None = None):
    """Replica as máscaras persistidas no preview sem executar visão/comparação."""
    window = getattr(app, "display_f3_window", None)
    repository = getattr(app, "display_project_repository", None)
    if window is None or repository is None:
        return None

    # Guarda uma referência direta ao app. O overlay não precisa depender do
    # callback CONFIGURAR para reencontrar o runtime em todo frame.
    window._display_f3_app = app

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        return None
    check_id = overlay._current_check_id(app)
    if not project_name or not check_id:
        _clear_geometry(app)
        return None

    if visual_rotation is None:
        try:
            visual_rotation = int(app._obter_rotacao_visual_display_f3())
        except Exception:
            visual_rotation = 0
    rotation = int(visual_rotation or 0) % 360
    if rotation not in (0, 90, 180, 270):
        rotation = 0

    loaded_key = (project_name, check_id, rotation)
    if loaded_key == getattr(window, "_display_roi_overlay_loaded_key", None):
        return {
            "resolution": getattr(window, "_display_roi_overlay_resolution", None),
            "masks": getattr(window, "_display_roi_overlay_masks", ()),
        }

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        _clear_geometry(app)
        return None

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    checks = project.get("checks", []) or []
    check = next(
        (
            item
            for item in checks
            if isinstance(item, dict)
            and str(item.get("id") or "") == check_id
        ),
        None,
    )
    if resolution is None or not isinstance(check, dict):
        _clear_geometry(app)
        return None

    states = (
        check.get("mask_states", {})
        if isinstance(check.get("mask_states"), dict)
        else {}
    )
    # Não recalcula nem reinterpreta geometria. Usa diretamente as máscaras já
    # persistidas; preparar_check_visual_display só aplica a rotação visual.
    masks = [
        item
        for item in (project.get("masks", []) or [])
        if isinstance(item, dict)
        and states.get(str(item.get("id") or ""))
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    ]

    try:
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            masks,
            rotation,
        )
    except Exception:
        _clear_geometry(app)
        return None

    window._display_roi_overlay_loaded_key = loaded_key
    # Compatibilidade com o overlay histórico.
    window._display_roi_overlay_cache_key = loaded_key
    window._display_roi_overlay_resolution = tuple(visual_resolution)
    window._display_roi_overlay_masks = tuple(visual_masks)
    return {
        "resolution": tuple(visual_resolution),
        "masks": tuple(visual_masks),
    }


def _context(window, visual_rotation: int):
    app = getattr(window, "_display_f3_app", None)
    if app is None:
        app = overlay._app_from_window(window)

    # Mesmo sem reencontrar o app, se a geometria já foi pré-carregada durante
    # a abertura do F3 ela deve ser desenhada imediatamente em estado neutro.
    if app is None:
        masks = getattr(window, "_display_roi_overlay_masks", ())
        resolution = getattr(window, "_display_roi_overlay_resolution", None)
        if masks and resolution is not None:
            return {
                "resolution": resolution,
                "masks": masks,
                "classifications": {},
            }
        return None

    try:
        project_name = str(app.display_project_repository.obter_projeto_ativo() or "")
    except Exception:
        project_name = ""
    check_id = overlay._current_check_id(app)
    if not project_name or not check_id:
        return None

    expected_key = (project_name, check_id, int(visual_rotation or 0) % 360)
    if expected_key != getattr(window, "_display_roi_overlay_loaded_key", None):
        _prepare_geometry(app, visual_rotation)

    masks = getattr(window, "_display_roi_overlay_masks", ())
    resolution = getattr(window, "_display_roi_overlay_resolution", None)
    if not masks or resolution is None:
        return None

    analysis = getattr(app, "_display_auto_last_analysis", None)
    classifications = {}
    if _matches(analysis, project_name, check_id):
        for item in analysis.get("mask_results", []) or []:
            if isinstance(item, dict) and item.get("mask_id"):
                classifications[str(item["mask_id"])] = str(
                    item.get("classified") or "unknown"
                )

    return {
        "resolution": resolution,
        "masks": masks,
        "classifications": classifications,
    }


def _no_extra_analysis(app):
    """Overlay/status nunca executam uma segunda análise só para desenhar."""
    try:
        context = app._display_auto_current_context()
    except Exception:
        return None
    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not isinstance(context, dict):
        return None
    if _matches(
        analysis,
        str(context.get("project_name") or ""),
        str(context.get("check_id") or ""),
    ):
        return analysis
    return None


def _install_eager_geometry() -> None:
    cls = DisplayProductionF3Mixin
    if bool(getattr(cls, "_display_f3_eager_mask_geometry_installed", False)):
        return

    original_activate = cls._ativar_tela_producao_display_f3
    original_render_flow = cls._renderizar_fluxo_checks_display_f3
    original_summary = cls._atualizar_resumo_projeto_display_f3
    original_close = cls.fechar_tela_producao_display_f3

    def activate(self):
        result = original_activate(self)
        _prepare_geometry(self)
        return result

    def render_flow(self):
        result = original_render_flow(self)
        _prepare_geometry(self)
        return result

    def summary(self):
        _clear_geometry(self)
        result = original_summary(self)
        if bool(getattr(self, "display_f3_ativo", False)):
            _prepare_geometry(self)
        return result

    def close(self):
        analysis_after_id = getattr(self, "_display_f3_analysis_after_id", None)
        if analysis_after_id is not None:
            try:
                self.root.after_cancel(analysis_after_id)
            except Exception:
                pass
        self._display_f3_analysis_after_id = None
        _clear_geometry(self)
        return original_close(self)

    cls._ativar_tela_producao_display_f3 = activate
    cls._renderizar_fluxo_checks_display_f3 = render_flow
    cls._atualizar_resumo_projeto_display_f3 = summary
    cls.fechar_tela_producao_display_f3 = close
    cls._display_f3_eager_mask_geometry_installed = True


def _install_analysis_after_paint() -> None:
    """Renderiza primeiro; só depois executa o processamento óptico do CHECK."""
    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_analysis_after_paint_installed", False)):
        return

    cls.DISPLAY_F3_PREVIEW_INTERVAL_MS = F3_RESPONSIVE_PREVIEW_INTERVAL_MS

    def run_analysis(self):
        self._display_f3_analysis_after_id = None
        if not bool(getattr(self, "display_f3_ativo", False)):
            return
        try:
            self._process_display_auto_check()
        except Exception:
            # O preview deve continuar vivo mesmo se alguma camada diagnóstica
            # apresentar erro. Erros funcionais continuam visíveis pelos status.
            pass

    def update_preview(self):
        # Chama diretamente o próximo item do MRO para evitar o método antigo,
        # que desenhava e analisava no mesmo callback síncrono.
        DisplayProductionF3Mixin._atualizar_preview_display_f3(self)
        if not bool(getattr(self, "display_f3_ativo", False)):
            return
        if getattr(self, "_display_f3_analysis_after_id", None) is not None:
            return
        try:
            self._display_f3_analysis_after_id = self.root.after(
                F3_ANALYSIS_AFTER_PAINT_MS,
                lambda owner=self: run_analysis(owner),
            )
        except Exception:
            self._display_f3_analysis_after_id = None

    cls._atualizar_preview_display_f3 = update_preview
    cls._display_f3_analysis_after_paint_installed = True


def instalar_overlay_imediato_display_f3() -> None:
    overlay._overlay_context = _context
    live_runtime.atualizar_classificacao_overlay_f3 = _no_extra_analysis
    mask_status.atualizar_classificacao_overlay_f3 = _no_extra_analysis
    _install_eager_geometry()
    _install_analysis_after_paint()
