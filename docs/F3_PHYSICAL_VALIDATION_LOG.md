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

Implementação principal: commit `2fca6b695542b325eb67d6bfb3d7b6d10feefa31`.

### Validação automatizada desta correção

- compilação dos módulos F3: PASS;
- regressões luminosas focadas: **30 testes PASS**;
- novos testes D-028:
  - `test_usb_power_gate_aceita_lock_luminoso_atual_do_mesmo_check`: PASS;
  - `test_lock_luminoso_stale_ou_de_outro_check_nao_libera_gate`: PASS;
- workflow `Display F3 fast H1 BLUE tests`: PASS;
- workflow `Display F3 cycle rearm tests`: PASS;
- a suíte ampla de object tracking continua com **8 failures + 1 error** nos
  mesmos testes históricos já presentes antes desta alteração. A etapa focada
  da D-028 passa antes desse bloco agregado.

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

---

## 29/09/2026 — Sincronia visual câmera x máscaras x visor e demora no IDENTIFICANDO

**Resultado físico antes da correção:** FAIL de experiência operacional.

### Sintoma observado

- os segmentos reais do display mudavam primeiro na câmera ao vivo;
- as máscaras verdes sobre a câmera reagiam depois;
- o `VISOR DO DISPLAY` também reagia depois;
- no BLUE intermitente, a defasagem entre a fase física e as representações da
  interface deixava a tela visualmente desconcertante;
- ao abrir o F3, a aquisição inicial permanecia tempo demais em
  `IDENTIFICANDO...`.

### Causa identificada no código

As duas representações visuais usavam resultados assíncronos do
tracking/analyzer, enquanto a imagem da câmera já era latest-frame-wins. Portanto
não existia garantia de que câmera, máscara verde e visor representassem o mesmo
frame.

Na inicialização, o banco de referências também calculava AKAZE
preventivamente para todas as fotos, apesar de AKAZE ser fallback de
reacquisition. Além disso, o coordinator podia deixar o primeiro tracking HIGH
esperando um executor ocupado por trabalho já existente.

### Correção D-029

- uma amostra luminosa **somente visual** é calculada sobre o mesmo frame reduzido
  que será desenhado na câmera;
- a amostra é compartilhada entre overlay e visor no mesmo repaint;
- repaints do mesmo frame reutilizam cache;
- nenhum timer, thread ou worker novo foi criado;
- a amostra não participa de OK/NG ou de qualquer autoridade produtiva;
- AKAZE das referências passou a ser lazy e cacheado somente quando necessário;
- o primeiro tracking HIGH recebe prioridade de enfileiramento para reduzir o
  tempo de `IDENTIFICANDO...`.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

Implementação principal: commit `ba627170e5da3629f27ec564ebd675547fdd035e`.

Ajuste final de renderização: commit
`979cb1fa0de5f78df9171ff0d2ae23ea6edbd5ef`, que evita reconstruir o conjunto
de IDs luminosos dentro de cada um dos 28 segmentos do visor e reforça o teste
de contrato do espelho visual.

### Validação automatizada desta correção

- compilação dos módulos F3: PASS;
- regressões luminosas focadas anteriores: **30 testes PASS**;
- novo bloco `live visual sync and startup performance regressions`:
  **8/8 testes PASS**;
- contratos validados:
  - frame ON detecta somente as ROIs luminosas;
  - frame totalmente escuro limpa imediatamente o espelho visual;
  - repaint do mesmo frame reutiliza cache;
  - câmera e visor consomem a mesma amostra latest-frame;
  - AKAZE das referências é lazy;
  - primeiro tracking HIGH pode entrar antes de trabalho de menor prioridade;
  - backpressure volta a valer após o primeiro future;
- `Display F3 fast H1 BLUE tests`: PASS;
- `Display F3 cycle rearm tests`: PASS;
- a suíte ampla de object tracking continua com **7 failures + 1 error** em
  regressões históricas já existentes fora desta alteração. O antigo teste que
  exigia AKAZE eager foi atualizado para o contrato lazy e agora passa.

### Reteste esperado

~~~text
abrir F3
→ aquisição inicial/LOCK ocorre mais cedo

BLUE acende
→ no mesmo repaint:
   câmera física mostra ON
   máscaras correspondentes ficam verdes
   VISOR mostra os mesmos segmentos verdes

BLUE apaga
→ no mesmo repaint:
   câmera física mostra OFF
   máscaras verdes apagam
   VISOR apaga os mesmos segmentos

sem backlog visual
sem queda perceptível de responsividade
sem alterar a regra produtiva de OK/NG
~~~

---

## 29/09/2026 — Reteste D-029 / runtime preso em IDENTIFICANDO

**Resultado físico:** FAIL.

### Sintoma observado

