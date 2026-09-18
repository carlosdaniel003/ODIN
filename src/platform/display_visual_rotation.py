from __future__ import annotations

from copy import deepcopy

from src.core.roi_geometry import normalizar_angulo_segmento
from src.ui.main_window_parts.image.rotacao_visual_principal import (
    converter_ponto_original_para_visual,
    dimensoes_visuais,
    normalizar_rotacao_visual,
    rotacionar_imagem_visual,
)


def obter_rotacao_visual_display(view) -> int:
    """Lê a orientação visual atual da tela principal sem alterar a câmera."""
    return normalizar_rotacao_visual(
        getattr(view, "rotacao_visual_principal", 0)
    )


def obter_rotacao_visual_do_frame_provider(frame_provider) -> int:
    """Resolve a rotação visual a partir do callback pertencente ao app F3."""
    app = getattr(frame_provider, "__self__", None)
    view = getattr(app, "view", None)
    return obter_rotacao_visual_display(view)


def preparar_frame_visual_display(frame, rotacao: int):
    """Retorna somente a representação visual usada pelo F3.

    O frame de origem nunca é modificado. A rotação segue exatamente a mesma
    convenção da imagem principal do ODIN (0/90/180/270 graus).
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    return rotacionar_imagem_visual(
        frame,
        normalizar_rotacao_visual(rotacao),
    )


def _ponto_visual(
    x: float,
    y: float,
    largura_original: int,
    altura_original: int,
    rotacao: int,
) -> list[int]:
    visual_x, visual_y = converter_ponto_original_para_visual(
        x,
        y,
        largura_original,
        altura_original,
        rotacao,
    )
    return [int(round(visual_x)), int(round(visual_y))]


def preparar_mascara_visual_display(
    mascara: dict,
    largura_original: int,
    altura_original: int,
    rotacao: int,
) -> dict:
    """Cria uma cópia visual da máscara sem alterar a geometria persistida."""
    item = deepcopy(mascara)
    angulo = normalizar_rotacao_visual(rotacao)
    if angulo == 0:
        return item

    tipo = str(item.get("type", "")).lower()
    mascara_id = str(item.get("id", ""))

    if tipo == "circle":
        cx, cy = _ponto_visual(
            item.get("cx", 0),
            item.get("cy", 0),
            largura_original,
            altura_original,
            angulo,
        )
        item["cx"] = cx
        item["cy"] = cy
        return item

    if tipo == "segment":
        cx, cy = _ponto_visual(
            item.get("cx", 0),
            item.get("cy", 0),
            largura_original,
            altura_original,
            angulo,
        )
        item["cx"] = cx
        item["cy"] = cy
        item["angle"] = normalizar_angulo_segmento(
            float(item.get("angle", 0) or 0) + angulo
        )
        return item

    if tipo == "polygon":
        item["points"] = [
            _ponto_visual(
                ponto[0],
                ponto[1],
                largura_original,
                altura_original,
                angulo,
            )
            for ponto in item.get("points", [])
            if isinstance(ponto, (list, tuple)) and len(ponto) >= 2
        ]
        return item

    if tipo == "rectangle":
        x = float(item.get("x", 0))
        y = float(item.get("y", 0))
        largura = float(item.get("width", 0))
        altura = float(item.get("height", 0))
        pontos = (
            (x, y),
            (x + largura, y),
            (x + largura, y + altura),
            (x, y + altura),
        )
        return {
            "id": mascara_id,
            "type": "polygon",
            "points": [
                _ponto_visual(
                    px,
                    py,
                    largura_original,
                    altura_original,
                    angulo,
                )
                for px, py in pontos
            ],
        }

    return item


def restaurar_mascara_original_display(
    mascara_visual: dict,
    largura_original: int,
    altura_original: int,
    rotacao: int,
) -> dict:
    """Converte uma máscara editada visualmente de volta à orientação mestre.

    O editor de máscaras trabalha na mesma orientação que o operador enxerga.
    Antes de persistir, a geometria volta para as coordenadas da resolução
    mestre, mantendo câmera e arquivos Display independentes da rotação visual.
    """
    angulo = normalizar_rotacao_visual(rotacao)
    if angulo == 0:
        return deepcopy(mascara_visual)

    largura_visual, altura_visual = dimensoes_visuais(
        max(1, int(largura_original)),
        max(1, int(altura_original)),
        angulo,
    )
    rotacao_inversa = normalizar_rotacao_visual(360 - angulo)
    return preparar_mascara_visual_display(
        mascara_visual,
        largura_visual,
        altura_visual,
        rotacao_inversa,
    )


def preparar_pontos_visuais_display(
    points,
    largura_original: int,
    altura_original: int,
    rotacao: int,
) -> list[list[float]]:
    angulo = normalizar_rotacao_visual(rotacao)
    result = []
    for point in (points or []):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x, y = converter_ponto_original_para_visual(
            float(point[0]),
            float(point[1]),
            int(largura_original),
            int(altura_original),
            angulo,
        )
        result.append([float(x), float(y)])
    return result


def restaurar_pontos_originais_display(
    points_visual,
    largura_original: int,
    altura_original: int,
    rotacao: int,
) -> list[list[float]]:
    angulo = normalizar_rotacao_visual(rotacao)
    if angulo == 0:
        return [
            [float(point[0]), float(point[1])]
            for point in (points_visual or [])
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
    largura_visual, altura_visual = dimensoes_visuais(
        int(largura_original),
        int(altura_original),
        angulo,
    )
    return preparar_pontos_visuais_display(
        points_visual,
        largura_visual,
        altura_visual,
        normalizar_rotacao_visual(360 - angulo),
    )


def preparar_check_visual_display(
    frame,
    master_resolution,
    masks,
    rotacao: int,
):
    """Prepara frame, resolução e máscaras do CHECK na mesma orientação visual."""
    largura = max(1, int(master_resolution[0]))
    altura = max(1, int(master_resolution[1]))
    angulo = normalizar_rotacao_visual(rotacao)
    largura_visual, altura_visual = dimensoes_visuais(
        largura,
        altura,
        angulo,
    )
    frame_visual = preparar_frame_visual_display(frame, angulo)
    mascaras_visuais = [
        preparar_mascara_visual_display(
            mascara,
            largura,
            altura,
            angulo,
        )
        for mascara in (masks or [])
        if isinstance(mascara, dict)
    ]
    return (
        frame_visual,
        (largura_visual, altura_visual),
        mascaras_visuais,
    )


def instalar_rotacao_visual_editor_mascaras_display() -> None:
    """Aplica rotação visual também ao editor de máscaras do Projeto Display."""
    import src.platform.display_project_config as config_module

    config_window = config_module.DisplayProjectConfigWindow
    if getattr(config_window, "_odin_display_mask_visual_rotation", False):
        return

    def edit_masks(self) -> None:
        name = self._selected_name()
        if not name:
            config_module.messagebox.showwarning(
                "Sem Projeto Display",
                "Selecione ou crie um projeto primeiro.",
                parent=self.window,
            )
            return
        resolution = self._read_resolution_fields()
        if resolution is None:
            return
        if not self.repository.salvar_resolucao_mestra(name, *resolution):
            return
        project = self.repository.carregar_projeto(name)
        if project is None:
            return
        try:
            frame = self.frame_provider()
        except Exception:
            frame = None

        visual_rotation = obter_rotacao_visual_do_frame_provider(
            self.frame_provider
        )
        frame_visual, resolution_visual, masks_visual = (
            preparar_check_visual_display(
                frame,
                resolution,
                project.get("masks", []),
                visual_rotation,
            )
        )

        def save_masks(masks: list[dict]) -> None:
            masks_original = [
                restaurar_mascara_original_display(
                    mask,
                    resolution[0],
                    resolution[1],
                    visual_rotation,
                )
                for mask in (masks or [])
                if isinstance(mask, dict)
            ]
            if self.repository.salvar_configuracao_projeto(
                name,
                resolution,
                masks_original,
            ):
                self.refresh(name)
                self.status.configure(
                    text=f"{len(masks_original)} máscara(s) salvas em {name}."
                )
                self._notify_change()

        self.mask_editor = config_module.DisplayMaskEditorWindow(
            root=self.root,
            master_resolution=resolution_visual,
            masks=masks_visual,
            frame=frame_visual,
            on_save=save_masks,
        )
        try:
            self.mask_editor.visual_rotation = visual_rotation
        except Exception:
            pass

    config_window.edit_masks = edit_masks
    config_window._odin_display_mask_visual_rotation = True


def instalar_rotacao_visual_editor_check_display() -> None:
    """Estende somente o gerenciador de CHECKS do F3 com rotação visual."""
    import src.platform.display_check_editor as check_module

    manager = check_module.DisplayCheckManagerWindow
    if getattr(manager, "_odin_display_check_visual_rotation", False):
        return

    def edit_selected(self) -> None:
        check_id = self._selected_id()
        if not check_id:
            return
        project = self.repository.carregar_projeto(self.project_name)
        check = self.repository.carregar_check(self.project_name, check_id)
        if project is None or check is None:
            return
        masks = project.get("masks", [])
        if not masks:
            check_module.messagebox.showwarning(
                "Sem máscaras",
                "Crie as máscaras do Projeto Display antes de editar os CHECKS.",
                parent=self.window,
            )
            return
        resolution = check_module.normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if resolution is None:
            check_module.messagebox.showwarning(
                "Sem resolução mestre",
                "Defina a resolução mestre do Projeto Display primeiro.",
                parent=self.window,
            )
            return
        try:
            frame = self.frame_provider()
        except Exception:
            frame = None

        visual_rotation = obter_rotacao_visual_do_frame_provider(
            self.frame_provider
        )
        frame_visual, resolution_visual, masks_visual = (
            preparar_check_visual_display(
                frame,
                resolution,
                masks,
                visual_rotation,
            )
        )

        def save_states(states: dict[str, str]) -> None:
            if self.repository.salvar_estados_check(
                self.project_name,
                check_id,
                states,
            ):
                self.refresh(check_id)
                self._notify_change()

        board_original = check.get("board_points_reference", [])
        if not board_original:
            try:
                from src.platform.display_f3_object_tracking import (
                    F3TrackingConfigStore,
                    canonical_board_points,
                )
                board_original = canonical_board_points(
                    project,
                    F3TrackingConfigStore(self.repository),
                )
            except Exception:
                board_original = []
        board_visual = preparar_pontos_visuais_display(
            board_original,
            resolution[0],
            resolution[1],
            visual_rotation,
        )
        raw_overrides = (
            check.get("mask_overrides_reference", {})
            if isinstance(check.get("mask_overrides_reference"), dict)
            else {}
        )
        overrides_visual = {
            str(mask_id): preparar_mascara_visual_display(
                mask,
                resolution[0],
                resolution[1],
                visual_rotation,
            )
            for mask_id, mask in raw_overrides.items()
            if isinstance(mask, dict)
        }

        def save_geometry(board_points, edited_masks) -> None:
            board_original_saved = restaurar_pontos_originais_display(
                board_points,
                resolution[0],
                resolution[1],
                visual_rotation,
            )
            overrides_original = {}
            for mask in (edited_masks or []):
                if not isinstance(mask, dict):
                    continue
                mask_id = str(mask.get("id") or "")
                if not mask_id:
                    continue
                overrides_original[mask_id] = restaurar_mascara_original_display(
                    mask,
                    resolution[0],
                    resolution[1],
                    visual_rotation,
                )
            if self.repository.salvar_geometria_check(
                self.project_name,
                check_id,
                board_original_saved,
                overrides_original,
            ):
                self.refresh(check_id)
                self._notify_change()

        self.check_editor = check_module.DisplayCheckMaskEditorWindow(
            root=self.root,
            project_name=self.project_name,
            check=check,
            master_resolution=resolution_visual,
            masks=masks_visual,
            frame=frame_visual,
            on_save=save_states,
            board_points=board_visual,
            mask_overrides=overrides_visual,
            on_save_geometry=save_geometry,
        )
        try:
            self.check_editor.visual_rotation = visual_rotation
        except Exception:
            pass

    manager.edit_selected = edit_selected
    manager._odin_display_check_visual_rotation = True


instalar_rotacao_visual_editor_mascaras_display()
instalar_rotacao_visual_editor_check_display()
