from __future__ import annotations

import tkinter as tk

import src.platform.raspberry_pi3_profile as raspberry_pi3_profile
from src.platform.analysis_response_metrics import (
    AnalysisResponseMetricsMixin,
)
from src.platform.automatic_led_detection import (
    AutomaticLedDetectionMixin,
)
from src.platform.camera_advanced_config import (
    instalar_normalizacao_config_repository,
)
from src.platform.camera_live_settings import (
    CameraLiveSettingsMixin,
)
from src.platform.camera_screenshot import (
    CameraScreenshotMixin,
)
from src.platform.camera_selection import (
    CameraSelectionMixin,
)
from src.platform.camera_stability_runtime import (
    RaspberryCameraStabilityMixin,
)
from src.platform.display_auto_check_runtime import (
    DisplayAutomaticCheckF3Mixin,
)
from src.platform.display_awake_runtime import (
    LinuxDisplayAwakeMixin,
)
from src.platform.display_check_presence_reference import (
    instalar_referencia_presenca_check_display,
)
from src.platform.display_f3_check_transition_guard import (
    instalar_guard_transicao_check_display_f3,
)
from src.platform.display_f3_exact_check_template import (
    instalar_gabarito_exato_checks_display_f3,
)
from src.platform.display_f3_fast_expected_gate import (
    instalar_gate_rapido_check_esperado_display_f3,
)
from src.platform.display_f3_live_runtime_fix import (
    instalar_runtime_ao_vivo_display_f3,
)
from src.platform.display_f3_mask_status import (
    instalar_status_mascaras_display_f3,
)
from src.platform.display_f3_operational_status import (
    instalar_status_operacional_display_f3,
)
from src.platform.display_f3_optical_power_reconciliation import (
    instalar_reconciliacao_optica_estado_fisico_display_f3,
)
from src.platform.display_f3_physical_learning_policy import (
    instalar_politica_fisica_e_aprendizado_display_f3,
)
from src.platform.display_f3_physical_state_fix import (
    instalar_correcao_estado_fisico_display_f3,
)
from src.platform.display_f3_reference_authority_bridge import (
    instalar_ponte_autoridade_referencias_display_f3,
)
from src.platform.display_f3_reference_authority_fix import (
    instalar_autoridade_referencias_display_f3,
)
from src.platform.display_f3_same_mask_reference_fix import (
    instalar_referencias_por_mesma_mascara_display_f3,
)
from src.platform.display_f3_status_layout_fix import (
    instalar_layout_status_f3_estavel,
)
from src.platform.display_f3_strict_mask_conformity import (
    instalar_conformidade_estrita_mascaras_display_f3,
)
from src.platform.display_production_f3 import (
    DisplayProductionF3Mixin,
)
from src.platform.display_reference_roi import (
    instalar_roi_referencias_display_f3,
)
from src.platform.display_theme import (
    DISPLAY_INK,
    DISPLAY_YELLOW,
    DISPLAY_YELLOW_DARK,
    DisplayThemeMixin,
)
from src.platform.display_visual_reference_status import (
    instalar_status_referencias_visuais_display,
)
from src.platform.f2_automatic_analysis import (
    F2AutomaticAnalysisMixin,
)
from src.platform.f2_automatic_cycle_guard import (
    F2AutomaticCycleGuardMixin,
)
from src.platform.f2_automatic_presence_cycle_policy import (
    F2AutomaticPresenceCyclePolicyMixin,
)
from src.platform.f2_board_status_display import (
    F2BoardStatusDisplayMixin,
)
from src.platform.fixed_mask_geometry_guard import (
    FixedMaskGeometryGuardMixin,
    instalar_repositorio_mascaras_absolutas,
)
from src.platform.freeform_live_camera_geometry import (
    FreeformLiveCameraGeometryMixin,
)
from src.platform.freeform_segment_persistence import (
    instalar_persistencia_segmento_livre,
)
from src.platform.freeform_segment_roi import (
    FreeformSegmentDrawingMixin,
)
from src.platform.fullscreen_led_selection import (
    FullscreenLedSelectionMixin,
)
from src.platform.gpio_raspberry_app import (
    GPIOEnabledRaspberryPi3ODINApp,
)
from src.platform.led_mask_resolution_sync import (
    ResolutionSynchronizedLedMasksMixin,
)
from src.platform.led_project_preview import (
    LedProjectPreviewMixin,
)
from src.platform.led_project_preview_store import (
    instalar_preview_projeto_led_store,
)
from src.platform.led_project_repository import (
    instalar_repositorio_projetos_led,
)
from src.platform.linux_f2_fixed_resolution import (
    LinuxF2FixedResolutionMixin,
)
from src.platform.live_fixed_full_hd_camera_service import (
    LiveFixedFullHdCameraService,
)
from src.platform.native_resolution_config import (
    NativeResolutionConfigMixin,
)
from src.platform.neutral_project_startup import (
    NeutralProjectStartupMixin,
)
from src.platform.project_mask_geometry_anchor import (
    ProjectMaskGeometryAnchorMixin,
)
from src.platform.project_master_resolution import (
    ProjectMasterResolutionMixin,
)
from src.platform.project_master_resolution_guard import (
    ProjectMasterResolutionGuardMixin,
)
from src.platform.raspberry_enter_trigger import (
    RaspberryEnterTriggerMixin,
)
from src.platform.raspberry_pi3_settings import (
    OPERATION_PREVIEW_HEIGHT,
    OPERATION_PREVIEW_WIDTH,
)
from src.platform.raspberry_runtime_fixes import (
    RaspberryRuntimeFixesMixin,
)
from src.platform.reference_capture import (
    ReferenceCaptureMixin,
)
from src.platform.reference_project_sets import (
    ProjectReferenceSetsMixin,
)
from src.platform.segment_display_operation_window import (
    SegmentDisplayOperationWindow,
)
from src.platform.segment_display_roi_editor import (
    SegmentDisplayRoiEditorMixin,
)
from src.platform.segment_display_runtime import (
    SegmentDisplayRuntimeMixin,
)
from src.platform.segment_project_geometry_persistence import (
    SegmentProjectGeometryPersistenceMixin,
    instalar_preservacao_segmentos_resolution_sync,
)
from src.platform.windows_camera_debug import (
    iniciar_debug_periodico_camera_windows,
    instalar_debug_camera_windows,
)
from src.platform.windows_camera_handoff import (
    instalar_handoff_camera_windows,
)


