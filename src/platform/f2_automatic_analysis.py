from __future__ import annotations

import json
import time
import tkinter as tk

from src.core.segment_low_light import (
    STATUS_ACESO,
    STATUS_APAGADO,
)


F2_AUTO_SETTING_KEY = "f2_auto_analysis_enabled"
F2_AUTO_ANALYSIS_INTERVAL_S = 0.10
F2_AUTO_REARM_OFF_FRAMES = 2


class F2AutomaticTriggerLatch:
    """Dispara uma vez e só rearma quando todas as ROIs voltam a apagar."""

    def __init__(self, off_frames_required: int = F2_AUTO_REARM_OFF_FRAMES) -> None:
        self.off_frames_required = max(1, int(off_frames_required))
        self.armed = True
        self.off_frames = 0

    def reset(self, armed: bool = True) -> None:
        self.armed = bool(armed)
        self.off_frames = 0

    def disarm(self) -> None:
        self.armed = False
        self.off_frames = 0

    @staticmethod
    def _has_light(states: dict[str, str]) -> bool:
        return any(
            str(status).upper() == STATUS_ACESO
            for status in states.values()
        )

    @staticmethod
    def _all_off(states: dict[str, str]) -> bool:
        return bool(states) and all(
            str(status).upper() == STATUS_APAGADO
            for status in states.values()
        )

    def observe(self, states: dict[str, str], can_trigger: bool = True) -> bool:
        states = dict(states or {})

        if self.armed:
            self.off_frames = 0
            if can_trigger and self._has_light(states):
                self.disarm()
                return True
            return False

        if self._all_off(states):
            self.off_frames += 1
            if self.off_frames >= self.off_frames_required:
                self.reset(armed=True)
        else:
            self.off_frames = 0
        return False


def estados_resultado_operacao(resultado) -> dict[str, str]:
    states: dict[str, str] = {}
    for item in tuple(getattr(resultado, "results", ()) or ()):
        led_id = str(getattr(item, "id", "")).strip()
        if not led_id:
            continue
        states[led_id] = str(getattr(item, "status", "")).strip().upper()
    return states


def carregar_analise_automatica_f2(repository) -> bool:
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        return False
    settings = config.get("settings", {}) if isinstance(config, dict) else {}
    if not isinstance(settings, dict):
        return False
    return bool(settings.get(F2_AUTO_SETTING_KEY, False))


def salvar_analise_automatica_f2(repository, enabled: bool) -> bool:
    """Persiste somente a flag F2 sem reescrever outras regras de configuração."""
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
        if not isinstance(config, dict):
            config = {}
        settings = config.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings[F2_AUTO_SETTING_KEY] = bool(enabled)
        config["settings"] = settings

        path = repository.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def _walk_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk_widgets(child)


def _find_settings_window(root):
    candidates = []
    for widget in root.winfo_children():
        if not isinstance(widget, tk.Toplevel):
            continue
        try:
            if widget.winfo_exists() and "Configurações" in str(widget.title()):
                candidates.append(widget)
        except Exception:
            continue
    return candidates[-1] if candidates else None


def _find_system_content(settings_window):
    """Localiza o container da aba Sistema sem depender da ordem dos widgets."""
    for widget in _walk_widgets(settings_window):
        if not isinstance(widget, tk.Label):
            continue
        try:
            if str(widget.cget("text")) != "Armazenamento":
                continue
            card = widget.master
            return getattr(card, "master", None)
        except Exception:
            continue
    return None


def _add_auto_analysis_setting(app, settings_window) -> None:
    content = _find_system_content(settings_window)
    if content is None:
        return
    if getattr(settings_window, "_odin_f2_auto_setting_added", False):
        return

    view = app.view
    card = tk.Frame(
        content,
        bg=view.COR_CARD_2,
        highlightthickness=1,
        highlightbackground=view.COR_BORDA,
    )
    card.pack(fill=tk.X, padx=(0, 8), pady=(0, 14))
    tk.Frame(card, bg="#22C55E", height=3).pack(fill=tk.X)
    tk.Label(
        card,
        text="Produção F2",
        font=("Segoe UI", 11, "bold"),
        fg=view.COR_TEXTO,
        bg=view.COR_CARD_2,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(12, 6))
    tk.Frame(card, bg="#172033", height=1).pack(
        fill=tk.X,
        padx=14,
        pady=(0, 10),
    )
    tk.Label(
        card,
        text=(
            "Quando ativado, o modo Produção F2 monitora as ROIs em tempo real "
            "e inicia a inspeção automaticamente ao detectar ao menos um LED ACESO. "
            "Desativado, Enter/GPIO e o comportamento atual permanecem inalterados."
        ),
        font=("Segoe UI", 9),
        fg=view.COR_TEXTO_2,
        bg=view.COR_CARD_2,
        wraplength=650,
        justify=tk.LEFT,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(0, 8))
    tk.Checkbutton(
        card,
        text="Ativar análise automática",
        variable=app._f2_auto_settings_var,
        font=("Segoe UI", 10, "bold"),
        fg=view.COR_TEXTO,
        bg=view.COR_CARD_2,
        activebackground=view.COR_CARD_2,
        activeforeground=view.COR_TEXTO,
        selectcolor=view.COR_CARD,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(0, 5))
    tk.Label(
        card,
        text=(
            "Overlay automático: verde = ACESO • vermelho = APAGADO • "
            "amarelo = POUCA LUZ. A mesma configuração não altera o F3."
        ),
        font=("Segoe UI", 8),
        fg=view.COR_TEXTO_3,
        bg=view.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
    ).pack(fill=tk.X, padx=14, pady=(0, 12))

    settings_window._odin_f2_auto_setting_added = True
    try:
        settings_window.update_idletasks()
    except Exception:
        pass


