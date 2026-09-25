from __future__ import annotations

"""Otimizações finais do Display F3 sem alterar o runtime da Produção F2.

Esta camada atua nos custos que não acrescentam informação operacional:
- releitura/normalização dos mesmos JSONs a cada frame;
- processamento repetido do mesmo frame da câmera antes do gate de frame novo;
- análise F3 e render da janela de produção atrás das telas de configuração;
- matcher visual legado que ficou sem saída depois do status físico unificado;
- leitura/cópia Full HD repetida das fotos de referência;
- redraw completo do editor apenas para mover a lupa.
"""

from copy import deepcopy
from pathlib import Path
import time

import cv2
import numpy as np


F3_CONFIG_BACKGROUND_INTERVAL_MS = 280
F3_MASK_POINTER_INTERVAL_S = 1.0 / 20.0
F3_MASK_DRAG_REDRAW_INTERVAL_S = 1.0 / 30.0
F3_MAGNIFIER_TAG = "odin_f3_magnifier_overlay"
F3_TIME_EPSILON = 1e-9

# O preview anterior herdava 45 ms do automático. Isso colocava o Tk em uma fila
# praticamente contínua quando um ciclo óptico custava mais do que 45 ms.
# H1/BLUE continuam rápidos; demais estados cedem tempo ao event loop.
F3_FAST_CYCLE_TARGET_MS = 50
F3_NORMAL_CYCLE_TARGET_MS = 85
F3_MIN_IDLE_SLICE_MS = 12

# Comparação física usa a mesma lógica visual, mas a referência é recortada antes
# de ser reduzida. Assim não copiamos/redimensionamos um frame Full HD inteiro uma
# vez para cada candidato físico.
F3_REFERENCE_COMPARE_WIDTH = 360
F3_REFERENCE_CACHE_LIMIT = 64
F3_MASK_REFERENCE_CACHE_LIMIT = 256

_REFERENCE_IMAGE_CACHE: dict[str, tuple[tuple[int, int], object]] = {}
_REFERENCE_COMPARE_CACHE: dict[tuple, object] = {}
_MASK_REFERENCE_CACHE: dict[tuple, dict] = {}


def _file_signature(path) -> tuple[int, int] | None:
    try:
        value = Path(path)
        stat = value.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except (OSError, TypeError, ValueError):
        return None


def _cached_payload(self, signature_attr: str, payload_attr: str, signature):
    if signature != getattr(self, signature_attr, object()):
        return None
    return getattr(self, payload_attr, None)


def _install_file_backed_cache(
    cls,
    *,
    load_name: str,
    write_name: str,
    path_attr: str,
    marker: str,
) -> None:
    """Cacheia o payload normalizado sem deepcopy do documento inteiro por leitura.

    Os repositórios F3 são usados no thread do Tk. APIs públicas que devolvem
    projeto/referência já fazem cópia do item retornado; operações mutáveis seguem
    o fluxo carregar -> alterar -> escrever e a escrita invalida o cache.
    """
    if bool(getattr(cls, marker, False)):
        return
    original_load = getattr(cls, load_name)
    original_write = getattr(cls, write_name)
    signature_attr = f"_{marker}_signature"
    payload_attr = f"_{marker}_payload"

    def load(self):
        path = getattr(self, path_attr, None)
        signature = _file_signature(path)
        cached = _cached_payload(self, signature_attr, payload_attr, signature)
        if cached is not None:
            return cached

        data = original_load(self)
        setattr(self, signature_attr, _file_signature(path))
        setattr(self, payload_attr, data)
        return data

    def write(self, data):
        setattr(self, signature_attr, object())
        setattr(self, payload_attr, None)
        result = original_write(self, data)
        setattr(self, signature_attr, object())
        setattr(self, payload_attr, None)
        return result

    setattr(cls, load_name, load)
    setattr(cls, write_name, write)
    setattr(cls, marker, True)


