TAG_LUPA = "lupa_canvas"


def limpar_lupa_canvas(self, evento=None) -> None:
    """
    Remove a lupa quando o mouse sai da imagem ou do Canvas.

    A limpeza não depende de _lupa_visivel, pois o estado pode ficar
    dessincronizado durante a atualização contínua da câmera.
    """
    if hasattr(self, "canvas") and self.canvas is not None:
        self.canvas.delete(TAG_LUPA)

    self.lupa_tk = None
    self._lupa_visivel = False
    self._lupa_ultima_posicao_canvas = None
    self._lupa_ultimo_tempo_s = 0.0