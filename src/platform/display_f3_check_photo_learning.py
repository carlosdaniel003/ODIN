from __future__ import annotations

"""Autoridade final do F3 baseada no próprio CHECK configurado.

Cada CHECK já possui tudo o que o analisador precisa para saber como aquele
estado deve parecer fisicamente:

* uma foto capturada em ``REFERÊNCIA VISUAL / PRESENÇA``;
* as máscaras persistidas do Projeto Display;
* ``mask_states`` dizendo, para cada máscara, se naquele CHECK ela é ACESA,
  APAGADA ou IGNORADA.

Esta camada transforma esse conjunto no aprendizado produtivo final do F3. A
mesma máscara do frame ao vivo é comparada com a mesma máscara da foto daquele
CHECK. O bloco legado ``REFERÊNCIAS / APRENDIZADO`` (amostras manuais globais de
ACESO/APAGADO/POUCA LUZ) não é consultado por esta autoridade e deixa de ser
exibido na configuração do Projeto Display.

A classe deriva do gabarito exato já existente, preservando a comparação por
pixels/energia dentro da máscara e os contratos históricos de H1/BLUE. O único
acréscimo de runtime é um cache da foto preparada do CHECK, evitando reler e
rotacionar o JPEG a cada frame no Raspberry Pi.

Nada deste módulo altera o F2.
"""

from copy import deepcopy
from pathlib import Path

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
from src.platform.display_f3_exact_check_template import (
    F3_EXACT_TEMPLATE_SOURCE,
    F3ExactCheckTemplateAnalyzer,
    _read_reference_full,
    _resize_visual_frame,
)
from src.platform.display_project_repository import normalizar_resolucao_display
from src.platform.display_visual_rotation import preparar_check_visual_display
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)


F3_CHECK_PHOTO_LEARNING_AUTHORITY = "f3_current_check_photo_mask_states"
F3_CHECK_PHOTO_LEARNING_SOURCE = "captured_check_photo_and_mask_states"


def _file_signature(path_value) -> tuple[str, int, int]:
    path = Path(str(path_value or ""))
    try:
        stat = path.stat()
        return str(path), int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return str(path), 0, 0


def _mask_signature(masks: list[dict]) -> tuple:
    values = []
    for mask in masks or ():
        if not isinstance(mask, dict):
            continue
        values.append(
            (
                str(mask.get("id") or ""),
                str(mask.get("type") or ""),
                repr(
                    {
                        key: mask.get(key)
                        for key in (
                            "cx",
                            "cy",
                            "radius",
                            "x",
                            "y",
                            "width",
                            "height",
                            "angle",
                            "points",
                        )
                        if key in mask
                    }
                ),
            )
        )
    return tuple(values)


class F3CheckPhotoLearningAnalyzer(F3ExactCheckTemplateAnalyzer):
    """Aprende o estado esperado diretamente da foto e ``mask_states`` do CHECK."""

    def __init__(self, repository) -> None:
        super().__init__(repository)
        self._check_template_cache_key = None
        self._check_template_cache = None

    def invalidate_learning_cache(self) -> None:
        self._check_template_cache_key = None
        self._check_template_cache = None

    def _reference_visual_context(
        self,
        project_name: str,
        check_id: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ):
        metadata = self.presence_store.get(project_name, check_id)
        if not isinstance(metadata, dict):
            return None, {}, None

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return None, {}, metadata

        cache_key = (
            str(project_name),
            str(check_id),
            int(visual_rotation or 0) % 360,
            tuple(master_resolution),
            str(project.get("updated_at") or ""),
            _file_signature(metadata.get("image_path")),
            _mask_signature(masks),
        )
        if cache_key == self._check_template_cache_key:
            cached = self._check_template_cache
            if isinstance(cached, tuple) and len(cached) == 3:
                frame, mask_by_id, cached_metadata = cached
                return frame, dict(mask_by_id), deepcopy(cached_metadata)

        reference = _read_reference_full(metadata)
        if reference is None:
            return None, {}, metadata

        frame, resolution, visual_masks = preparar_check_visual_display(
            reference,
            master_resolution,
            masks,
            visual_rotation,
        )
        frame = _resize_visual_frame(frame, resolution)
        if frame is None or getattr(frame, "size", 0) == 0:
            return None, {}, metadata

        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }
        self._check_template_cache_key = cache_key
        self._check_template_cache = (
            frame,
            dict(mask_by_id),
            deepcopy(metadata),
        )
        return frame, mask_by_id, metadata

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        analysis = super().analyze(
            frame=frame,
            project_name=project_name,
            check_id=check_id,
            visual_rotation=visual_rotation,
        )
        if not isinstance(analysis, dict):
            return analysis

        # Mantém o source exato para compatibilidade com a sonda rápida H1/BLUE.
        # Os novos campos explicitam de onde vem o aprendizado produtivo.
        analysis["reference_authority"] = F3_EXACT_TEMPLATE_SOURCE
        analysis["learning_authority"] = F3_CHECK_PHOTO_LEARNING_AUTHORITY
        analysis["learning_source"] = F3_CHECK_PHOTO_LEARNING_SOURCE
        analysis["uses_current_check_photo"] = True
        analysis["uses_project_masks"] = True
        analysis["uses_mask_states"] = True
        analysis["legacy_reference_learning_used"] = False
        analysis["cross_check_learning_used"] = False
        analysis["manual_reference_store_used"] = False

        results = [
            item
            for item in (analysis.get("mask_results") or ())
            if isinstance(item, dict)
        ]
        for item in results:
            item["learning_source"] = F3_CHECK_PHOTO_LEARNING_SOURCE
            item["expected_state_source"] = "check.mask_states"
            item["same_physical_mask_template"] = True

        analysis["learning_sample_count"] = len(results)
        if bool(analysis.get("ready")):
            analysis["reason"] = (
                "check_conforme_foto_e_estados_configurados"
                if analysis.get("approved") is True
                else "check_diverge_foto_ou_estados_configurados"
            )
        return analysis


