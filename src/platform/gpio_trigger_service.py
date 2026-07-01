from __future__ import annotations

from collections.abc import Callable


class GPIOTriggerService:
    """Gatilho digital event-driven para microswitch no Raspberry Pi."""

    def __init__(
        self,
        bcm_pin: int,
        bounce_time_s: float,
        on_pressed: Callable[[], None],
        on_released: Callable[[], None],
    ) -> None:
        self.bcm_pin = int(bcm_pin)
        self.bounce_time_s = max(0.0, float(bounce_time_s))
        self.on_pressed = on_pressed
        self.on_released = on_released
        self._button = None
        self.available = False
        self.error_message = ""

    def start(self) -> bool:
        if self.available and self._button is not None:
            return True

        try:
            from gpiozero import Button

            self._button = Button(
                self.bcm_pin,
                pull_up=True,
                bounce_time=self.bounce_time_s,
            )
            self._button.when_pressed = self.on_pressed
            self._button.when_released = self.on_released
            self.available = True
            self.error_message = ""
            return True
        except Exception as error:
            self._button = None
            self.available = False
            self.error_message = (
                f"{type(error).__name__}: {error}"
            )
            return False

    @property
    def is_pressed(self) -> bool:
        if not self.available or self._button is None:
            return False
        try:
            return bool(self._button.is_pressed)
        except Exception:
            return False

    def close(self) -> None:
        button = self._button
        self._button = None
        self.available = False

        if button is None:
            return

        try:
            button.when_pressed = None
            button.when_released = None
            button.close()
        except Exception:
            pass