Após a correção de sincronia visual D-029, o Display F3 abriu normalmente, mas
permaneceu indefinidamente em `IDENTIFICANDO...` no H1. A câmera continuava ao
vivo e o operador conseguia acionar ANALISAR, porém o runtime produtivo não
publicava um novo lock de tracking nem liberava a sequência.

### Evidência objetiva do DEBUG

No clique analisado:

- câmera ao vivo: frame 811, com fluxo ativo em aproximadamente 15 FPS;
- último estado publicado de object tracking: frame 36;
- tracking: `locked=false`, `reason=object_not_locked`,
  `evidence_current=false`;
- energia produtiva: indisponível por `object_not_locked`;
- `last_auto_analysis=null`;
- CHECK atual permaneceu H1 e nenhum CHECK foi concluído.

A diferença extrema entre o frame atual da câmera e o frame ainda publicado pelo
tracking confirmou que o problema não era falta de atualização da câmera.

### Causa identificada

A otimização de aquisição inicial de D-029 introduziu um deadlock de publicação
no `F3RuntimeCoordinator`:

~~~text
primeiro full_cycle
  -> submete tracking HIGH
  -> _display_f3_tracking_future != None
  -> worker termina
  -> executor deixa de estar busy
  -> Future continua armazenado até o full_cycle consumi-lo

_choose_path()
  -> initial_lock_needed = True
  -> Future existe
  -> executor não está busy
  -> tracking_initial_lock_in_flight
  -> render_only
  -> nunca chama o consumidor do Future
  -> _display_f3_tracking_result continua None
  -> IDENTIFICANDO para sempre
~~~

O coordinator distinguia apenas `Future is None` de `Future existe`; não
distinguia um Future ainda em execução de um Future já concluído.

### Correção aplicada

O coordinator passa a verificar resultados assíncronos concluídos antes de:

- coalescer frame repetido;
- aplicar backpressure do executor;
- tratar o primeiro lock como ainda em voo.

Um Future concluído de tracking ou classificação semântica força exatamente um
`full_cycle` para que o consumidor canônico publique o resultado no thread Tk.
Nenhum novo scheduler, thread, worker ou fila foi criado.

A política de desempenho permanece:

~~~text
worker em voo -> render_only / backpressure
worker concluído -> full_cycle curto para drenar/publicar
próximo trabalho pesado -> continua no executor único
~~~

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Validação automatizada adicionada

- Future de tracking inicial concluído precisa ser drenado antes do backpressure;
- Future semântico concluído precisa ser drenado mesmo quando o frame visual se
  repete;
- o teste existente de tracking ainda em voo continua exigindo
  `render_only`/backpressure.

### Reteste esperado

~~~text
abrir F3
-> primeiro tracking HIGH é submetido
-> worker termina
-> coordinator drena o resultado concluído
-> tracking passa a acompanhar frames atuais
-> IDENTIFICANDO deixa de ficar preso

com LOCK válido:
-> câmera, máscaras verdes e VISOR usam a mesma amostra visual latest-frame
-> sem backlog visual
-> sem alterar OK/NG, energia ou sequência
~~~

---

## 29/09/2026 — Reteste do deadlock de publicação D-029

**Resultado físico:** PASS.

### Cenário

Foi repetida a abertura do Display F3 após a correção que passou a drenar
`Future` de tracking/semântica concluído antes do backpressure do coordinator.

### Resultado observado

O runtime deixou de permanecer indefinidamente em `IDENTIFICANDO...`.
O fluxo voltou a avançar normalmente.

### Estado

**PASS.**

A falha anterior permanece registrada acima como histórico; este reteste confirma
a correção do deadlock de publicação.

---

## 29/09/2026 — Troca de placa em nova posição e latência de aquisição

**Resultado físico antes desta alteração:** FAIL de desempenho / requisito de
reaquisição confirmado.

### Cenário

Depois de a placa terminar a inspeção e receber o resultado, ela é retirada do
suporte. A placa seguinte pode entrar em outra posição física.

O comportamento requerido é:

~~~text
placa A termina
→ placa A sai
→ suporte vazio confirmado
→ placa B entra em outra posição
→ ODIN procura novamente a placa
→ nenhuma pose da placa A é reutilizada
~~~

Também foi observado que o início de uma aquisição ainda permanece tempo demais
em `IDENTIFICANDO...`.

### Causa identificada no código

O rearme canônico já invalidava tracking, porém usava o mesmo reset completo
destinado a mudanças de configuração. Isso apagava simultaneamente:

- pose/matriz da placa anterior, o que é correto;
- banco de referências estruturais já preparado, o que é desnecessário.

Na aquisição seguinte, `configure()` precisava novamente decodificar todas as
fotografias estruturais e calcular ORB do banco inteiro.

