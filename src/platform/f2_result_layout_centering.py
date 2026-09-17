from __future__ import annotations


_INSTALADO = False


def instalar_layout_resultado_f2_centralizado() -> None:
    """Centraliza de verdade o pós-análise somente na Produção F2.

    O snapshot e os textos deixam de disputar duas metades horizontais do painel.
    O resultado passa a ser um único bloco vertical: preview centralizada, aviso
    centralizado e detalhe OK/NG centralizado, todos usando a largura útil inteira.
    """
    global _INSTALADO
    if _INSTALADO:
        return

    from src.platform.segment_display_operation_window import (
        F2_ANALYZED_WAITING_TEXT,
        SegmentDisplayOperationWindow,
        tamanho_fonte_status_analisado_f2,
    )

    original_layout = SegmentDisplayOperationWindow._set_result_snapshot_layout
    original_resize = SegmentDisplayOperationWindow._on_analysis_resize

    def _set_result_snapshot_layout_centralizado(self, visible: bool) -> None:
        if not visible:
            original_layout(self, False)
            try:
                self.status_frame.grid_columnconfigure(0, weight=1, uniform="")
                self.status_frame.grid_columnconfigure(1, weight=0, uniform="")
                self.status_frame.grid_rowconfigure(0, weight=1)
                self.status_frame.grid_rowconfigure(1, weight=0)
                self.status_frame.grid_rowconfigure(2, weight=0)
                self.status_frame.grid_rowconfigure(3, weight=0)
                self.status_frame.grid_rowconfigure(4, weight=0)
            except Exception:
                pass
            return

        self._result_snapshot_visible = True

        # Um único eixo central. As linhas 0 e 4 são espaçadores equivalentes;
        # preview, status e detalhe ficam empilhados entre elas.
        self.status_frame.grid_columnconfigure(0, weight=1, uniform="")
        self.status_frame.grid_columnconfigure(1, weight=0, uniform="")
        self.status_frame.grid_rowconfigure(0, weight=1)
        self.status_frame.grid_rowconfigure(1, weight=0)
        self.status_frame.grid_rowconfigure(2, weight=0)
        self.status_frame.grid_rowconfigure(3, weight=0)
        self.status_frame.grid_rowconfigure(4, weight=1)

        self.result_snapshot_panel.grid(
            row=1,
            column=0,
            rowspan=1,
            sticky="",
            padx=0,
            pady=(4, 10),
        )
        self.status_label.grid_configure(
            row=2,
            column=0,
            sticky="ew",
            padx=16,
            pady=(2, 4),
        )
        self.detail_label.grid_configure(
            row=3,
            column=0,
            sticky="ew",
            padx=16,
            pady=(4, 2),
        )

        try:
            self.status_label.configure(
                anchor="center",
                justify="center",
                wraplength=0,
            )
            self.detail_label.configure(
                anchor="center",
                justify="center",
            )
        except Exception:
            pass

    def _aplicar_status_pos_analise_f2_centralizado(
        self,
        panel_width: int | None = None,
    ) -> None:
        if panel_width is None:
            try:
                panel_width = int(self.analysis_panel.winfo_width())
            except Exception:
                panel_width = 640
        if int(panel_width or 0) <= 2:
            panel_width = 640

        # A preview agora está acima do texto; portanto o aviso usa a largura
        # inteira do painel em vez da antiga largura da coluna direita.
        font_size = tamanho_fonte_status_analisado_f2(int(panel_width))
        self.status_label.configure(
            text=F2_ANALYZED_WAITING_TEXT,
            font=("DejaVu Sans", font_size, "bold"),
            height=2,
            pady=0,
            justify="center",
            anchor="center",
            wraplength=0,
        )

    def _on_analysis_resize_centralizado(self, event) -> None:
        # Preserva todos os comportamentos existentes e, no final, corrige os
        # cálculos que antes ainda reservavam metade da largura para a preview.
        original_resize(self, event)
        try:
            width = int(event.width)
        except (TypeError, ValueError, AttributeError):
            width = 640
        if width <= 2:
            width = 640

        if bool(getattr(self, "_result_snapshot_visible", False)):
            try:
                self.detail_label.configure(
                    wraplength=max(220, width - 96),
                    anchor="center",
                    justify="center",
                )
            except Exception:
                pass
            try:
                self._on_result_snapshot_resize()
            except Exception:
                pass

        if bool(getattr(self, "_f2_analyzed_waiting_active", False)):
            _aplicar_status_pos_analise_f2_centralizado(self, width)

    SegmentDisplayOperationWindow._set_result_snapshot_layout = (
        _set_result_snapshot_layout_centralizado
    )
    SegmentDisplayOperationWindow._aplicar_status_pos_analise_f2 = (
        _aplicar_status_pos_analise_f2_centralizado
    )
    SegmentDisplayOperationWindow._on_analysis_resize = (
        _on_analysis_resize_centralizado
    )
    _INSTALADO = True
