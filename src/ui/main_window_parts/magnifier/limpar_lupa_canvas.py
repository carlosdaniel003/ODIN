TAG_LUPA = "lupa_canvas"


def limpar_lupa_canvas(self, evento=None) -> None:
    if not getattr(self, "_lupa_visivel", False):
        return

    if hasattr(self, "canvas") and self.canvas is not None:
        self.canvas.delete(TAG_LUPA)

    self.lupa_tk = None
    self._lupa_visivel = False
    self._lupa_ultima_posicao_canvas = None
    self._lupa_ultimo_tempo_s = 0.0