No primeiro ciclo da sessão ocorria custo semelhante: o banco inteiro era
materializado antes de o tracker saber se H1 atual ou `board_off` já eram
suficientes para localizar a placa.

### Alteração aplicada

- foi separado reset completo de reset de ciclo;
- EMPTY agora invalida a pose corrente sem descartar a calibração/referências da
  sessão;
- a nova placa continua obrigatoriamente sem `last_matrix`, sem anchor angular,
  sem `last_result` e sem geometria live da placa anterior;
- referências passaram a ser materializadas sob demanda;
- aquisição inicial prioriza a referência do CHECK atual e `board_off`;
- as demais vistas continuam disponíveis como fallback;
- nenhum scheduler, thread ou worker adicional foi criado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
abrir F3
→ IDENTIFICANDO reduzido
→ novo LOCK

terminar placa A
→ retirar placa A
→ confirmar EMPTY
→ inserir placa B deslocada/rotacionada dentro da faixa permitida
→ pose antiga não aparece
→ ODIN procura novamente
→ obtém novo LOCK na posição da placa B
→ H1 segue normalmente
~~~

Além do tempo percebido, observar no DEBUG se o frame do tracking acompanha o
frame atual logo após a entrada da nova placa.

---

## 29/09/2026 — Reteste D-030 / nova placa em outra posição

**Resultado físico:** PASS.

### Cenário

Após concluir a placa anterior, ela foi retirada e uma nova placa entrou em outra
posição física. Também foi retestado o tempo de aquisição após a separação entre
pose efêmera e banco de referências da sessão.

### Resultado observado

- a placa seguinte foi procurada novamente;
- a pose da placa anterior não foi herdada;
- a nova posição foi adquirida corretamente;
- o fluxo voltou a funcionar após a otimização de IDENTIFICANDO....

### Estado

**PASS.**

---

## 29/09/2026 — SEGREGAR PLACA sem ação em transição de rearme

**Resultado físico antes da correção:** FAIL.

### Sintoma observado

O botão **SEGREGAR PLACA** podia não produzir ação.

### Causa identificada no código

A ação manual era bloqueada não apenas enquanto a placa anterior ainda aguardava
EMPTY, mas também durante waiting_new_board_after_empty. Nesse segundo estado,
a autoridade canônica de presença já podia ter confirmado fisicamente a nova
placa enquanto o debounce de rearme ainda não havia limpado a flag. O clique
virava um retorno silencioso.

Também foi confirmado que a extensão de nomenclatura SEGREGAR existia, mas não
era instalada explicitamente pela composição desktop canônica.

### Alteração aplicada

- waiting_empty continua bloqueando SEGREGAR para impedir dupla contagem;
- durante waiting_new_board, SEGREGAR é liberado somente quando
  board_presence_evidence confirma placa presente e não EMPTY;
- a composição desktop passa a instalar explicitamente a apresentação
  **SEGREGAR PLACA** antes de construir a janela F3;
- nenhuma regra ou contador do F2 é alterado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

---

## 29/09/2026 — Segmento 24 fisicamente danificado foi aprovado

**Resultado físico antes da correção:** FAIL crítico de decisão.

### Cenário

O CHECK esperava o segmento 24 ACESO. O segmento estava fisicamente danificado e
não acendeu durante o teste. Mesmo assim, depois de algum tempo o CHECK foi
aprovado.

### Causa identificada no código

A conformidade estrita já existia e bloqueava OK quando qualquer máscara ativa
divergia. Entretanto, a composição final de tracking substituía o analyzer da
sessão por F3TrackedRawCheckAnalyzer, que internamente reconstruía
F3SameMaskReferenceAnalyzer simples.

Assim, a camada geométrica final podia rebaixar a autoridade semântica que deveria
continuar estrita. O mesmo wrapper permanecia publicado mesmo quando tracking
estava desligado.

### Correção D-031

- o analyzer final de tracking passa a usar F3StrictMaskConformityAnalyzer;
- a conformidade estrita agora aceita as ROIs móveis do tracking;
- tracking ligado e desligado passam pela mesma regra de conformidade;
- uma única máscara divergente impede OK;
- regressão explícita usa MASK_024 esperado ON, classificado OFF, com outro
  segmento ON: a política precisa retornar NG para MASK_024.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
CHECK posterior energizado
→ demais segmentos esperados ON acendem
→ MASK_024 deveria estar ON, mas permanece fisicamente apagada
→ análise mantém MASK_024 como divergente
→ CHECK nunca recebe OK
→ após debounce normal de NG
→ placa é reprovada por MASK_024
→ frame/evidência NG permanece congelado até retirada
~~~

Repetir o mesmo teste com tracking habilitado e desabilitado para confirmar que a
autoridade semântica não muda com o modo de tracking.

