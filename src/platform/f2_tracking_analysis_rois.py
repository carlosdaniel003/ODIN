from __future__ import annotations

"""Usa as ROIs rastreadas também no julgamento produtivo da Produção F2.

O rastreamento visual já projeta o contorno e as máscaras do projeto sobre a
posição física atual da placa. Esta camada faz a inspeção usar exatamente essa
mesma geometria quando ``Ativar rastreamento automático de objetos`` está ativo.

Contrato:
- tracking desligado: nenhum comportamento é alterado;
- tracking ligado + lock válido: Enter/GPIO e análise automática usam o frame
  bruto atual e as ROIs transformadas para a pose rastreada;
- tracking ligado sem lock: a análise de LEDs não volta silenciosamente para as
  máscaras fixas do projeto. O automático continua processando presença/rearme,
  mas sem estados de LED; Enter/GPIO aguardam um lock válido;
- referências e ROIs persistidas nunca são modificadas.
"""

from src.core.operation_engine import OperationResult
from src.platform.f2_automatic_presence_cycle_policy import (
    F2AutomaticPresenceCyclePolicyMixin,
)
from src.platform.f2_object_tracking import F2ObjectTrackingMixin
from src.platform.f2_object_tracking_visual_overlay import (
    inverter_matriz_rastreamento_f2,
    transformar_rois_para_frame_atual_f2,
)


_PATCH_INSTALADO = False


