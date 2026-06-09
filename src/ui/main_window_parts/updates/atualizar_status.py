def atualizar_status(self, texto: str) -> None:
    self.label_meta_status.config(text=texto)

    if self.relogio_visivel:
        self.label_meta_data.config(text=self.obter_data_hora())
    else:
        self.label_meta_data.config(text="--")