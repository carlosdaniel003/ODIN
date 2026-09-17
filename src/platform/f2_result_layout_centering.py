from __future__ import annotations


_INSTALADO = False


def instalar_layout_resultado_f2_centralizado() -> None:
    """Centraliza snapshot e textos do pós-análise somente na Produção F2.

    O snapshot ocupa a coluna esquerda e o bloco de mensagens fica agrupado
    verticalmente na coluna direita. Assim o aviso de placa já analisada e o
    detalhamento OK/NG deixam de ficar separados nas extremidades do painel.
    """
    global _INSTALADO
    if _INSTALADO:
        return

    from src.platform.segment_display_operation_window import (
        SegmentDisplayOperationWindow,
    )

    original = SegmentDisplayOperationWindow._set_result_snapshot_layout

    def _set_result_snapshot_layout_centralizado(self, visible: bool) -> None:
        if not visible:
            original(self, False)
            try:
                self.status_frame.grid_rowconfigure(0, weight=1)
                self.status_frame.grid_rowconfigure(1, weight=0)
                self.status_frame.grid_rowconfigure(2, weight=0)
                self.status_frame.grid_rowconfigure(3, weight=0)
            except Exception:
                pass
            return

        self._result_snapshot_visible = True

        # Duas colunas: snapshot à esquerda e mensagens à direita. As linhas
        # externas funcionam como espaçadores simétricos para manter status e
        # detalhe como um único bloco visual centralizado verticalmente.
        self.status_frame.grid_columnconfigure(0, weight=0, uniform="")
        self.status_frame.grid_columnconfigure(1, weight=1, uniform="")
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_rowconfigure(1, weight=0)
        self.status_frame.grid_rowconfigure(2, weight=0)
        self.status_frame.grid_rowconfigure(3, weight=1)

        self.result_snapshot_panel.grid(
            row=0,
            column=0,
            rowspan=4,
            sticky="w",
            padx=(0, 16),
            pady=4,
        )
        self.status_label.grid_configure(
            row=1,
            column=1,
            sticky="ew",
            padx=12,
            pady=(0, 6),
        )
        self.detail_label.grid_configure(
            row=2,
            column=1,
            sticky="ew",
            padx=12,
            pady=(6, 0),
        )

        try:
            self.status_label.configure(anchor="center", justify="center")
            self.detail_label.configure(anchor="center", justify="center")
        except Exception:
            pass

    SegmentDisplayOperationWindow._set_result_snapshot_layout = (
        _set_result_snapshot_layout_centralizado
    )
    _INSTALADO = True