def _frame_valido(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _tracking_ativo(app) -> bool:
    checker = getattr(app, "_f2_tracking_enabled", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def _tracking_com_lock(app) -> bool:
    status = getattr(app, "_f2_object_tracking_last_status", {})
    tracker = getattr(app, "_f2_object_tracker", None)
    return bool(
        isinstance(status, dict)
        and status.get("locked")
        and tracker is not None
        and getattr(tracker, "last_matrix", None) is not None
    )


def _rois_base_analise_f2(app):
    """Mantém a geometria canônica mesmo durante overrides transitórios."""
    depth = int(getattr(app, "_f2_tracking_analysis_override_depth", 0) or 0)
    current = tuple(getattr(app, "operacao_leds_preview", ()) or ())

    if depth <= 0 and current:
        app._f2_tracking_analysis_base_rois = current

    cached = tuple(getattr(app, "_f2_tracking_analysis_base_rois", ()) or ())
    return cached if cached else current


def obter_rois_rastreadas_analise_f2(app, raw_frame):
    """Projeta as ROIs canônicas para a posição física atual da placa."""
    if not _tracking_ativo(app) or not _frame_valido(raw_frame):
        return ()
    if not _tracking_com_lock(app):
        return ()

    tracker = getattr(app, "_f2_object_tracker", None)
    reference_to_current = inverter_matriz_rastreamento_f2(
        getattr(tracker, "last_matrix", None)
    )
    if reference_to_current is None:
        return ()

    base_rois = _rois_base_analise_f2(app)
    if not base_rois:
        return ()

    height, width = raw_frame.shape[:2]
    transformed = transformar_rois_para_frame_atual_f2(
        base_rois,
        reference_to_current,
        int(width),
        int(height),
    )
    if len(transformed) != len(base_rois):
        return ()
    return tuple(transformed)


def _preparar_rois_para_engine(engine, raw_frame, tracked_rois):
    if engine is None or not getattr(engine, "ready", False):
        return ()
    if not _frame_valido(raw_frame) or not tracked_rois:
        return ()

    height, width = raw_frame.shape[:2]
    prepare_led = getattr(engine, "_prepare_led", None)
    if not callable(prepare_led):
        return ()

    prepared = []
    for led in tuple(tracked_rois or ()):
        try:
            item = prepare_led(led, int(width), int(height))
        except Exception:
            return ()
        if item is None:
            return ()
        prepared.append(item)

    if len(prepared) != len(tuple(tracked_rois or ())):
        return ()
    return tuple(prepared)


def _resultado_sem_rois() -> OperationResult:
    # Resultado neutro para o monitoramento automático enquanto não há lock.
    # Sem ``results`` não existe ACESO e, portanto, nunca há disparo por LED.
    return OperationResult(
        ok=False,
        failed_led_ids=(),
        results=(),
        elapsed_seconds=0.0,
    )


def _publicar_aguardando_lock(app) -> None:
    window = getattr(app, "operacao_window", None)
    setter = getattr(window, "set_preview_status", None)
    if not callable(setter):
        return
    try:
        setter(
            "RASTREAMENTO ATIVO • AGUARDANDO LOCK PARA ANALISAR",
            "#FBBF24",
        )
    except Exception:
        pass


def _cachear_frame_e_rois_rastreadas(app, raw_frame) -> None:
    app._f2_tracking_analysis_raw_frame = raw_frame
    app._f2_tracking_analysis_frame_id = getattr(
        app,
        "camera_ultimo_frame_id",
        None,
    )

    if not _tracking_com_lock(app):
        app._f2_tracking_analysis_rois = ()
        return

    app._f2_tracking_analysis_rois = obter_rois_rastreadas_analise_f2(
        app,
        raw_frame,
    )


def _dados_rastreados_atuais(app):
    raw_frame = getattr(app, "_f2_tracking_analysis_raw_frame", None)
    tracked_rois = tuple(
        getattr(app, "_f2_tracking_analysis_rois", ()) or ()
    )
    if not _frame_valido(raw_frame) or not tracked_rois:
        return None, ()
    return raw_frame, tracked_rois


def _executar_dispatch_com_rois_rastreadas(app, raw_frame, tracked_rois):
    engine = getattr(app, "operacao_engine", None)
    prepared = _preparar_rois_para_engine(engine, raw_frame, tracked_rois)
    if not prepared:
        _publicar_aguardando_lock(app)
        return None

    original_frame = getattr(app, "camera_frame_atual", None)
    original_preview_rois = getattr(app, "operacao_leds_preview", None)
    original_prepared = getattr(engine, "_prepared_leds", ())
    original_width = getattr(engine, "_frame_width", 0)
    original_height = getattr(engine, "_frame_height", 0)
    depth = int(getattr(app, "_f2_tracking_analysis_override_depth", 0) or 0)

    height, width = raw_frame.shape[:2]
    app._f2_tracking_analysis_override_depth = depth + 1
    app.camera_frame_atual = raw_frame
    app.operacao_leds_preview = list(tracked_rois)
    engine._prepared_leds = prepared
    engine._frame_width = int(width)
    engine._frame_height = int(height)

    try:
        # Pula somente a implementação antiga do F2ObjectTrackingMixin, que
        # alinhava o frame para as máscaras fixas. Todo o restante da cadeia
        # (guards, ciclo automático, contadores, snapshot e UI) permanece igual.
        return super(F2ObjectTrackingMixin, app).disparar_inspecao_operacao()
    finally:
        app.camera_frame_atual = original_frame
        app.operacao_leds_preview = original_preview_rois
        engine._prepared_leds = original_prepared
        engine._frame_width = original_width
        engine._frame_height = original_height
        app._f2_tracking_analysis_override_depth = depth


def instalar_analise_em_rois_rastreadas_f2() -> None:
    """Instala a autoridade de ROIs móveis somente quando o tracking está ativo."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    # 1) Memoriza o frame bruto que originou cada lock. O método original ainda
    # produz o frame alinhado usado pelos classificadores de presença existentes.
    tracking_frame_atual = F2ObjectTrackingMixin._f2_tracking_frame
    if not bool(getattr(tracking_frame_atual, "_odin_f2_analysis_roi_cache", False)):
        tracking_frame_anterior = tracking_frame_atual

        def tracking_frame_com_cache(self, frame):
            result = tracking_frame_anterior(self, frame)
            if _tracking_ativo(self) and _frame_valido(frame):
                _cachear_frame_e_rois_rastreadas(self, frame)
            else:
                self._f2_tracking_analysis_raw_frame = None
                self._f2_tracking_analysis_rois = ()
            return result

        tracking_frame_com_cache._odin_f2_analysis_roi_cache = True
        tracking_frame_com_cache._odin_f2_analysis_roi_cache_base = (
            tracking_frame_anterior
        )
        F2ObjectTrackingMixin._f2_tracking_frame = tracking_frame_com_cache

    # 2) Enter/GPIO: força um lock atualizado e chama a cadeia produtiva com o
    # frame bruto + PreparedLed gerados das máscaras móveis.
    dispatch_atual = F2ObjectTrackingMixin.disparar_inspecao_operacao
    if not bool(getattr(dispatch_atual, "_odin_f2_tracked_roi_dispatch", False)):
        dispatch_anterior = dispatch_atual

        def disparar_com_rois_rastreadas(self):
            if not _tracking_ativo(self):
                return dispatch_anterior(self)

            depth_tracking = int(
                getattr(self, "_f2_object_tracking_override_depth", 0) or 0
            )
            if depth_tracking > 0:
                raw_frame, tracked_rois = _dados_rastreados_atuais(self)
            else:
                raw_frame = getattr(self, "camera_frame_atual", None)
                if not _frame_valido(raw_frame):
                    return dispatch_anterior(self)
                # Atualiza matriz/pose no próprio frame que será julgado. O frame
                # alinhado retornado não é usado nesta nova rota de análise.
                try:
                    self._f2_tracking_frame(raw_frame)
                except Exception:
                    pass
                raw_frame, tracked_rois = _dados_rastreados_atuais(self)

            if not _frame_valido(raw_frame) or not tracked_rois:
                _publicar_aguardando_lock(self)
                return None

            return _executar_dispatch_com_rois_rastreadas(
                self,
                raw_frame,
                tracked_rois,
            )

        disparar_com_rois_rastreadas._odin_f2_tracked_roi_dispatch = True
        disparar_com_rois_rastreadas._odin_f2_tracked_roi_dispatch_base = (
            dispatch_anterior
        )
        F2ObjectTrackingMixin.disparar_inspecao_operacao = (
            disparar_com_rois_rastreadas
        )

    # 3) Automático: mantém presença/rearme no frame alinhado já existente, mas
    # intercepta somente OperationEngine.analyze() para que o diagnóstico dos LEDs
    # use o frame bruto e as mesmas ROIs rastreadas exibidas na câmera.
    auto_atual = F2AutomaticPresenceCyclePolicyMixin._f2_auto_analyze_current_frame
    if not bool(getattr(auto_atual, "_odin_f2_tracked_roi_auto", False)):
        auto_anterior = auto_atual

        def auto_com_rois_rastreadas(self):
            if not _tracking_ativo(self):
                return auto_anterior(self)

            engine = getattr(self, "operacao_engine", None)
            if engine is None:
                return auto_anterior(self)

            raw_frame, tracked_rois = _dados_rastreados_atuais(self)
            original_analyze = getattr(engine, "analyze", None)
            if not callable(original_analyze):
                return auto_anterior(self)

            def analyze_tracking(_aligned_frame, *args, **kwargs):
                if not _frame_valido(raw_frame) or not tracked_rois:
                    return _resultado_sem_rois()

                prepared = _preparar_rois_para_engine(
                    engine,
                    raw_frame,
                    tracked_rois,
                )
                if not prepared:
                    return _resultado_sem_rois()

                original_prepared = getattr(engine, "_prepared_leds", ())
                original_width = getattr(engine, "_frame_width", 0)
                original_height = getattr(engine, "_frame_height", 0)
                height, width = raw_frame.shape[:2]
                engine._prepared_leds = prepared
                engine._frame_width = int(width)
                engine._frame_height = int(height)
                try:
                    return original_analyze(raw_frame, *args, **kwargs)
                finally:
                    engine._prepared_leds = original_prepared
                    engine._frame_width = original_width
                    engine._frame_height = original_height

            try:
                engine.analyze = analyze_tracking
            except Exception:
                return auto_anterior(self)

            try:
                return auto_anterior(self)
            finally:
                try:
                    engine.analyze = original_analyze
                except Exception:
                    pass

        auto_com_rois_rastreadas._odin_f2_tracked_roi_auto = True
        auto_com_rois_rastreadas._odin_f2_tracked_roi_auto_base = auto_anterior
        F2AutomaticPresenceCyclePolicyMixin._f2_auto_analyze_current_frame = (
            auto_com_rois_rastreadas
        )

    _PATCH_INSTALADO = True
