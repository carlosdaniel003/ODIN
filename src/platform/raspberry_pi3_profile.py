from src.platform.raspberry_pi3_settings import CAMERA_FPS, CAMERA_HEIGHT, CAMERA_WIDTH, FRAME_INTERVAL_MS


def aplicar_perfil_raspberry_pi3() -> None:
    import src.app as app

    agendar_original = app.ODINApp.agendar_proximo_frame_camera

    def obter_parametros(self):
        return CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS

    def agendar(self, atraso_ms=FRAME_INTERVAL_MS):
        return agendar_original(self, atraso_ms)

    def paineis_sob_demanda(self, forcar=False):
        return None

    app.CAMERA_LARGURA_DESEJADA = CAMERA_WIDTH
    app.CAMERA_ALTURA_DESEJADA = CAMERA_HEIGHT
    app.CAMERA_FPS_DESEJADO = CAMERA_FPS
    app.ODINApp.obter_parametros_camera_dinamicos = obter_parametros
    app.ODINApp.agendar_proximo_frame_camera = agendar
    app.ODINApp.atualizar_renderizacoes_camera_se_necessario = paineis_sob_demanda
