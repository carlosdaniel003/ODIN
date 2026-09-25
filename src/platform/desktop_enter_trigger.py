from __future__ import annotations

import tkinter as tk


ENTER_REARM_DELAY_MS = 120


class DesktopEnterTriggerMixin:
    """Despacha ENTER para parametrização ou Produção F2 no desktop."""

    def __init__(self, root: tk.Tk) -> None:
        self._enter_instantaneo_armado = True
        self._enter_rearme_after_id = None
        super().__init__(root)
        self._instalar_atalho_enter_instantaneo()
        self.root.bind(
            "<Destroy>",
            self._ao_destruir_atalho_enter,
            add="+",
        )

    def _instalar_atalho_enter_instantaneo(self) -> None:
        # Substitui o atalho genérico por um despachante dependente da tela atual.
        for sequencia in ("<Return>", "<KP_Enter>"):
            self.root.unbind(sequencia)

        self.root.bind(
            "<KeyPress-Return>",
            self._evento_enter_pressionado,
        )
        self.root.bind(
            "<KeyPress-KP_Enter>",
            self._evento_enter_pressionado,
        )
        self.root.bind(
            "<KeyRelease-Return>",
            self._evento_enter_liberado,
        )
        self.root.bind(
            "<KeyRelease-KP_Enter>",
            self._evento_enter_liberado,
        )

        operation_window = getattr(self, "operacao_window", None)
        container = getattr(operation_window, "container", None)
        if container is not None:
            for sequencia in ("<Return>", "<KP_Enter>"):
                container.unbind(sequencia)

            container.bind(
                "<KeyPress-Return>",
                self._evento_enter_pressionado,
            )
            container.bind(
                "<KeyPress-KP_Enter>",
                self._evento_enter_pressionado,
            )
            container.bind(
                "<KeyRelease-Return>",
                self._evento_enter_liberado,
            )
            container.bind(
                "<KeyRelease-KP_Enter>",
                self._evento_enter_liberado,
            )

            operation_window.footer_label.configure(
                text=(
                    "ENTER: inspeção instantânea   |   "
                    "F1 ou ESC: parametrização"
                )
            )

    def _cancelar_rearme_enter(self) -> None:
        if self._enter_rearme_after_id is None:
            return

        try:
            self.root.after_cancel(self._enter_rearme_after_id)
        except Exception:
            pass

        self._enter_rearme_after_id = None

    def _rearmar_enter_instantaneo(self) -> None:
        self._enter_rearme_after_id = None
        self._enter_instantaneo_armado = True

    def _evento_enter_pressionado(self, evento=None) -> str:
        # No Linux, a repetição automática pode gerar pares muito rápidos de
        # KeyRelease/KeyPress. Cancelar o rearme pendente impede que manter a
        # tecla pressionada dispare várias inspeções.
        self._cancelar_rearme_enter()

        if not self._enter_instantaneo_armado:
            return "break"

        self._enter_instantaneo_armado = False

        if getattr(self, "operacao_ativa", False):
            # A inspeção é iniciada no primeiro KeyPress e preserva os guards existentes.
            self.disparar_inspecao_operacao()
        else:
            # Na parametrização, mantém a análise instantânea do frame ao vivo.
            self.capturar_frame_camera_para_analise(evento)

        return "break"

    def _evento_enter_liberado(self, _evento=None) -> str:
        self._cancelar_rearme_enter()
        try:
            self._enter_rearme_after_id = self.root.after(
                ENTER_REARM_DELAY_MS,
                self._rearmar_enter_instantaneo,
            )
        except tk.TclError:
            self._enter_rearme_after_id = None

        return "break"

    def _ao_destruir_atalho_enter(self, evento) -> None:
        if evento.widget is not self.root:
            return
        self._cancelar_rearme_enter()

