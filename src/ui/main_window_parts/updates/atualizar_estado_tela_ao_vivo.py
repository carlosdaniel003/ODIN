def atualizar_estado_tela_ao_vivo(self, ativa: bool) -> None:
    self.tela_ao_vivo_ativa = bool(ativa)

    if not hasattr(self, "botao_tela_ao_vivo"):
        return

    if self.botao_tela_ao_vivo is None:
        return

    if ativa:
        self.botao_tela_ao_vivo.config(
            text="Parar câmera",
            bg="#3F1D1D",
            fg="#FECACA",
            activebackground="#7F1D1D",
        )
    else:
        self.botao_tela_ao_vivo.config(
            text="Tela ao vivo",
            bg="#0F3D24",
            fg="#BBF7D0",
            activebackground="#14532D",
        )