def _install_repository_caches() -> None:
    from src.platform.display_project_repository import DisplayProjectRepository
    from src.platform.display_check_presence_reference import (
        DisplayCheckPresenceReferenceStore,
    )
    from src.platform.display_visual_reference_status import (
        DisplayProjectPresenceReferenceStore,
    )

    _install_file_backed_cache(
        DisplayProjectRepository,
        load_name="_carregar",
        write_name="_escrever",
        path_attr="config_file",
        marker="_display_f3_cached_project_repository",
    )
    _install_file_backed_cache(
        DisplayCheckPresenceReferenceStore,
        load_name="_load",
        write_name="_write",
        path_attr="config_file",
        marker="_display_f3_cached_check_references",
    )
    _install_file_backed_cache(
        DisplayProjectPresenceReferenceStore,
        load_name="_load",
        write_name="_write",
        path_attr="config_file",
        marker="_display_f3_cached_project_references",
    )


def configuracao_f3_visivel(app) -> bool:
    if bool(getattr(app, "_display_f3_configuration_opening", False)):
        return True
    config = getattr(app, "_display_project_config_window", None)
    if config is None:
        return False
    try:
        return bool(config.visible)
    except Exception:
        return False


def _install_configuration_runtime_pause() -> None:
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin
    from src.platform.display_production_f3 import DisplayProductionF3Mixin

    if not bool(
        getattr(
            DisplayAutomaticCheckF3Mixin,
            "_display_f3_configuration_pause_installed",
            False,
        )
    ):
        original_process = DisplayAutomaticCheckF3Mixin._process_display_auto_check

        def process(self):
            if configuracao_f3_visivel(self):
                if not bool(getattr(self, "_display_f3_configuration_pause_active", False)):
                    self._display_f3_configuration_pause_active = True
                    try:
                        self._reset_display_auto_stability(transition=False)
                    except TypeError:
                        try:
                            self._reset_display_auto_stability()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    self._display_auto_last_analysis = None
                    self._display_f3_overlay_analysis_cache_key = None
                    self._display_f3_overlay_analysis_cache = None
                return None

            self._display_f3_configuration_pause_active = False
            return original_process(self)

        DisplayAutomaticCheckF3Mixin._process_display_auto_check = process
        DisplayAutomaticCheckF3Mixin._display_f3_configuration_pause_installed = True

    if not bool(
        getattr(
            DisplayProductionF3Mixin,
            "_display_f3_configuration_preview_pause_installed",
            False,
        )
    ):
        original_preview = DisplayProductionF3Mixin._atualizar_preview_display_f3

        def preview(self):
            if configuracao_f3_visivel(self):
                self.display_f3_after_id = None
                self._agendar_preview_display_f3(F3_CONFIG_BACKGROUND_INTERVAL_MS)
                return None
            return original_preview(self)

        DisplayProductionF3Mixin._atualizar_preview_display_f3 = preview
        DisplayProductionF3Mixin._display_f3_configuration_preview_pause_installed = True

    if not bool(
        getattr(
            DisplayProductionF3Mixin,
            "_display_f3_zero_copy_config_frame_installed",
            False,
        )
    ):
        def frame_for_configuration(self):
            frame = getattr(self, "camera_frame_atual", None)
            if frame is None or getattr(frame, "size", 0) == 0:
                return None
            return frame

        DisplayProductionF3Mixin._obter_frame_para_configuracao_display = (
            frame_for_configuration
        )
        DisplayProductionF3Mixin._display_f3_zero_copy_config_frame_installed = True


