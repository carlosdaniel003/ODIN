from __future__ import annotations

"""Reaplica o overlay das máscaras F2 depois que a janela de Configurações estabiliza.

A composição de mixins do ODIN pode reconstruir a seção de referências depois do
primeiro render. Este patch atua no ponto mais externo do fluxo de abertura da
janela e reaplica o overlay após o ciclo atual do Tk, sem tocar no runtime
produtivo do F2 nem no F3.
"""

from src.platform.f2_automatic_cycle_guard import F2AutomaticCycleGuardMixin
from src.platform.f2_board_presence_mask_preview import _aplicar_mascaras_nas_previews


_PATCH_INSTALADO = False


def _reaplicar_overlay_f2(app, window) -> None:
    if window is None:
        return
    try:
        if not bool(window.winfo_exists()):
            return
    except Exception:
        return

    controller = getattr(app, "_f2_board_presence_refs", None)
    if controller is None:
        return

    try:
        _aplicar_mascaras_nas_previews(controller, window)
        window._odin_f2_board_presence_mask_preview_last_error = None
    except Exception as exc:
        # Mantém telemetria local para não esconder novamente uma falha visual.
        try:
            window._odin_f2_board_presence_mask_preview_last_error = repr(exc)
        except Exception:
            pass


def _agendar_reaplicacao_f2(app, window) -> None:
    if window is None:
        return

    # Aplicação imediata e reaplicações após a composição final da janela.
    _reaplicar_overlay_f2(app, window)

    for atraso_ms in (0, 60, 180, 350):
        try:
            window.after(
                atraso_ms,
                lambda a=app, w=window: _reaplicar_overlay_f2(a, w),
            )
        except Exception:
            pass


def instalar_reaplicacao_tardia_mascaras_previews_f2() -> None:
    """Envolve a abertura real das Configurações, não apenas o render do card."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    current = F2AutomaticCycleGuardMixin.abrir_configuracoes
    if bool(getattr(current, "_odin_f2_mask_preview_late_fix", False)):
        _PATCH_INSTALADO = True
        return

    previous = current

    def abrir_configuracoes_com_overlay_final(self):
        result = previous(self)

        finder = getattr(self, "_encontrar_janela_configuracoes_aberta", None)
        window = None
        if callable(finder):
            try:
                window = finder()
            except Exception:
                window = None

        _agendar_reaplicacao_f2(self, window)
        return result

    abrir_configuracoes_com_overlay_final._odin_f2_mask_preview_late_fix = True
    abrir_configuracoes_com_overlay_final._odin_f2_mask_preview_late_fix_base = previous
    F2AutomaticCycleGuardMixin.abrir_configuracoes = abrir_configuracoes_com_overlay_final
    _PATCH_INSTALADO = True
