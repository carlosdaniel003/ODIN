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

## Medições iniciais (CI 40316106768)

Todas as capturas são PNG 1920×1080; quatro novos testes físicos
PASS, junto de 77 testes anteriores (81/81). Pixels V>=200:
H1 15477, BLUE OK 40022, BLUE NG 32699, USB 33071, FM 39754, AUX 33864.
Registro luminoso BLUE OK→NG: deslocamento relativo
[6,09, -55,086] px (resposta 0,65074). São diagnósticos de pixels,
não identificação automática de MASK_024.

A CI publica o relatório detalhado como artefato
`f3-real-snapshots-report`. Até existir configuração/ONNX e pose por
fotografia, os seis vereditos semânticos permanecem BLOQUEADOS.

## Auditoria posterior ao ZIP real — 26/10/2026

O operador forneceu separadamente arquivos privados do projeto, da CNN e
fotos JPG de referência. O teste do modelo sobre os cinco **JPGs** (não
os seis PNGs do repositório) revelou CNN-only H1 26/30, BLUE 11/30,
USB 30/30, FM 12/30, AUX 30/30. A foto referência BLUE e as máscaras
`mask_overrides_reference` parecem desalinhadas: 0/18 máscaras ON do
CHECK_002 apresentam brilho V>=200 dentro da ROI, embora existam
segmentos luminosos na imagem fora delas.

**Não incorporar arquivos privados do ZIP aqui** sem autorização explícita.
Os PNGs seguem exigindo cálculo validado das poses por imagem para um
replay híbrido seguro. Os números acima são diagnósticos da CNN isolada
em fotos que podem ter participado do treinamento, não resultados
industriais independentes OK/NG.

## Replay experimental com o ZIP privado (somente no computador local)

```bash
python scripts/avaliar_f3_fotos_reais.py --asset-zip /caminho/enviar.zip --estimate-geometry --report diagnostico_f3_local.json
```

O ZIP e os modelos NÃO são enviados ao GitHub: o comando utiliza diretório
temporário e ajusta somente as referências da cópia temporária. O estimador
busca correspondência entre luz e as máscaras canônicas em orientações 0/180
**das máscaras**, sem rotacionar os PNGs já orientados. É uma hipótese de
translação, não um LOCK homologado de rastreamento. Os resultados são marcados
`PROVISIONAL_*` ou `BLOCKED`; nunca justificam aprovar uma placa NG.
Os `--geometry-dir` com poses reais validadas continuam prioritários.