class RaspberryPi3ProductionApp(
    LinuxDisplayAwakeMixin,
    DisplayThemeMixin,
    DisplayAutomaticCheckF3Mixin,
    DisplayProductionF3Mixin,
    F2BoardStatusDisplayMixin,
    F2AutomaticPresenceCyclePolicyMixin,
    F2AutomaticCycleGuardMixin,
    F2AutomaticAnalysisMixin,
    CameraSelectionMixin,
    LinuxF2FixedResolutionMixin,
    ProjectMasterResolutionGuardMixin,
    NeutralProjectStartupMixin,
    ProjectMasterResolutionMixin,
    CameraScreenshotMixin,
    CameraLiveSettingsMixin,
    LedProjectPreviewMixin,
    ProjectReferenceSetsMixin,
    ReferenceCaptureMixin,
    FreeformLiveCameraGeometryMixin,
    FreeformSegmentDrawingMixin,
    FullscreenLedSelectionMixin,
    ProjectMaskGeometryAnchorMixin,
    FixedMaskGeometryGuardMixin,
    SegmentProjectGeometryPersistenceMixin,
    AnalysisResponseMetricsMixin,
    SegmentDisplayRuntimeMixin,
    SegmentDisplayRoiEditorMixin,
    ResolutionSynchronizedLedMasksMixin,
    NativeResolutionConfigMixin,
    RaspberryCameraStabilityMixin,
    RaspberryRuntimeFixesMixin,
    RaspberryEnterTriggerMixin,
    AutomaticLedDetectionMixin,
    GPIOEnabledRaspberryPi3ODINApp,
):
    """Perfil final do display com ROI circular e segmentos convencionais/livres."""

    def __init__(self, root: tk.Tk) -> None:
        raspberry_pi3_profile.RaspberryPi3CameraService = LiveFixedFullHdCameraService
        instalar_handoff_camera_windows()
        instalar_debug_camera_windows()
        instalar_normalizacao_config_repository()
        instalar_persistencia_segmento_livre()
        instalar_repositorio_projetos_led()
        instalar_preview_projeto_led_store()
        instalar_repositorio_mascaras_absolutas()
        instalar_preservacao_segmentos_resolution_sync()
        instalar_referencia_presenca_check_display()
        instalar_status_referencias_visuais_display()
        instalar_layout_status_f3_estavel()
        instalar_status_operacional_display_f3()
        instalar_guard_transicao_check_display_f3()
        instalar_roi_referencias_display_f3()
        instalar_correcao_estado_fisico_display_f3()
        instalar_reconciliacao_optica_estado_fisico_display_f3()
        instalar_runtime_ao_vivo_display_f3()
        instalar_status_mascaras_display_f3()
        instalar_autoridade_referencias_display_f3()
        instalar_ponte_autoridade_referencias_display_f3()
        instalar_referencias_por_mesma_mascara_display_f3()
        instalar_politica_fisica_e_aprendizado_display_f3()
        instalar_gabarito_exato_checks_display_f3()
        # A foto exata do CHECK permanece disponivel para diagnostico/presenca,
        # mas a ultima autoridade produtiva passa a ser o gabarito configurado
        # por mascara, sem auto-referencia da propria foto do CHECK.
        instalar_conformidade_estrita_mascaras_display_f3()
        instalar_gate_rapido_check_esperado_display_f3()
        super().__init__(root)
        iniciar_debug_periodico_camera_windows(self)

    def _tem_referencia_pouca_luz_ativa(self) -> bool:
        grupos = getattr(self, "_referencias_ativas_por_tipo", None)
        if isinstance(grupos, dict):
            return bool(grupos.get("pouca_luz"))
        return getattr(self, "features_referencia_pouca_luz", None) is not None

    def preparar_tela_operacao(self) -> None:
        resultado = super().preparar_tela_operacao()
        self.operacao_engine.definir_diagnostico_pouca_luz_habilitado(
            self._tem_referencia_pouca_luz_ativa()
        )
        return resultado

    def _instalar_tela_operacao(self) -> None:
        self.operacao_window = SegmentDisplayOperationWindow(
            root=self.root,
            on_trigger=self.disparar_inspecao_operacao,
            on_close=self.fechar_tela_operacao,
            preview_width=OPERATION_PREVIEW_WIDTH,
            preview_height=OPERATION_PREVIEW_HEIGHT,
        )

        self.root.bind(
            "<F2>",
            lambda _event: self.abrir_tela_operacao(),
            add="+",
        )

        parent = getattr(self.view, "frame_topo_direita", self.root)
        self.botao_operacao = tk.Button(
            parent,
            text="PRODUÇÃO  F2",
            command=self.abrir_tela_operacao,
            font=("DejaVu Sans", 10, "bold"),
            bg=DISPLAY_YELLOW,
            fg=DISPLAY_INK,
            activebackground=DISPLAY_YELLOW_DARK,
            activeforeground=DISPLAY_INK,
            relief="flat",
            bd=0,
            padx=16,
            pady=8,
            cursor="hand2",
        )

        if parent is self.root:
            self.botao_operacao.place(
                relx=1.0,
                x=-18,
                y=16,
                anchor="ne",
            )
            self.botao_operacao.lift()
        else:
            self.botao_operacao.pack(
                side=tk.RIGHT,
                padx=(0, 8),
                pady=18,
            )