def _install_runtime_aliases() -> None:
    """Usa exemplos ON/OFF reais da mesma máscara como classificação produtiva.

    A foto exata do CHECK continua disponível no DEBUG como comparação de cena,
    mas uma divergência de template nunca mais é convertida automaticamente no
    estado oposto do LED.
    """
    runtime_module.DisplayAutomaticCheckAnalyzer = F3SameMaskReferenceAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = F3SameMaskReferenceAnalyzer

    try:
        import src.platform.display_f3_live_diagnostic_trace as trace_module

        trace_module.F3ExactCheckTemplateAnalyzer = F3SameMaskReferenceAnalyzer
        trace_module._display_f3_check_photo_learning_authority = True
    except Exception:
        pass

    try:
        import src.platform.display_f3_h1_single_frame_probe as probe_module

        probe_module.LearnedDisplayAutomaticCheckAnalyzer = F3SameMaskReferenceAnalyzer
        probe_module._display_f3_check_photo_learning_authority = True
    except Exception:
        pass

    # DEBUG mantém os dois diagnósticos separados: foto exata de cena e
    # aprendizado produtivo ON/OFF da mesma máscara.
    try:
        import src.platform.display_f3_manual_snapshot_debug as debug_module

        debug_module.F3ExactCheckTemplateAnalyzer = F3CheckPhotoLearningAnalyzer
        debug_module.F3SameMaskReferenceAnalyzer = F3SameMaskReferenceAnalyzer
        debug_module._display_f3_check_photo_learning_authority = True
    except Exception:
        pass


def _install_legacy_reference_ui_retirement() -> None:
    """Remove da UI o bloco manual REFERÊNCIAS/APRENDIZADO agora redundante."""
    try:
        import src.platform.display_project_config as config_module
    except Exception:
        return

    cls = config_module.DisplayProjectConfigWindow
    if bool(getattr(cls, "_display_f3_legacy_reference_ui_retired", False)):
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        # A extensão histórica cria um box e guarda o botão. Destruímos o box
        # inteiro depois da composição final da janela, sem procurar widgets por
        # texto e sem alterar os demais painéis do Projeto Display.
        button = getattr(self, "reference_button", None)
        panel = getattr(button, "master", None) if button is not None else None
        if panel is not None:
            try:
                panel.destroy()
            except Exception:
                pass

        self.reference_button = None
        self.reference_summary = None
        legacy_window = getattr(self, "reference_window", None)
        if legacy_window is not None:
            try:
                if bool(getattr(legacy_window, "visible", False)):
                    legacy_window.close()
            except Exception:
                pass
        self.reference_window = None
        self._display_f3_legacy_reference_learning_retired = True

    def open_retired_references(self) -> None:
        # Mantido apenas para compatibilidade com chamadas antigas. Não abre a
        # janela nem consulta o store legado.
        self.reference_window = None
        return None

    cls.__init__ = init
    cls.open_display_references = open_retired_references
    cls._display_f3_legacy_reference_ui_retired = True


_INSTALLED = False


def instalar_aprendizado_foto_check_display_f3() -> None:
    """Instala fotos + máscaras + estados como aprendizado produtivo do F3."""
    global _INSTALLED

    # Reaplica os aliases em toda chamada. Algumas camadas históricas também os
    # reatribuem fora de seus guards; assim esta função pode sempre recuperar a
    # autoridade final sem criar outro loop de câmera.
    _install_runtime_aliases()
    _install_legacy_reference_ui_retirement()

    # Este instalador é o último do bootstrap F3. Fechamos aqui, e não em uma
    # camada intermediária, o handoff físico entre placas e a leitura do debug.
    # Assim H1 pode estar 28/28 conforme sem furar o rearme da placa anterior.
    from src.platform.display_f3_final_rearm_guard import (
        instalar_guard_rearme_terminal_final_display_f3,
    )

    instalar_guard_rearme_terminal_final_display_f3()

    from src.platform.display_f3_debug_clarity_fix import (
        instalar_clareza_debug_tecnico_display_f3,
    )

    instalar_clareza_debug_tecnico_display_f3()

    if _INSTALLED:
        return
    _INSTALLED = True
