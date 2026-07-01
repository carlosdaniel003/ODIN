from __future__ import annotations

import tkinter as tk

from src.platform.gpio_trigger_service import GPIOTriggerService
from src.platform.raspberry_pi3_profile import RaspberryPi3ODINApp
from src.platform.raspberry_pi3_settings import (
    GPIO_POSITIONING_DELAY_MS,
    GPIO_TRIGGER_BCM_PIN,
    GPIO_TRIGGER_BOUNCE_S,
)


class GPIOEnabledRaspberryPi3ODINApp(RaspberryPi3ODINApp):
    """Adiciona gatilho por microswitch ao modo de operação."""

    def __init__(self, root: tk.Tk) -> None:
        self._gpio_positioning = False
        self._gpio_waiting_removal = False
        self._gpio_armed = False
        self._gpio_positioning_after_id = None
        self.gpio_trigger_service = None

        super().__init__(root)
        self._initialize_gpio_trigger()
        self.root.bind(
            "<Destroy>",
            self._on_root_destroy,
            add="+",
        )

    def _initialize_gpio_trigger(self) -> None:
        self.gpio_trigger_service = GPIOTriggerService(
            bcm_pin=GPIO_TRIGGER_BCM_PIN,
            bounce_time_s=GPIO_TRIGGER_BOUNCE_S,
            on_pressed=self._dispatch_gpio_pressed,
            on_released=self._dispatch_gpio_released,
        )
        started = self.gpio_trigger_service.start()
        self._gpio_armed = (
            started and not self.gpio_trigger_service.is_pressed
        )

        if not started:
            self.view.atualizar_status(
                "GPIO27 indisponível. ENTER continua disponível. "
                f"{self.gpio_trigger_service.error_message}"
            )

    def _dispatch_gpio_pressed(self) -> None:
        try:
            self.root.after(0, self._handle_gpio_pressed)
        except tk.TclError:
            pass

    def _dispatch_gpio_released(self) -> None:
        try:
            self.root.after(0, self._handle_gpio_released)
        except tk.TclError:
            pass

    def _handle_gpio_pressed(self) -> None:
        if (
            not self.operacao_ativa
            or not self.operacao_engine.ready
            or not self._gpio_armed
            or self._gpio_positioning
            or self._gpio_waiting_removal
            or self.operacao_processando
            or self._operacao_resultado_after_id is not None
        ):
            return

        self._gpio_armed = False
        self._gpio_positioning = True
        self.operacao_window.show_positioning(
            delay_seconds=GPIO_POSITIONING_DELAY_MS / 1000.0,
            total=self.operacao_total,
            ok_count=self.operacao_ok,
            ng_count=self.operacao_ng,
        )
        self._cancel_gpio_positioning_timer()
        self._gpio_positioning_after_id = self.root.after(
            GPIO_POSITIONING_DELAY_MS,
            self._confirm_gpio_positioning,
        )

    def _handle_gpio_released(self) -> None:
        if self._gpio_positioning:
            self._cancel_gpio_positioning_timer()
            self._gpio_positioning = False
            self._gpio_armed = True
            self._show_gpio_waiting_if_possible()
            return

        self._gpio_armed = True

        if self._gpio_waiting_removal:
            self._gpio_waiting_removal = False
            if self._operacao_resultado_after_id is None:
                self._show_gpio_waiting_if_possible()

    def _confirm_gpio_positioning(self) -> None:
        self._gpio_positioning_after_id = None

        if not self.operacao_ativa:
            self._gpio_positioning = False
            return

        service = self.gpio_trigger_service
        if (
            service is None
            or not service.available
            or not service.is_pressed
        ):
            self._gpio_positioning = False
            self._gpio_armed = True
            self._show_gpio_waiting_if_possible()
            return

        self._gpio_positioning = False
        super().disparar_inspecao_operacao()

    def _cancel_gpio_positioning_timer(self) -> None:
        if self._gpio_positioning_after_id is None:
            return
        try:
            self.root.after_cancel(
                self._gpio_positioning_after_id
            )
        except Exception:
            pass
        self._gpio_positioning_after_id = None

    def _show_gpio_waiting_if_possible(self) -> None:
        if (
            not self.operacao_ativa
            or not self.operacao_engine.ready
            or self.operacao_processando
            or self._operacao_resultado_after_id is not None
        ):
            return

        self.operacao_window.show_waiting(
            led_count=self.operacao_engine.led_count,
            total=self.operacao_total,
            ok_count=self.operacao_ok,
            ng_count=self.operacao_ng,
        )
        self.operacao_window.set_preview_paused(False)

    def abrir_tela_operacao(self) -> None:
        self._cancel_gpio_positioning_timer()
        self._gpio_positioning = False
        self._gpio_waiting_removal = False

        service = self.gpio_trigger_service
        self._gpio_armed = bool(
            service is not None
            and service.available
            and not service.is_pressed
        )
        super().abrir_tela_operacao()

    def fechar_tela_operacao(self) -> None:
        self._cancel_gpio_positioning_timer()
        self._gpio_positioning = False
        self._gpio_waiting_removal = False
        super().fechar_tela_operacao()

    def preparar_tela_operacao(self) -> None:
        super().preparar_tela_operacao()

        if not self.operacao_ativa or not self.operacao_engine.ready:
            return

        service = self.gpio_trigger_service
        if (
            service is not None
            and service.available
            and service.is_pressed
        ):
            self._gpio_armed = False
            self._gpio_waiting_removal = True
            self.operacao_window.show_waiting_removal(
                total=self.operacao_total,
                ok_count=self.operacao_ok,
                ng_count=self.operacao_ng,
            )
        else:
            self._gpio_armed = bool(
                service is not None and service.available
            )
            self._gpio_waiting_removal = False

    def disparar_inspecao_operacao(self) -> None:
        if self._gpio_positioning or self._gpio_waiting_removal:
            return
        super().disparar_inspecao_operacao()

    def _retornar_aguardando_operacao(self) -> None:
        service = self.gpio_trigger_service
        switch_pressed = bool(
            service is not None
            and service.available
            and service.is_pressed
        )

        if switch_pressed:
            self._operacao_resultado_after_id = None
            if not self.operacao_ativa:
                return
            if self.camera_desconectada or self.camera_frame_atual is None:
                self.operacao_window.show_error(
                    "CÂMERA DESCONECTADA",
                    total=self.operacao_total,
                    ok_count=self.operacao_ok,
                    ng_count=self.operacao_ng,
                )
                return

            self._gpio_armed = False
            self._gpio_waiting_removal = True
            self.operacao_window.show_waiting_removal(
                total=self.operacao_total,
                ok_count=self.operacao_ok,
                ng_count=self.operacao_ng,
            )
            self.operacao_window.set_preview_paused(False)
            return

        self._gpio_armed = bool(
            service is not None and service.available
        )
        self._gpio_waiting_removal = False
        super()._retornar_aguardando_operacao()

    def _mostrar_erro_operacao(self, mensagem: str) -> None:
        self._cancel_gpio_positioning_timer()
        self._gpio_positioning = False
        super()._mostrar_erro_operacao(mensagem)

    def _on_root_destroy(self, event) -> None:
        if event.widget is not self.root:
            return
        service = self.gpio_trigger_service
        if service is not None:
            service.close()
