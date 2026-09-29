# F3 — Registro de validação física

Este arquivo é o diário cronológico dos testes físicos do **Display F3**.

## Regra de manutenção

- Não apagar nem reescrever silenciosamente um resultado antigo.
- Registrar tanto **PASS** quanto **FAIL**.
- Registrar o comportamento observado no equipamento, a evidência do DEBUG,
  a causa identificada, a alteração realizada e o que ainda depende de reteste.
- Quando uma correção ainda não foi validada fisicamente, marcar explicitamente
  como **PENDENTE DE RETESTE**.
- Decisões arquiteturais continuam em `docs/DECISIONS.md`; este arquivo preserva
  a sequência factual dos testes.
- O log começa em 29/09/2026. Investigações anteriores continuam preservadas em
  `docs/DECISIONS.md`.

---

## 29/09/2026 — H1 / alinhamento por núcleo luminoso

**Resultado físico:** PASS observado no fluxo subsequente.

### Contexto

A rodada anterior mostrou que uma pose já visualmente correta podia ser rejeitada
por `fine_gain_insufficient`. A D-026 passou a permitir que o próprio núcleo
luminoso dos segmentos ON confirme uma pose já correta sem exigir movimento
geométrico artificial.

### Evidência operacional

Na execução que posteriormente chegou a USB, o H1 aparece como **CONCLUÍDO**.
O fluxo conseguiu avançar H1 -> BLUE -> USB.

### Estado

**PASS** para a progressão observada nesta montagem.

---

## 29/09/2026 — BLUE intermitente / snapshot ON

**Mudança relacionada:** D-027.

**Resultado físico:** PASS.

### Problema anterior

BLUE fica aproximadamente um intervalo aceso e outro apagado. O worker podia
capturar a fase ON, mas terminar quando a câmera já estava na fase OFF; o
resultado correto era descartado por frescor de frame.

### Alteração aplicada

Foi criada uma janela curta para preservar um snapshot positivo do mesmo
`project_name + check_id` quando `intermittent=true`. A câmera visível continua
latest-frame-wins; somente a evidência temporal do CHECK é preservada.

### Validação

Após a alteração, BLUE foi concluído automaticamente e a sequência avançou para
USB.

### Estado

**PASS**.

---

## 29/09/2026 — USB aceso corretamente, mas gate permaneceu bloqueado

**Resultado físico antes da correção:** FAIL.

### Sintoma

- H1: CONCLUÍDO.
- BLUE: CONCLUÍDO.
- USB: fisicamente aceso com o padrão esperado.
- UI permaneceu em `AGUARDANDO USB`.
- status superior: `PLACA NO SUPORTE • LIGADA • ALINHANDO USB`.
- máscaras visuais já mostravam segmentos luminosos identificados.

### Evidência do DEBUG

No mesmo cenário:

- CHECK lógico: `CHECK_004 / USB`;
- USB não é intermitente;
- energia física: **CONFIRMADA**;
- máscaras live: **15 ON / 11 OFF**;
- análise bruta do USB: **28/28**, `approved=true`;
- tracking luminoso:
  - frame 942;
  - `source_type=luminous_segment_grid`;
  - `evidence_current=true`;
  - 15/15 IDs ON encontrados;
  - `alignment_ready=true`;
  - modo `base_core_verified`;
- autoridade de energia em frame posterior:
  - frame 949;
  - `powered_confirmed=true`;
  - `spatial_alignment_ready=false`;
  - `spatial_alignment_source=structural_only`;
  - gate bloqueado por
    `energia_confirmada_aguardando_alinhamento_segmentos`;
- a análise semântica correta ficou
  `blocked_by_power_gate=true`.

### Causa

Existe latência normal entre os jobs HIGH de tracking e o frame live usado pela
autoridade de energia. O tracker canônico já possuía um lock luminoso atual e
válido do USB, mas o gate de energia exigia que o estado espacial do frame de
energia também já tivesse sido publicado como luminoso. Assim, duas evidências
válidas e próximas no tempo não eram reconciliadas:

~~~text
tracking frame 942
USB 15/15 alinhado
        +
energia frame 949
display ligado
        ↓
gate ainda usava spatial_alignment_ready=false
        ↓
28/28 correto ficava sem autoridade
~~~

### Correção D-028

O `F3PowerAuthority` passa a receber explicitamente a evidência do proprietário
canônico de tracking e pode reconciliar o gate espacial quando TODAS as condições
abaixo forem verdadeiras:

1. placa presente;
2. energia do frame live realmente confirmada;
3. alinhamento é requerido e a evidência de energia ainda o marca como não pronto;
4. tracking está `locked=true`;
5. `evidence_current=true`;
6. `source_type=luminous_segment_grid`;
7. referência é exatamente `luminous:<CHECK atual>`;
8. existem IDs luminosos validados;
9. idade do lock não excede o limite operacional do tracking;
10. diferença de frames não excede o limite operacional do tracking.

Não existe liberação por lock estrutural, lock mantido/stale, outro CHECK,
outro projeto ou evidência luminosa antiga.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

O reteste esperado é:

~~~text
H1 conclui
→ BLUE conclui
→ USB acende corretamente
→ tracking confirma USB luminoso
→ energia confirma display ligado
→ gate fica liberado
→ analyzer 28/28 possui autoridade
→ USB conclui e avança para AUX
~~~

