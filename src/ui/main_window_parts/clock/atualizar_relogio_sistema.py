def atualizar_relogio_sistema(self) -> None:
    if self.relogio_visivel:
        self.label_meta_data.config(text=self.obter_data_hora())

    self._atualizacao_relogio_pendente = self.root.after(
        1000,
        self.atualizar_relogio_sistema,
    )