from __future__ import annotations

import math
import tkinter as tk

from src.ui.main_window_parts.settings.abrir_janela_configuracoes_ao_vivo import (
    abrir_janela_configuracoes_ao_vivo as abrir_janela_base,
)


_MANUAL_PARA_AUTO = {
    "exposure": "exposure_auto",
    "focus": "focus_auto",
    "white_balance": "white_balance_auto",
}
_AUTO_PARA_MANUAL = {
    valor: chave for chave, valor in _MANUAL_PARA_AUTO.items()
}

_STATUS_AMIGAVEL = {
    "manual_pronto": "Pronto para ajuste",
    "restaurado": "Restaurado",
    "manual_disponivel": "Manual disponível",
    "automatico": "Automático",
    "aplicado": "Aplicado ao vivo",
    "nao_suportado": "Não suportado pelo driver",
    "ignorado_driver": "Driver não confirmou este valor",
    "ajustado_driver": "Limitado ao passo aceito pelo driver",
    "padrao_driver": "Padrão do driver",
    "padrao_driver_windows": "Padrão do Windows",
}


def _nova_janela(root, anteriores):
    novas = [
        widget
        for widget in root.winfo_children()
        if isinstance(widget, tk.Toplevel)
        and widget not in anteriores
        and widget.winfo_exists()
    ]
    return novas[-1] if novas else None


def abrir_janela_configuracoes_sem_saltos(
    self,
    *args,
    callback_status_camera_ao_vivo=None,
    **kwargs,
) -> None:
    """Acrescenta semântica manual/restaurar sobre a janela ao vivo existente."""
    anteriores = {
        widget
        for widget in self.root.winfo_children()
        if isinstance(widget, tk.Toplevel)
    }

    abrir_janela_base(
        self,
        *args,
        callback_status_camera_ao_vivo=callback_status_camera_ao_vivo,
        **kwargs,
    )

    janela = _nova_janela(self.root, anteriores)
    if janela is None:
        return

    variaveis = getattr(janela, "_odin_camera_live_variables", {})
    labels_status = getattr(janela, "_odin_camera_live_status_labels", {})
    estado = {
        "sincronizando": False,
        "aguardando_baseline": set(),
        "after_status": None,
        "tentativas_status": 0,
    }

    def consultar_baselines() -> None:
        estado["after_status"] = None
        if callback_status_camera_ao_vivo is None:
            return
        try:
            if not janela.winfo_exists():
                return
            status = callback_status_camera_ao_vivo() or {}
        except Exception:
            return

        pendentes = set(estado["aguardando_baseline"])
        for nome in tuple(pendentes):
            dados = status.get(nome, {})
            if not isinstance(dados, dict):
                continue

            status_nome = str(dados.get("status") or "")
            label = labels_status.get(nome)
            if label is not None and status_nome:
                try:
                    label.configure(
                        text=_STATUS_AMIGAVEL.get(status_nome, status_nome)
                    )
                except tk.TclError:
                    pass

            if status_nome != "manual_pronto":
                continue

            valor = dados.get("valor_lido")
            try:
                valor = float(valor)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(valor):
                continue

            variavel = variaveis.get(nome)
            if variavel is None:
                continue

            # Só sincroniza se o usuário ainda não começou a arrastar o slider.
            estado["sincronizando"] = True
            try:
                variavel.set(valor)
            except tk.TclError:
                pass
            finally:
                estado["sincronizando"] = False
            estado["aguardando_baseline"].discard(nome)

        if estado["aguardando_baseline"] and estado["tentativas_status"] < 6:
            estado["tentativas_status"] += 1
            try:
                estado["after_status"] = janela.after(90, consultar_baselines)
            except tk.TclError:
                estado["after_status"] = None

    def agendar_consulta_baseline() -> None:
        if callback_status_camera_ao_vivo is None:
            return
        if estado["after_status"] is not None:
            try:
                janela.after_cancel(estado["after_status"])
            except tk.TclError:
                pass
        estado["tentativas_status"] = 0
        try:
            estado["after_status"] = janela.after(90, consultar_baselines)
        except tk.TclError:
            estado["after_status"] = None

    def mudou_manual(nome: str) -> None:
        if estado["sincronizando"]:
            return
        enabled_var = variaveis.get(f"{nome}_enabled")
        if enabled_var is None:
            return
        try:
            habilitado = bool(enabled_var.get())
        except tk.TclError:
            return

        auto_chave = _MANUAL_PARA_AUTO.get(nome)
        auto_var = variaveis.get(auto_chave) if auto_chave else None

        if habilitado:
            estado["aguardando_baseline"].add(nome)
            if auto_var is not None:
                try:
                    if bool(auto_var.get()):
                        auto_var.set(False)
                except tk.TclError:
                    pass
            agendar_consulta_baseline()
        else:
            estado["aguardando_baseline"].discard(nome)
            # Para foco/exposição/WB, sair do manual significa voltar ao
            # comportamento automático/default da câmera.
            if auto_var is not None:
                try:
                    if not bool(auto_var.get()):
                        auto_var.set(True)
                except tk.TclError:
                    pass

    def mudou_automatico(chave_auto: str) -> None:
        if estado["sincronizando"]:
            return
        auto_var = variaveis.get(chave_auto)
        nome = _AUTO_PARA_MANUAL.get(chave_auto)
        enabled_var = variaveis.get(f"{nome}_enabled") if nome else None
        if auto_var is None or enabled_var is None:
            return
        try:
            automatico = bool(auto_var.get())
        except tk.TclError:
            return
        if automatico:
            estado["aguardando_baseline"].discard(nome)
            try:
                if bool(enabled_var.get()):
                    enabled_var.set(False)
            except tk.TclError:
                pass

    def mudou_valor(nome: str) -> None:
        if estado["sincronizando"]:
            return
        # Se o usuário já moveu o slider, não sobrescrevemos seu valor quando
        # a leitura do baseline chegar alguns milissegundos depois.
        estado["aguardando_baseline"].discard(nome)

    traces = []
    for nome in (
        "pan",
        "tilt",
        "contrast",
        "sharpness",
        "saturation",
        "exposure",
        "gain",
        "focus",
        "white_balance",
        "brightness",
        "gamma",
    ):
        enabled_var = variaveis.get(f"{nome}_enabled")
        valor_var = variaveis.get(nome)
        if enabled_var is not None:
            try:
                trace_id = enabled_var.trace_add(
                    "write",
                    lambda *_args, n=nome: mudou_manual(n),
                )
                traces.append((enabled_var, trace_id))
            except tk.TclError:
                pass
        if valor_var is not None:
            try:
                trace_id = valor_var.trace_add(
                    "write",
                    lambda *_args, n=nome: mudou_valor(n),
                )
                traces.append((valor_var, trace_id))
            except tk.TclError:
                pass

    for chave_auto in _AUTO_PARA_MANUAL:
        auto_var = variaveis.get(chave_auto)
        if auto_var is None:
            continue
        try:
            trace_id = auto_var.trace_add(
                "write",
                lambda *_args, chave=chave_auto: mudou_automatico(chave),
            )
            traces.append((auto_var, trace_id))
        except tk.TclError:
            pass

    janela._odin_camera_sem_saltos_traces = traces

    def ao_destruir(evento) -> None:
        if evento.widget is not janela:
            return
        after_id = estado.get("after_status")
        if after_id is not None:
            try:
                janela.after_cancel(after_id)
            except tk.TclError:
                pass

    janela.bind("<Destroy>", ao_destruir, add="+")
