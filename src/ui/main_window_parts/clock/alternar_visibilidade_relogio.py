def alternar_visibilidade_relogio(self) -> None:
    self.relogio_visivel = not self.relogio_visivel
    self.atualizar_estado_relogio()