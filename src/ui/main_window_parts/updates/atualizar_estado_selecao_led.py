import tkinter as tk


def atualizar_estado_selecao_led(self, selecao_ativa: bool) -> None:
        self.selecao_led_ativa = bool(selecao_ativa)

        if not hasattr(self, "botao_selecionar_leds") or self.botao_selecionar_leds is None:
            return

        if self.selecao_led_ativa:
            self.botao_selecionar_leds.config(
                text="Selecionando...",
                bg="#075985",
                fg="#E0F2FE",
                activebackground="#0369A1",
                activeforeground=self.COR_TEXTO,
                relief=tk.SOLID,
                bd=1,
            )

            if hasattr(self, "canvas"):
                self.canvas.config(
                    cursor="tcross",
                    highlightbackground=self.COR_AZUL,
                    highlightcolor=self.COR_AZUL,
                )

            return

        self.botao_selecionar_leds.config(
            text="Selecionar LEDs",
            bg="#0B1626",
            fg="#E5E7EB",
            activebackground="#122033",
            activeforeground=self.COR_TEXTO,
            relief=tk.FLAT,
            bd=0,
        )

        if hasattr(self, "canvas"):
            self.canvas.config(
                cursor="crosshair",
                highlightbackground=self.COR_BORDA,
                highlightcolor=self.COR_BORDA,
            )
