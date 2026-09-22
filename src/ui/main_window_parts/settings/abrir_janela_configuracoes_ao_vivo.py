from __future__ import annotations

import tkinter as tk

from config import CAMERA_RESOLUTION_PRESETS, DEFAULT_CAMERA_SETTINGS
from src.ui.main_window_parts.settings.abrir_janela_configuracoes_interativa import (
    abrir_janela_configuracoes as abrir_janela_configuracoes_interativa,
)
from src.ui.main_window_parts.widgets.select_lista import SelectLista


LIVE_CAMERA_DEBOUNCE_MS = 60
LIVE_CAMERA_STATUS_DELAY_MS = 140


_CONTROLES_MANUAIS = {
    "Panorâmica manual": "pan",
    "Inclinação manual": "tilt",
    "Contraste manual": "contrast",
    "Nitidez manual": "sharpness",
    "Saturação manual": "saturation",
    "Exposição manual": "exposure",
    "Ganho manual": "gain",
    "Foco manual": "focus",
    "Balanço de branco manual": "white_balance",
    "Brilho manual": "brightness",
    "Gamma manual": "gamma",
}

_CONTROLES_AUTOMATICOS = {
    "Exposição automática": "exposure_auto",
    "Foco automático": "focus_auto",
    "Balanço de branco automático": "white_balance_auto",
}

_NOMES_STATUS = {
    "aplicado": "Aplicado ao vivo",
    "nao_suportado": "Não suportado",
    "ignorado_driver": "Driver não confirmou este valor",
    "ajustado_driver": "Limitado ao passo aceito pelo driver",
    "padrao_driver": "Padrão do driver",
    "padrao_driver_windows": "Padrão do Windows",
    "aguardando_camera": "Aguardando câmera",
    "aplicado_software": "Aplicado ao vivo",
    "automatico": "Automático",
    "travado_producao": "Aplicado ao vivo",
    "travado_producao_v4l2": "Aplicado ao vivo",
}


def _percorrer_widgets(widget):
    for filho in widget.winfo_children():
        yield filho
        yield from _percorrer_widgets(filho)


def _encontrar_label(widget, texto: str):
    for item in _percorrer_widgets(widget):
        if not isinstance(item, tk.Label):
            continue
        try:
            if str(item.cget("text")) == texto:
                return item
        except tk.TclError:
            continue
    return None


def _encontrar_card(janela: tk.Toplevel, titulo: str):
    label = _encontrar_label(janela, titulo)
    return label.master if label is not None else None


def _primeiro_widget(widget, classe):
    for item in _percorrer_widgets(widget):
        if isinstance(item, classe):
            return item
    return None


def _variavel_existente(widget, opcao: str, classe):
    try:
        nome = str(widget.cget(opcao) or "").strip()
    except (tk.TclError, AttributeError):
        return None
    if not nome:
        return None
    try:
        return classe(master=widget, name=nome)
    except (tk.TclError, TypeError):
        return None


def _variavel_linha_select(corpo, texto_label: str):
    label = _encontrar_label(corpo, texto_label)
    if label is None:
        return None
    select = _primeiro_widget(label.master, SelectLista)
    if select is None:
        return None
    return _variavel_existente(select, "textvariable", tk.StringVar)


def _capturar_variaveis_camera(janela: tk.Toplevel) -> tuple[dict, dict]:
    variaveis: dict[str, tk.Variable] = {}
    labels_status: dict[str, tk.Label] = {}

    card_perfil = _encontrar_card(janela, "Perfil de captura")
    if card_perfil is not None:
        variaveis["_resolution_label"] = _variavel_linha_select(
            card_perfil,
            "Resolução:",
        )
        variaveis["_fps_label"] = _variavel_linha_select(
            card_perfil,
            "FPS:",
        )
        variaveis["_format_label"] = _variavel_linha_select(
            card_perfil,
            "Formato:",
        )

        label_personalizada = _encontrar_label(
            card_perfil,
            "Personalizada:",
        )
        if label_personalizada is not None:
            spinboxes = [
                item
                for item in _percorrer_widgets(label_personalizada.master)
                if isinstance(item, tk.Spinbox)
            ]
            if len(spinboxes) >= 2:
                variaveis["_width"] = _variavel_existente(
                    spinboxes[0],
                    "textvariable",
                    tk.IntVar,
                )
                variaveis["_height"] = _variavel_existente(
                    spinboxes[1],
                    "textvariable",
                    tk.IntVar,
                )

    card_rotacao = _encontrar_card(janela, "Rotação da imagem")
    if card_rotacao is not None:
        select_rotacao = _primeiro_widget(card_rotacao, SelectLista)
        if select_rotacao is not None:
            variaveis["_rotation_label"] = _variavel_existente(
                select_rotacao,
                "textvariable",
                tk.StringVar,
            )

    for item in _percorrer_widgets(janela):
        if not isinstance(item, tk.Checkbutton):
            continue
        try:
            texto = str(item.cget("text"))
        except tk.TclError:
            continue

        if texto in _CONTROLES_AUTOMATICOS:
            chave = _CONTROLES_AUTOMATICOS[texto]
            variavel = _variavel_existente(item, "variable", tk.BooleanVar)
            if variavel is not None:
                variaveis[chave] = variavel
            continue

        nome = _CONTROLES_MANUAIS.get(texto)
        if nome is None:
            continue

        habilitado = _variavel_existente(item, "variable", tk.BooleanVar)
        if habilitado is not None:
            variaveis[f"{nome}_enabled"] = habilitado

        linha = item.master.master
        escala = _primeiro_widget(linha, tk.Scale)
        if escala is not None:
            valor = _variavel_existente(escala, "variable", tk.DoubleVar)
            if valor is not None:
                variaveis[nome] = valor

        for candidato in item.master.winfo_children():
            if isinstance(candidato, tk.Label):
                labels_status[nome] = candidato
                break

    return (
        {chave: valor for chave, valor in variaveis.items() if valor is not None},
        labels_status,
    )


