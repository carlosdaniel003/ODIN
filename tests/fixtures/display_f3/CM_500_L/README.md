# Fotografias reais — Display F3 CM_500_L

Acervo registrado em 26/10/2026 no commit `ac69c2a4`. Os seis PNGs
são fotos físicas da câmera, não imagens geradas nem mocks.

| Foto | CHECK | Condição confirmada pelo operador |
| --- | --- | --- |
| H1_OK.png | H1 | OK |
| BLUE_OK.png | BLUE, fase ON | OK |
| BLUE_NG_024.png | BLUE, fase ON | NG, MASK_024 apagada |
| USB_OK.png | USB | OK |
| FM_OK.png | FM | OK |
| AUX_OK.png | AUX | OK |

**Orientação:** o operador aplicou 180° ANTES de gravar os PNGs.
No replay destas imagens a rotação adicional é **0°**. Não rotacionar
novamente nem confundir com o `visual_rotation` do frame RAW ao vivo.

## Executar análise offline

```bash
python -m unittest tests.test_display_f3_real_snapshots -v
python scripts/avaliar_f3_fotos_reais.py --report f3_fotos_relatorio.json
```

O relatório inicial mede características da imagem, diferença visual entre
BLUE OK e NG e a disponibilidade de recursos para o replay semântico.

**Limitação atual:** este repositório não versiona
`data/config/odin_display_projects.json`, referências físicas locais
nem modelo `data/models/f3_neural/cm_500_l_segments.onnx` e metadados.
As fotos sozinhas NÃO estabelecem a posição/identidade das 30 máscaras.
O relatório marca `semantic_replay.status=BLOCKED`, não inventa OK/NG.
A comparação de pixels BLUE OK/NG é exclusivamente diagnóstica.

Para executar o classificador real (sem produção), forneça localmente:

- `--project-config /caminho/odin_display_projects.json`
- `--geometry-dir /caminho/geometrias`, contendo
  `H1_OK.json`, `BLUE_OK.json`, `BLUE_NG_024.json`, etc. Cada JSON:
  `{"frame_resolution":[1920,1080],"masks":[...30 geometrias rastreadas...]}`,
  com IDs originais e orientação da imagem já rotacionada.
- Modelo ONNX e JSON de metadados no diretório local resolvido pela
  configuração do projeto (sem alterar pesos ou thresholds em produção).

O replay mostra resultados **semânticos da fotografia**; não simula gates
físicos, debounce temporal ou decisão terminal de produção. Não introduz
autoridade nova de OK/NG nem altera o modo tracking OFF.

O conjunto tem 5 fotos OK e 1 NG. É suficiente para reprodução inicial,
mas não para demonstrar generalização ou ausência de falso OK em produção.
