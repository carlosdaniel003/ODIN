from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import cv2


PASTA_SAIDA = Path(__file__).resolve().parent / "diagnostico_camera"
INDICES = (0, 1, 2, 3, 4, 5)
TEMPO_LIMITE_POR_TESTE_S = 6
TENTATIVAS_LEITURA = 20


def obter_backends() -> list[tuple[str, int]]:
    backends: list[tuple[str, int]] = []

    if hasattr(cv2, "CAP_DSHOW"):
        backends.append(("DSHOW", cv2.CAP_DSHOW))

    if hasattr(cv2, "CAP_MSMF"):
        backends.append(("MSMF", cv2.CAP_MSMF))

    backends.append(("AUTO", cv2.CAP_ANY))
    return backends


def testar_camera(
    indice: int,
    nome_backend: str,
    backend: int,
    fila: mp.Queue,
) -> None:
    captura = None

    try:
        if backend == cv2.CAP_ANY:
            captura = cv2.VideoCapture(indice)
        else:
            captura = cv2.VideoCapture(indice, backend)

        if captura is None or not captura.isOpened():
            fila.put(
                {
                    "indice": indice,
                    "backend": nome_backend,
                    "abriu": False,
                    "frame": False,
                    "mensagem": "dispositivo não abriu",
                }
            )
            return

        frame_valido = None

        for _ in range(TENTATIVAS_LEITURA):
            sucesso, frame = captura.read()

            if (
                sucesso
                and frame is not None
                and getattr(frame, "size", 0) > 0
            ):
                frame_valido = frame
                break

            time.sleep(0.05)

        if frame_valido is None:
            fila.put(
                {
                    "indice": indice,
                    "backend": nome_backend,
                    "abriu": True,
                    "frame": False,
                    "mensagem": "abriu, mas não entregou frame",
                }
            )
            return

        altura, largura = frame_valido.shape[:2]
        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        caminho_frame = (
            PASTA_SAIDA
            / f"camera_indice_{indice}_{nome_backend}.jpg"
        )
        cv2.imwrite(str(caminho_frame), frame_valido)

        fila.put(
            {
                "indice": indice,
                "backend": nome_backend,
                "abriu": True,
                "frame": True,
                "largura": largura,
                "altura": altura,
                "arquivo": str(caminho_frame),
                "mensagem": "OK",
            }
        )
    except Exception as erro:
        fila.put(
            {
                "indice": indice,
                "backend": nome_backend,
                "abriu": False,
                "frame": False,
                "mensagem": (
                    f"{type(erro).__name__}: {erro}"
                ),
            }
        )
    finally:
        if captura is not None:
            try:
                captura.release()
            except Exception:
                pass


def executar_teste(
    indice: int,
    nome_backend: str,
    backend: int,
) -> dict:
    fila: mp.Queue = mp.Queue()
    processo = mp.Process(
        target=testar_camera,
        args=(indice, nome_backend, backend, fila),
        daemon=True,
    )
    processo.start()
    processo.join(TEMPO_LIMITE_POR_TESTE_S)

    if processo.is_alive():
        processo.terminate()
        processo.join(timeout=1)
        return {
            "indice": indice,
            "backend": nome_backend,
            "abriu": False,
            "frame": False,
            "mensagem": (
                f"travou por mais de "
                f"{TEMPO_LIMITE_POR_TESTE_S}s"
            ),
        }

    if not fila.empty():
        return fila.get()

    return {
        "indice": indice,
        "backend": nome_backend,
        "abriu": False,
        "frame": False,
        "mensagem": "processo terminou sem resultado",
    }


def main() -> int:
    print("=" * 72)
    print("DIAGNÓSTICO DE CÂMERAS — ODIN")
    print("=" * 72)
    print(f"Python: {sys.version.split()[0]}")
    print(f"OpenCV: {cv2.__version__}")
    print(f"Saída: {PASTA_SAIDA}")
    print()
    print(
        "Feche antes o aplicativo Câmera do Windows, Teams, navegador, "
        "OBS e qualquer programa que possa estar usando a câmera."
    )
    print()

    resultados: list[dict] = []

    for indice in INDICES:
        for nome_backend, backend in obter_backends():
            print(
                f"Testando índice {indice} com {nome_backend}...",
                flush=True,
            )
            resultado = executar_teste(
                indice,
                nome_backend,
                backend,
            )
            resultados.append(resultado)

            if resultado.get("frame"):
                print(
                    "  OK — "
                    f"{resultado['largura']}x"
                    f"{resultado['altura']} — "
                    f"{resultado['arquivo']}"
                )
            else:
                print(f"  FALHA — {resultado['mensagem']}")

    cameras_validas = [
        resultado
        for resultado in resultados
        if resultado.get("frame")
    ]

    print()
    print("=" * 72)

    if not cameras_validas:
        print("NENHUMA CÂMERA ENTREGOU FRAME AO OPENCV.")
        print()
        print(
            "Isso indica índice incorreto, câmera ocupada por outro "
            "programa, permissão do Windows ou incompatibilidade do driver."
        )
        return 1

    print("COMBINAÇÕES QUE FUNCIONARAM:")
    for resultado in cameras_validas:
        print(
            f"- índice {resultado['indice']} / "
            f"{resultado['backend']} / "
            f"{resultado['largura']}x{resultado['altura']}"
        )

    melhor = cameras_validas[0]
    print()
    print("CONFIGURAÇÃO INICIAL RECOMENDADA:")
    print(f"INDICE_CAMERA_PADRAO = {melhor['indice']}")
    print(f"Backend: {melhor['backend']}")
    print()
    print(
        "Abra a imagem JPG salva na pasta diagnostico_camera para "
        "confirmar que é a câmera correta."
    )
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
