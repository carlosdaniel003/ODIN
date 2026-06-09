def atualizar_estado_relogio(self) -> None:
    if self.relogio_visivel:
        self.label_meta_data.config(text=self.obter_data_hora())

        if self.botao_toggle_relogio is not None:
            self.botao_toggle_relogio.config(
                text="Hora ON",
                bg="#0F3D24",
                fg="#BBF7D0",
                activebackground="#14532D",
                activeforeground=self.COR_TEXTO,
            )
        return

    self.label_meta_data.config(text="--")

    if self.botao_toggle_relogio is not None:
        self.botao_toggle_relogio.config(
            text="Hora OFF",
            bg="#111827",
            fg="#94A3B8",
            activebackground="#1F2937",
            activeforeground=self.COR_TEXTO,
        )