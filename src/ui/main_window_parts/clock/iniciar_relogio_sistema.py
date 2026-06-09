def iniciar_relogio_sistema(self) -> None:
    if self._atualizacao_relogio_pendente is not None:
        self.root.after_cancel(self._atualizacao_relogio_pendente)
        self._atualizacao_relogio_pendente = None

    self.atualizar_estado_relogio()
    self.atualizar_relogio_sistema()