def construir_configuracoes_camera_ao_vivo(
    configuracoes_base: dict | None,
    variaveis: dict,
) -> dict:
    """Monta o estado atual da aba Câmera sem persistir em disco."""
    configuracoes = dict(configuracoes_base or {})
    padrao = DEFAULT_CAMERA_SETTINGS

    mapa_label_para_resolucao = {
        dados["label"]: modo
        for modo, dados in CAMERA_RESOLUTION_PRESETS.items()
    }

    variavel = variaveis.get("_resolution_label")
    if variavel is not None:
        modo = mapa_label_para_resolucao.get(str(variavel.get()), "auto")
        configuracoes["resolution_mode"] = modo

    for chave_ui, chave_config in (
        ("_width", "width"),
        ("_height", "height"),
    ):
        variavel = variaveis.get(chave_ui)
        if variavel is not None:
            try:
                configuracoes[chave_config] = int(variavel.get())
            except (TypeError, ValueError, tk.TclError):
                configuracoes[chave_config] = int(padrao[chave_config])

    variavel_fps = variaveis.get("_fps_label")
    if variavel_fps is not None:
        fps_texto = str(variavel_fps.get())
        automatico = fps_texto == "Automático"
        configuracoes["fps_mode"] = "auto" if automatico else "manual"
        try:
            configuracoes["fps"] = 0 if automatico else int(fps_texto)
        except (TypeError, ValueError):
            configuracoes["fps"] = int(padrao["fps"])

    variavel_formato = variaveis.get("_format_label")
    if variavel_formato is not None:
        configuracoes["format"] = str(variavel_formato.get()).upper()

    variavel_rotacao = variaveis.get("_rotation_label")
    if variavel_rotacao is not None:
        try:
            configuracoes["rotation"] = int(
                str(variavel_rotacao.get()).replace("°", "")
            )
        except (TypeError, ValueError):
            configuracoes["rotation"] = int(padrao["rotation"])

    chaves_booleanas = {
        f"{nome}_enabled" for nome in _CONTROLES_MANUAIS.values()
    } | set(_CONTROLES_AUTOMATICOS.values())

    for chave, variavel in variaveis.items():
        if chave.startswith("_"):
            continue
        try:
            if chave in chaves_booleanas:
                configuracoes[chave] = bool(variavel.get())
            elif chave in _CONTROLES_MANUAIS.values():
                configuracoes[chave] = float(variavel.get())
        except (TypeError, ValueError, tk.TclError):
            continue

    return configuracoes


def _atualizar_texto_estado_camera(
    janela: tk.Toplevel,
    camera_conectada: bool,
) -> None:
    for item in _percorrer_widgets(janela):
        if not isinstance(item, tk.Label):
            continue
        try:
            texto = str(item.cget("text"))
        except tk.TclError:
            continue
        if not (
            texto.startswith("Câmera conectada.")
            or texto.startswith("Câmera desligada ou reconectando.")
        ):
            continue

        if camera_conectada:
            item.configure(
                text=(
                    "Câmera conectada. Foco, exposição, ganho, balanço de branco, "
                    "brilho, gamma, posição, imagem e rotação são aplicados em "
                    "tempo real. Salvar apenas persiste os valores; Cancelar "
                    "restaura o estado anterior."
                ),
                fg="#BBF7D0",
            )
        else:
            item.configure(
                text=(
                    "Câmera desligada ou reconectando. Os valores podem ser "
                    "editados, mas a aplicação ao vivo começa quando houver "
                    "uma câmera ativa."
                ),
                fg="#FDE68A",
            )
        return