class F2AutomaticAnalysisMixin:
    """Monitoramento opt-in exclusivo da Produção F2."""

    def __init__(self, *args, **kwargs) -> None:
        self.analise_automatica_f2 = False
        self._f2_auto_settings_var = None
        self._f2_auto_latch = F2AutomaticTriggerLatch()
        self._f2_auto_last_analysis_s = 0.0
        self._f2_auto_last_frame_id = None
        self._f2_auto_last_states: dict[str, str] = {}
        super().__init__(*args, **kwargs)
        self.analise_automatica_f2 = carregar_analise_automatica_f2(
            getattr(self, "config_repository", None)
        )

    def _f2_auto_enabled(self) -> bool:
        return bool(getattr(self, "analise_automatica_f2", False))

    def _f2_auto_reset_runtime(self) -> None:
        self._f2_auto_latch.reset(armed=True)
        self._f2_auto_last_analysis_s = 0.0
        self._f2_auto_last_frame_id = None
        self._f2_auto_last_states = {}

    def _f2_auto_apply_window_mode(self) -> None:
        window = getattr(self, "operacao_window", None)
        setter = getattr(window, "set_live_roi_states", None)
        if not callable(setter):
            return
        enabled = self._f2_auto_enabled() and bool(
            getattr(self, "operacao_ativa", False)
        )
        setter(
            self._f2_auto_last_states if enabled else {},
            enabled=enabled,
        )

    def abrir_configuracoes(self) -> None:
        self._f2_auto_settings_var = tk.BooleanVar(
            master=self.root,
            value=self._f2_auto_enabled(),
        )
        result = super().abrir_configuracoes()
        window = _find_settings_window(self.root)
        if window is not None:
            _add_auto_analysis_setting(self, window)
        return result

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_configurado_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ) -> None:
        enabled = self._f2_auto_enabled()
        variable = getattr(self, "_f2_auto_settings_var", None)
        if variable is not None:
            try:
                enabled = bool(variable.get())
            except Exception:
                pass

        result = super().salvar_configuracoes_sistema(
            salvar_resultados_analise,
            raio_configurado_px,
            configuracoes_camera,
        )
        self.analise_automatica_f2 = bool(enabled)
        salvar_analise_automatica_f2(
            getattr(self, "config_repository", None),
            self.analise_automatica_f2,
        )
        self._f2_auto_reset_runtime()
        self._f2_auto_apply_window_mode()
        return result

    def abrir_tela_operacao(self) -> None:
        self._f2_auto_reset_runtime()
        result = super().abrir_tela_operacao()
        self._f2_auto_apply_window_mode()
        return result

    def fechar_tela_operacao(self) -> None:
        window = getattr(self, "operacao_window", None)
        setter = getattr(window, "set_live_roi_states", None)
        if callable(setter):
            setter({}, enabled=False)
        self._f2_auto_reset_runtime()
        return super().fechar_tela_operacao()

    def _f2_auto_fresh_analysis_due(self) -> bool:
        now = time.monotonic()
        if now - self._f2_auto_last_analysis_s < F2_AUTO_ANALYSIS_INTERVAL_S:
            return False

        frame_id = getattr(self, "camera_ultimo_frame_id", None)
        if frame_id is not None and frame_id == self._f2_auto_last_frame_id:
            return False

        self._f2_auto_last_analysis_s = now
        self._f2_auto_last_frame_id = frame_id
        return True

    def _f2_auto_can_trigger(self) -> bool:
        return bool(
            getattr(self, "operacao_ativa", False)
            and getattr(self, "operacao_engine", None) is not None
            and self.operacao_engine.ready
            and not getattr(self, "operacao_processando", False)
            and getattr(self, "_operacao_resultado_after_id", None) is None
            and not getattr(self, "_gpio_positioning", False)
            and not getattr(self, "_gpio_waiting_removal", False)
            and not getattr(self, "camera_desconectada", False)
            and getattr(self, "camera_frame_atual", None) is not None
        )

    def _f2_auto_analyze_current_frame(self) -> bool:
        if not self._f2_auto_enabled():
            return False
        engine = getattr(self, "operacao_engine", None)
        frame = getattr(self, "camera_frame_atual", None)
        if (
            engine is None
            or not engine.ready
            or frame is None
            or getattr(frame, "size", 0) == 0
            or getattr(self, "operacao_processando", False)
            or not self._f2_auto_fresh_analysis_due()
        ):
            return False

        try:
            result = engine.analyze(frame)
        except Exception:
            return False

        states = estados_resultado_operacao(result)
        self._f2_auto_last_states = states
        window = getattr(self, "operacao_window", None)
        setter = getattr(window, "set_live_roi_states", None)
        if callable(setter):
            setter(states, enabled=True)

        should_trigger = self._f2_auto_latch.observe(
            states,
            can_trigger=self._f2_auto_can_trigger(),
        )
        if not should_trigger:
            return False

        self.disparar_inspecao_operacao()
        return True

    def _atualizar_preview_operacao(self) -> None:
        """Mantém o preview legado; adiciona análise somente no opt-in F2."""
        self._operacao_preview_after_id = None
        if not getattr(self, "operacao_ativa", False):
            return

        if self._f2_auto_enabled():
            self._f2_auto_apply_window_mode()
            if self._f2_auto_analyze_current_frame():
                # O disparo oficial agenda o próximo preview e o retorno do
                # resultado; não crie um segundo timer no mesmo ciclo.
                return

        if getattr(self, "camera_desconectada", False):
            self.operacao_window.set_preview_status(
                "Última imagem • câmera desconectada",
                "#FCA5A5",
            )
        elif getattr(self, "operacao_processando", False):
            self.operacao_window.set_preview_paused(True)
        elif getattr(self, "camera_frame_atual", None) is not None:
            self.operacao_window.update_preview(
                self.camera_frame_atual,
                self.operacao_leds_preview,
            )

        self._agendar_preview_operacao()

    def disparar_inspecao_operacao(self) -> None:
        """Preserva o frame exato usado pelo motor para a preview do último resultado."""
        total_before = int(getattr(self, "operacao_total", 0) or 0)
        ok_before = int(getattr(self, "operacao_ok", 0) or 0)
        ng_before = int(getattr(self, "operacao_ng", 0) or 0)

        window = getattr(self, "operacao_window", None)
        preview_setter = getattr(window, "set_result_preview_frame", None)
        engine = getattr(self, "operacao_engine", None)
        original_analyze = getattr(engine, "analyze", None)
        captured: dict[str, object] = {}
        wrapped = False

        # Captura o próprio argumento entregue a OperationEngine.analyze(). Isso
        # garante que a miniatura não seja um frame posterior da câmera ao vivo.
        if callable(preview_setter) and callable(original_analyze):
            def analyze_with_result_frame(frame, *args, **kwargs):
                try:
                    captured["frame"] = frame.copy()
                except Exception:
                    captured["frame"] = None
                return original_analyze(frame, *args, **kwargs)

            try:
                engine.analyze = analyze_with_result_frame
                wrapped = True
            except Exception:
                wrapped = False

        try:
            result = super().disparar_inspecao_operacao()
        finally:
            if wrapped:
                try:
                    engine.analyze = original_analyze
                except Exception:
                    pass

        total_after = int(getattr(self, "operacao_total", 0) or 0)
        ok_after = int(getattr(self, "operacao_ok", 0) or 0)
        ng_after = int(getattr(self, "operacao_ng", 0) or 0)
        inspection_completed = total_after > total_before

        if inspection_completed and callable(preview_setter):
            result_frame = captured.get("frame")
            if result_frame is not None and getattr(result_frame, "size", 0) > 0:
                is_ok = None
                if ok_after > ok_before:
                    is_ok = True
                elif ng_after > ng_before:
                    is_ok = False
                else:
                    last_result = getattr(window, "_last_result_ok", None)
                    if last_result is not None:
                        is_ok = bool(last_result)

                if is_ok is not None:
                    try:
                        preview_setter(
                            result_frame,
                            is_ok=is_ok,
                            failed_led_ids=tuple(
                                getattr(window, "_failed_led_ids", ()) or ()
                            ),
                        )
                    except Exception:
                        # A miniatura é apenas apresentação e nunca pode afetar
                        # contadores, OK/NG ou o rearme produtivo do F2.
                        pass

        if self._f2_auto_enabled() and inspection_completed:
            # Também protege quando o operador usa Enter/GPIO com o automático
            # ativo: a mesma placa não pode ser inspecionada novamente.
            self._f2_auto_latch.disarm()
        return result