def _install_fresh_frame_outer_gate() -> None:
    """Descarta frame repetido antes do matcher físico, não depois dele."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin

    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_outer_fresh_frame_gate_installed", False)):
        return
    original_process = cls._process_display_auto_check

    def process(self):
        if configuracao_f3_visivel(self):
            self._display_f3_outer_last_frame_token = None
            return original_process(self)

        if not bool(getattr(self, "display_f3_ativo", False)):
            self._display_f3_outer_last_frame_token = None
            return original_process(self)

        frame = getattr(self, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            self._display_f3_outer_last_frame_token = None
            return original_process(self)

        try:
            token = self._display_auto_frame_token(frame)
        except Exception:
            token = ("object", id(frame))

        if token == getattr(self, "_display_f3_outer_last_frame_token", None):
            return None

        self._display_f3_outer_last_frame_token = token
        return original_process(self)

    cls._process_display_auto_check = process
    cls._display_f3_outer_fresh_frame_gate_installed = True


def _install_adaptive_preview_cadence() -> None:
    """Evita fila infinita de callbacks quando um ciclo óptico demora."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin

    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_adaptive_preview_cadence_installed", False)):
        return
    original_update = cls._atualizar_preview_display_f3

    def update(self):
        started = time.perf_counter()
        result = original_update(self)
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        self._display_f3_last_cycle_ms = round(elapsed_ms, 2)

        if not bool(getattr(self, "display_f3_ativo", False)):
            return result

        if configuracao_f3_visivel(self):
            target_ms = F3_CONFIG_BACKGROUND_INTERVAL_MS
        else:
            try:
                context = self._display_auto_current_context()
            except Exception:
                context = None
            fast = False
            if isinstance(context, dict):
                try:
                    fast = bool(
                        self._display_auto_is_reference_gate(context)
                        or self._display_auto_is_transient_check(context)
                    )
                except Exception:
                    fast = False
            target_ms = F3_FAST_CYCLE_TARGET_MS if fast else F3_NORMAL_CYCLE_TARGET_MS

        # O método base agenda o próximo callback antes de executar toda a análise.
        # Cancelamos esse agendamento e colocamos o próximo após um pequeno respiro
        # do event loop. Se a análise já excedeu o alvo, ainda há slice mínimo.
        scheduled = getattr(self, "display_f3_after_id", None)
        if scheduled is not None:
            try:
                self.root.after_cancel(scheduled)
            except Exception:
                pass
            self.display_f3_after_id = None

        wait_ms = max(
            F3_MIN_IDLE_SLICE_MS,
            int(round(float(target_ms) - elapsed_ms)),
        )
        self._display_f3_last_idle_slice_ms = int(wait_ms)
        try:
            self._agendar_preview_display_f3(wait_ms)
        except Exception:
            pass
        return result

    cls._atualizar_preview_display_f3 = update
    cls._display_f3_adaptive_preview_cadence_installed = True


def _install_legacy_visual_status_bypass() -> None:
    """Desliga somente o matcher legado cuja saída já é ignorada pelo status único."""
    from src.platform.display_auto_check_runtime import DisplayAutomaticCheckF3Mixin

    cls = DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_f3_legacy_visual_status_bypassed", False)):
        return
    original_preview = cls._atualizar_preview_display_f3

    def preview(self):
        self._display_visual_status_frame_counter = 0
        return original_preview(self)

    cls._atualizar_preview_display_f3 = preview
    cls._display_f3_legacy_visual_status_bypassed = True


def _trim_cache(cache: dict, limit: int) -> None:
    while len(cache) > int(limit):
        try:
            cache.pop(next(iter(cache)))
        except Exception:
            break


def _reference_image_cached(metadata: dict | None):
    if not isinstance(metadata, dict):
        return None
    path = Path(str(metadata.get("image_path") or ""))
    signature = _file_signature(path)
    if signature is None:
        return None
    key = str(path)
    cached = _REFERENCE_IMAGE_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        return None
    _REFERENCE_IMAGE_CACHE[key] = (signature, image)
    _trim_cache(_REFERENCE_IMAGE_CACHE, F3_REFERENCE_CACHE_LIMIT)
    return image