def _atualizar_labels_status(labels_status: dict, status: dict) -> None:
    if not isinstance(status, dict):
        return
    for nome, label in labels_status.items():
        dados = status.get(nome, {})
        if not isinstance(dados, dict):
            continue
        estado = str(dados.get("status") or "")
        if not estado:
            continue
        try:
            label.configure(text=_NOMES_STATUS.get(estado, estado))
        except tk.TclError:
            pass


def abrir_janela_configuracoes_ao_vivo(
    self,
    *args,
    callback_camera_ao_vivo=None,
    callback_cancelar_camera_ao_vivo=None,
    callback_status_camera_ao_vivo=None,
    **kwargs,
) -> None:
    """Abre as configurações e conecta os controles diretamente à câmera ativa."""
    configuracoes_originais = dict(kwargs.get("configuracoes_camera") or {})
    camera_conectada = bool(kwargs.get("camera_conectada", False))
    callback_salvar_original = kwargs.get("callback_salvar")
    estado = {
        "salvo": False,
        "houve_live": False,
        "after_live": None,
        "after_status": None,
    }

    def callback_salvar_marcado(*callback_args, **callback_kwargs):
        estado["salvo"] = True
        if callback_salvar_original is not None:
            return callback_salvar_original(*callback_args, **callback_kwargs)
        return None

    kwargs["callback_salvar"] = callback_salvar_marcado

    janelas_antes = {
        widget
        for widget in self.root.winfo_children()
        if isinstance(widget, tk.Toplevel)
    }
    abrir_janela_configuracoes_interativa(self, *args, **kwargs)

    novas_janelas = [
        widget
        for widget in self.root.winfo_children()
        if isinstance(widget, tk.Toplevel)
        and widget not in janelas_antes
        and widget.winfo_exists()
    ]
    if not novas_janelas:
        return

    janela = novas_janelas[-1]
    variaveis, labels_status = _capturar_variaveis_camera(janela)
    janela._odin_camera_live_variables = variaveis
    janela._odin_camera_live_status_labels = labels_status
    _atualizar_texto_estado_camera(janela, camera_conectada)

    def consultar_status() -> None:
        estado["after_status"] = None
        if callback_status_camera_ao_vivo is None:
            return
        try:
            if not janela.winfo_exists():
                return
            status = callback_status_camera_ao_vivo()
        except (tk.TclError, Exception):
            return
        _atualizar_labels_status(labels_status, status)

    def aplicar_ao_vivo() -> None:
        estado["after_live"] = None
        if callback_camera_ao_vivo is None:
            return
        try:
            if not janela.winfo_exists():
                return
            configuracoes = construir_configuracoes_camera_ao_vivo(
                configuracoes_originais,
                variaveis,
            )
            callback_camera_ao_vivo(configuracoes)
            estado["houve_live"] = True
        except (tk.TclError, Exception):
            return

        if callback_status_camera_ao_vivo is not None:
            if estado["after_status"] is not None:
                try:
                    janela.after_cancel(estado["after_status"])
                except tk.TclError:
                    pass
            estado["after_status"] = janela.after(
                LIVE_CAMERA_STATUS_DELAY_MS,
                consultar_status,
            )

    def agendar_aplicacao(*_args) -> None:
        if callback_camera_ao_vivo is None:
            return
        try:
            if estado["after_live"] is not None:
                janela.after_cancel(estado["after_live"])
            estado["after_live"] = janela.after(
                LIVE_CAMERA_DEBOUNCE_MS,
                aplicar_ao_vivo,
            )
        except tk.TclError:
            pass

    traces = []
    vistos = set()
    for variavel in variaveis.values():
        nome = str(variavel)
        if nome in vistos:
            continue
        vistos.add(nome)
        try:
            trace_id = variavel.trace_add("write", agendar_aplicacao)
            traces.append((variavel, trace_id))
        except tk.TclError:
            continue
    janela._odin_camera_live_traces = traces

    def ao_destruir(evento) -> None:
        if evento.widget is not janela:
            return
        for chave in ("after_live", "after_status"):
            after_id = estado.get(chave)
            if after_id is not None:
                try:
                    janela.after_cancel(after_id)
                except tk.TclError:
                    pass
                estado[chave] = None

        if (
            not estado["salvo"]
            and estado["houve_live"]
            and callback_cancelar_camera_ao_vivo is not None
        ):
            try:
                callback_cancelar_camera_ao_vivo(configuracoes_originais)
            except Exception:
                pass

    janela.bind("<Destroy>", ao_destruir, add="+")