def _small_reference_after_roi(metadata: dict | None, exact_module):
    if not isinstance(metadata, dict):
        return None
    path = Path(str(metadata.get("image_path") or ""))
    signature = _file_signature(path)
    if signature is None:
        return None
    roi = exact_module.reference_roi_module.normalizar_roi_referencia(
        metadata.get("roi")
    )
    roi_key = tuple(sorted((roi or {}).items())) if isinstance(roi, dict) else None
    key = (str(path), signature, roi_key, F3_REFERENCE_COMPARE_WIDTH)
    cached = _REFERENCE_COMPARE_CACHE.get(key)
    if cached is not None:
        return cached

    reference = _reference_image_cached(metadata)
    if reference is None:
        return None
    if roi is not None:
        reference = exact_module.reference_roi_module.recortar_roi_referencia(
            reference,
            roi,
        )
    if reference is None or getattr(reference, "size", 0) == 0:
        return None

    height, width = reference.shape[:2]
    if width > F3_REFERENCE_COMPARE_WIDTH:
        target_width = F3_REFERENCE_COMPARE_WIDTH
        target_height = max(1, int(round(height * target_width / float(width))))
        reference = cv2.resize(
            reference,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
    _REFERENCE_COMPARE_CACHE[key] = reference
    _trim_cache(_REFERENCE_COMPARE_CACHE, F3_REFERENCE_CACHE_LIMIT)
    return reference


def _prepare_current_roi_small(frame, metadata: dict | None, reference_small, exact_module):
    if frame is None or getattr(frame, "size", 0) == 0 or reference_small is None:
        return None
    current = frame
    if current.ndim == 2:
        current = cv2.cvtColor(current, cv2.COLOR_GRAY2BGR)
    elif current.ndim == 3 and current.shape[2] == 4:
        current = cv2.cvtColor(current, cv2.COLOR_BGRA2BGR)
    elif current.ndim != 3 or current.shape[2] != 3:
        return None

    roi = exact_module.reference_roi_module.normalizar_roi_referencia(
        (metadata or {}).get("roi")
    )
    if roi is not None:
        current = exact_module.reference_roi_module.recortar_roi_referencia(
            current,
            roi,
        )
    if current is None or getattr(current, "size", 0) == 0:
        return None

    height, width = reference_small.shape[:2]
    if current.shape[:2] != (height, width):
        current = cv2.resize(
            current,
            (width, height),
            interpolation=cv2.INTER_AREA,
        )
    return current


def _install_exact_reference_hot_path() -> None:
    """Remove I/O JPEG e cópias Full HD do classificador físico por gabarito."""
    import src.platform.display_f3_exact_check_template as exact_module

    if bool(getattr(exact_module, "_display_f3_reference_hot_path_installed", False)):
        return

    def read_reference(metadata: dict | None):
        return _reference_image_cached(metadata)

    def score_reference(frame, metadata: dict | None) -> float | None:
        reference_small = _small_reference_after_roi(metadata, exact_module)
        if reference_small is None:
            return None
        current_small = _prepare_current_roi_small(
            frame,
            metadata,
            reference_small,
            exact_module,
        )
        if current_small is None:
            return None
        return float(
            exact_module.calcular_similaridade_presenca_display(
                reference_small,
                current_small,
            )
        )

    exact_module._read_reference_full = read_reference
    exact_module._score_reference_full_roi = score_reference

    analyzer_cls = exact_module.F3ExactCheckTemplateAnalyzer
    original_reference_context = analyzer_cls._reference_visual_context

    def reference_context(
        self,
        project_name: str,
        check_id: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ):
        metadata = self.presence_store.get(project_name, check_id)
        path = Path(str((metadata or {}).get("image_path") or ""))
        signature = _file_signature(path)
        masks_key = repr(masks)
        key = (
            str(project_name),
            str(check_id),
            int(visual_rotation or 0),
            signature,
            str(project.get("updated_at") or ""),
            masks_key,
        )
        cached = getattr(self, "_display_f3_reference_visual_cache", None)
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == key:
            return cached[1]
        value = original_reference_context(
            self,
            project_name,
            check_id,
            project,
            masks,
            visual_rotation,
        )
        self._display_f3_reference_visual_cache = (key, value)
        return value

    analyzer_cls._reference_visual_context = reference_context

    original_invalidate = analyzer_cls.invalidate_learning_cache

    def invalidate(self):
        self._display_f3_reference_visual_cache = None
        try:
            return original_invalidate(self)
        finally:
            _REFERENCE_COMPARE_CACHE.clear()
            _MASK_REFERENCE_CACHE.clear()

    analyzer_cls.invalidate_learning_cache = invalidate

    exact_module._display_f3_reference_hot_path_installed = True


def _mask_reference_prepared(reference_frame, selection, exact_module):
    if reference_frame is None or getattr(reference_frame, "size", 0) == 0:
        return None
    height, width = reference_frame.shape[:2]
    key = (id(reference_frame), repr(selection), width, height)
    cached = _MASK_REFERENCE_CACHE.get(key)
    if cached is not None:
        return cached

    prepared = exact_module.criar_mascaras_roi(selection, width, height)
    if prepared is None:
        return None
    x1, y1, x2, y2, mask, _inner, _ring = prepared
    reference_roi = reference_frame[y1:y2, x1:x2]
    if (
        reference_roi is None
        or getattr(reference_roi, "size", 0) == 0
        or mask is None
        or int(np.count_nonzero(mask)) <= 0
    ):
        return None

    reference_blur = cv2.GaussianBlur(reference_roi, (3, 3), 0)
    reference_hsv = cv2.cvtColor(reference_blur, cv2.COLOR_BGR2HSV)
    ref_bgr = reference_blur[mask].astype(np.float32)
    ref_s = reference_hsv[:, :, 1][mask].astype(np.float32)
    ref_v = reference_hsv[:, :, 2][mask].astype(np.float32)
    value = {
        "bounds": (x1, y1, x2, y2),
        "mask": mask,
        "ref_bgr": ref_bgr,
        "ref_s": ref_s,
        "ref_v": ref_v,
        "reference_v_mean": float(np.mean(ref_v)),
    }
    _MASK_REFERENCE_CACHE[key] = value
    _trim_cache(_MASK_REFERENCE_CACHE, F3_MASK_REFERENCE_CACHE_LIMIT)
    return value


def _install_exact_mask_reference_cache() -> None:
    """Pré-calcula a metade fixa da comparação de cada máscara do CHECK."""
    import src.platform.display_f3_exact_check_template as exact_module

    if bool(getattr(exact_module, "_display_f3_mask_hot_path_installed", False)):
        return

    def compare(current_frame, reference_frame, selection) -> dict | None:
        if (
            current_frame is None
            or getattr(current_frame, "size", 0) == 0
            or reference_frame is None
            or getattr(reference_frame, "size", 0) == 0
        ):
            return None

        height, width = reference_frame.shape[:2]
        if current_frame.shape[:2] != (height, width):
            current_frame = cv2.resize(
                current_frame,
                (width, height),
                interpolation=cv2.INTER_AREA,
            )

        fixed = _mask_reference_prepared(reference_frame, selection, exact_module)
        if fixed is None:
            return None
        x1, y1, x2, y2 = fixed["bounds"]
        mask = fixed["mask"]
        current_roi = current_frame[y1:y2, x1:x2]
        if current_roi is None or getattr(current_roi, "size", 0) == 0:
            return None

        current_blur = cv2.GaussianBlur(current_roi, (3, 3), 0)
        current_hsv = cv2.cvtColor(current_blur, cv2.COLOR_BGR2HSV)
        cur_bgr = current_blur[mask].astype(np.float32)
        cur_s = current_hsv[:, :, 1][mask].astype(np.float32)
        cur_v = current_hsv[:, :, 2][mask].astype(np.float32)

        ref_bgr = fixed["ref_bgr"]
        ref_s = fixed["ref_s"]
        ref_v = fixed["ref_v"]
        bgr_mae = float(np.mean(np.abs(cur_bgr - ref_bgr)) / 255.0)
        s_mae = float(np.mean(np.abs(cur_s - ref_s)) / 255.0)
        v_mae = float(np.mean(np.abs(cur_v - ref_v)) / 255.0)

        pixel_similarity = 1.0 - (
            (0.30 * bgr_mae)
            + (0.20 * s_mae)
            + (0.50 * v_mae)
        )
        reference_v_mean = float(fixed["reference_v_mean"])
        current_v_mean = float(np.mean(cur_v))
        energy_similarity = 1.0 - min(
            1.0,
            abs(current_v_mean - reference_v_mean) / 255.0,
        )
        similarity = max(
            0.0,
            min(
                1.0,
                float((0.75 * pixel_similarity) + (0.25 * energy_similarity)),
            ),
        )
        return {
            "similarity": round(similarity, 4),
            "pixel_similarity": round(float(pixel_similarity), 4),
            "energy_similarity": round(float(energy_similarity), 4),
            "reference_v_mean": round(reference_v_mean, 4),
            "current_v_mean": round(current_v_mean, 4),
        }

    exact_module.comparar_mascara_com_gabarito_f3 = compare
    exact_module._display_f3_mask_hot_path_installed = True


def _interaction_due(last_time: float, now: float, interval: float) -> bool:
    elapsed = float(now) - float(last_time or 0.0)
    return elapsed + F3_TIME_EPSILON >= max(0.0, float(interval))


def _install_mask_editor_hot_path() -> None:
    import src.platform.display_editor_performance as performance_module
    import src.platform.display_mask_editor as mask_module
    from src.platform.display_mask_editor_interactions import (
        DisplayMaskEditorInteractionMixin,
    )

    cls = mask_module.DisplayMaskEditorWindow
    if bool(getattr(cls, "_display_f3_final_hot_path_installed", False)):
        return

    original_leave = DisplayMaskEditorInteractionMixin._leave

    def merge(self, changed):
        by_id = {mask_module._id(mask): mask for mask in changed}
        self.masks = [
            by_id.get(mask_module._id(mask), mask)
            for mask in self.snapshot
        ]

    def draw_magnifier(self) -> None:
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        try:
            canvas.delete(F3_MAGNIFIER_TAG)
        except Exception:
            pass

        frame = getattr(self, "frame", None)
        pointer_canvas = getattr(self, "pointer_canvas", None)
        pointer_master = getattr(self, "pointer_master", None)
        if (
            frame is None
            or getattr(frame, "size", 0) == 0
            or pointer_canvas is None
            or pointer_master is None
        ):
            return

        x, y = pointer_master
        radius = 28
        x1, x2 = max(0, x - radius), min(self.master_width, x + radius)
        y1, y2 = max(0, y - radius), min(self.master_height, y + radius)
        crop = frame[y1:y2, x1:x2]
        if getattr(crop, "size", 0) == 0:
            return

        size = int(mask_module.MAGNIFIER_SIZE_PX)
        image = cv2.resize(crop, (size, size), interpolation=cv2.INTER_NEAREST)
        self._magnifier = performance_module._photo_from_bgr_fast(image)
        if self._magnifier is None:
            return

        canvas_width = max(1, int(canvas.winfo_width()))
        left = canvas_width - size - 18
        if pointer_canvas[0] > left - 20:
            left = 18
        top = 42
        canvas.create_image(
            left,
            top,
            image=self._magnifier,
            anchor="nw",
            tags=(F3_MAGNIFIER_TAG,),
        )
        canvas.create_rectangle(
            left,
            top,
            left + size,
            top + size,
            outline="#38BDF8",
            width=2,
            tags=(F3_MAGNIFIER_TAG,),
        )
        try:
            canvas.tag_raise(F3_MAGNIFIER_TAG)
        except Exception:
            pass

    def motion(self, event):
        now = time.perf_counter()
        last = float(getattr(self, "_display_f3_last_light_motion_s", 0.0) or 0.0)
        if not _interaction_due(last, now, F3_MASK_POINTER_INTERVAL_S):
            return None
        self._display_f3_last_light_motion_s = now

        self.pointer_canvas = (event.x, event.y)
        self.pointer_master = self._to_master(event.x, event.y)
        if self.freeform and self.pointer_master:
            self.freeform_mouse = self.pointer_master
            self.redraw()
        else:
            self._draw_magnifier()
        return None

    def leave(self, event=None):
        self.pointer_canvas = None
        self.pointer_master = None
        try:
            self.canvas.delete(F3_MAGNIFIER_TAG)
        except Exception:
            pass
        if self.freeform:
            return original_leave(self, event)
        return None

    def drag(self, event):
        now = time.perf_counter()
        last = float(getattr(self, "_display_f3_last_drag_redraw_s", 0.0) or 0.0)
        allow_redraw = _interaction_due(
            last,
            now,
            F3_MASK_DRAG_REDRAW_INTERVAL_S,
        )
        if allow_redraw:
            self._display_f3_last_drag_redraw_s = now

        previous = bool(getattr(self, "_odin_editor_suppress_redraw", False))
        self._odin_editor_suppress_redraw = previous or not allow_redraw
        try:
            return DisplayMaskEditorInteractionMixin._drag(self, event)
        finally:
            self._odin_editor_suppress_redraw = previous

    cls._merge = merge
    cls._draw_magnifier = draw_magnifier
    cls._motion = motion
    cls._leave = leave
    cls._drag = drag
    cls._display_f3_final_hot_path_installed = True


def instalar_performance_final_display_f3() -> None:
    _install_repository_caches()
    _install_configuration_runtime_pause()
    _install_legacy_visual_status_bypass()
    _install_exact_reference_hot_path()
    _install_exact_mask_reference_cache()
    _install_fresh_frame_outer_gate()
    # Cadência/scheduling pertencem ao F3RuntimeCoordinator (Etapa 4).
    _install_mask_editor_hot_path()
