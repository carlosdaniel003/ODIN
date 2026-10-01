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

---

## 30/09/2026 — Tracking ON / câmera, máscaras e visor não espelharam a mesma emissão

**Resultado físico antes da correção:** FAIL visual.

### Cenário

Modo **Rastreamento Automático do Display F3** ativo. Segmentos fisicamente
acesos eram visíveis na própria imagem da câmera, porém a máscara correspondente
e/ou o segmento equivalente do VISOR DO DISPLAY não reagiam em verde junto com
a emissão real.

### Requisito confirmado

A apresentação visual é independente dos gates produtivos:

~~~text
segmento físico aceso
→ máscara correspondente verde
→ segmento correspondente do visor verde
→ mesma atualização visual
~~~

Power gate, presença, spatial gate, H1, debounce e decisão OK/NG podem continuar
bloqueando a produção, mas não podem neutralizar esse espelho visual.

### Causa encontrada no código

D-029 já possuía amostra visual latest-frame, porém ainda existiam fallbacks
históricos que:

- condicionavam a apresentação ao estado de energia;
- permitiam ao visor usar classificação assíncrona;
- entravam em conflito com a intenção de fonte visual única;
- podiam perder maioria/todos os segmentos ON porque o threshold relativo subia
  junto com o baseline das máscaras.

### Correção D-032

- câmera/overlay e visor passam a consumir a mesma fonte visual;
- gate produtivo deixa de participar da cor do modo tracking;
- classificação semântica deixa de ser fallback do espelho visual;
- detector latest-frame cobre também maioria/todos ON por cluster gap + evidência
  absoluta forte;
- nenhum novo worker, thread, scheduler ou I/O foi adicionado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking ON + LOCK
→ segmento acende fisicamente
→ máscara fica verde no mesmo repaint
→ visor fica verde no mesmo repaint

segmento apaga
→ máscara perde verde
→ visor perde verde

repetir com power gate bloqueado
→ a cor visual continua reagindo
→ OK/NG permanece bloqueado normalmente
~~~

---

## 30/09/2026 — Reteste D-032 / máscaras e visor continuam sem reagir

**Resultado físico:** FAIL.

### Sintoma observado

Após o commit D-032, o operador continua sem ver:

- as máscaras da câmera ao vivo reagirem/colorirem conforme os segmentos físicos;
- o VISOR DO DISPLAY acompanhar os segmentos físicos.

Portanto a alteração anterior não resolveu o caminho real de apresentação no
equipamento.

### Interpretação

Este é o segundo ciclo de correção do mesmo defeito visual sem validação física
positiva. Conforme a regra das duas tentativas do projeto, não será feita nova
mudança de algoritmo/threshold por hipótese.

A etapa atual passa a ser **diagnóstico instrumentado do caminho real**.

### Instrumentação adicionada

Foi adicionada telemetria leve, somente em memória, para identificar em qual
ponto o espelho visual D-032 deixa de funcionar:

- hook visual final ativo;
- tracking realmente habilitado;
- geometria presente/LOCK;
- quantidade de máscaras na geometria;
- contexto visual construído;
- quantidade de máscaras no contexto;
- amostra latest-frame pronta ou não;
- motivo da amostra;
- IDs visualmente luminosos;
- contexto do visor atualizado ou não;
- 28 slots do visor disponíveis ou não;
- IDs recebidos pelo visor;
- resultado do repaint;
- exceção e estágio exatos quando houver fallback silencioso.

Nenhum novo timer, thread, worker, scheduler, I/O ou processamento pesado foi
adicionado.

### Próximo teste

Com o defeito visível:

1. clicar em **ANALISAR**;
2. abrir **DEBUG TÉCNICO**;
3. usar **COPIAR DEBUG**;
4. enviar o bloco inteiro.

O relatório passa a conter:

~~~text
[ESPELHO VISUAL LIVE D-032 / CÂMERA + MÁSCARAS + VISOR]
~~~

Esse bloco permitirá distinguir objetivamente:

~~~text
tracking não está ativo
vs
não existe LOCK/geometria
vs
contexto visual não foi construído
vs
amostra não está lendo as 28 máscaras
vs
amostra produz 0 IDs
vs
visor não recebeu contexto
vs
renderer caiu no fallback por exceção
~~~

### Estado

**FAIL CONFIRMADO — DIAGNÓSTICO INSTRUMENTADO, AGUARDANDO EVIDÊNCIA DO EQUIPAMENTO.**

---

## 30/09/2026 — Clarificação do reteste D-032: tracking estava OFF

**Resultado físico observado:** FAIL visual.

### Clarificação

O operador informou que o cenário anterior em que:

- as máscaras da câmera estavam cinzas;
- o VISOR DO DISPLAY não mostrava os segmentos;

estava sendo executado com **Rastreamento Automático desativado**.

Portanto o diagnóstico anterior tratou o modo errado. A instrumentação colocada
no wrapper de tracking não poderia explicar esse cenário porque, com tracking
OFF, o runtime delegava para o renderer fixo.

### Causa confirmada no código

No caminho tracking OFF:

~~~text
tracked_window_update
→ tracking_enabled = false
→ previous_window_update
→ contexto fixo
→ live_luminous_only = false
→ sem amostra visual latest-frame
→ cor dependente de análise/power gate
→ máscaras cinzas / visor sem emissão
~~~

Além disso, o contexto fixo usava somente máscaras ativas do CHECK.

### Correção D-033

~~~text
tracking OFF
→ geometria fixa das máscaras
→ TODAS as máscaras disponíveis
→ amostra luminosa no frame atual
→ mesmos live_visual_mask_ids
   ├── overlay da câmera
   └── VISOR DO DISPLAY
→ mesmo repaint
~~~

A mudança não altera energia, OK/NG, debounce, sequência ou conformidade.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

Com tracking OFF:

1. abrir o F3;
2. manter a placa na posição cadastrada;
3. acender segmentos físicos;
4. confirmar que as máscaras correspondentes ficam verdes;
5. confirmar que o VISOR mostra exatamente os mesmos segmentos verdes;
6. apagar segmentos e confirmar que ambos perdem o verde juntos;
7. repetir mesmo enquanto power gate ainda não confirmou energia.

---

## 30/09/2026 — Screenshot: 15 ACESOS no analyzer e visor neutro

**Resultado físico:** FAIL visual confirmado.

### Evidência

No mesmo estado de tela:

~~~text
PLACA NO SUPORTE • LIGADA • ANALISANDO USB
19/28 CONFORMES • 15 ACESOS • 13 APAGADOS
ANÁLISE VISUAL: CHECK AUX • 93%
~~~

Apesar disso:

- as máscaras desenhadas sobre o display estavam neutras;
- o VISOR DO DISPLAY também estava totalmente neutro.

### Diagnóstico

A análise automática já havia identificado estados físicos para as máscaras.
Logo, o defeito estava na ligação entre essa evidência e a apresentação.

A diferença entre o CHECK lógico e o CHECK da análise recente confirma que o
pipeline pode publicar essas informações em momentos diferentes. Para cor
visual, o estado físico classified continua utilizável; expected/matched
continuam presos ao CHECK correto.

### Correção D-034

- o espelho visual aceita classified da análise recente do mesmo projeto;
- detector latest-frame e classificação física são combinados para ON visual;
- câmera e visor consomem o mesmo mapa físico;
- ON = verde, OFF = azul/cinza, LOW_LIGHT = amarelo;
- gates e decisão produtiva permanecem inalterados.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

---

## 30/09/2026 — Reteste D-034: DEBUG confirmou bypass do tracking OFF

**Resultado físico:** FAIL visual, causa confirmada por telemetria.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico: AUX;
- placa presente;
- energia confirmada;
- objetivo visual:
  - ON = verde vivo;
  - OFF = verde escuro;
  - câmera e visor iguais.

### Evidência objetiva

O snapshot registrou 15 máscaras live ON e 11 live OFF confirmadas, mas o bloco
do espelho visual informou:

~~~text
tracking_enabled=NÃO
stage=tracking_disabled
render_path=previous_window_update
context_ready=NÃO
sample_ready=NÃO
visual_ids=0
readout_ready=NÃO
readout_visual_ids=0
preview_rendered=SIM
~~~

Portanto o frame era renderizado, porém o callback final abandonava o espelho
visual antes de construir contexto, amostrar ROIs e atualizar o visor.

### Causa confirmada

O `tracked_window_update` instalado diretamente na instância real possuía um
retorno antecipado para `previous_window_update` quando tracking estava OFF.
Essa camada era mais externa que as correções D-033/D-034 e anulava o caminho
pretendido.

### Correção D-035

- removido o bypass visual antecipado no proprietário final;
- tracking OFF usa geometria fixa e continua pelo espelho latest-frame;
- tracking ON usa geometria móvel pelo mesmo builder;
- sampler do frame atual publica ON e OFF por ROI;
- ON usa verde vivo `#22C55E`;
- OFF usa verde escuro `#14532D`;
- câmera e VISOR DO DISPLAY consomem o mesmo contexto;
- análise/power físico permanece somente fallback visual quando o sampler não
  possui amostra de uma ROI;
- nenhuma regra de OK/NG, energia, presença, debounce ou sequência foi alterada;
- nenhum timer/thread/worker/scheduler novo foi criado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking OFF
→ display aceso
→ ROIs ON: verde vivo na câmera + visor
→ ROIs OFF: verde escuro na câmera + visor

segmento muda ON -> OFF
→ os dois perdem verde vivo no mesmo repaint
→ passam para verde escuro

segmento muda OFF -> ON
→ os dois passam para verde vivo
~~~

---

## 30/09/2026 — Tecla 1 não acionava SEGREGAR após mudança de foco

**Resultado físico antes da correção:** FAIL.

### Sintoma observado

Na Produção Display F3, pressionar **1** não executava **SEGREGAR PLACA**.

### Causa identificada

O atalho estava associado somente a `self.container`, que é um `tk.Frame`.
Ao abrir o F3 o Frame recebe foco, porém clicar em um widget filho — por exemplo
ANALISAR, CONFIGURAR, DEBUG ou outro controle — transfere o foco. Eventos de
teclado do widget filho não percorrem o binding particular do Frame pai.

A ação `descartar_placa_display_f3()` e o botão continuavam conectados; o
defeito estava na captura do atalho de teclado.

### Correção

- mantém os bindings existentes no container;
- adiciona `1` e `KP_1` ao toplevel/root com `add="+"`, sem substituir
  atalhos existentes;
- o handler global só consome a tecla quando a janela F3 está visível;
- a ação continua passando pela autoridade canônica de SEGREGAR e pelas guardas
  contra dupla contabilização;
- nenhuma regra de TOTAL/NG, rearme, tracking, câmera ou F2 foi alterada.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
abrir F3
→ clicar em ANALISAR (ou outro controle)
→ pressionar 1
→ SEGREGAR PLACA
→ TOTAL +1
→ NG +1
→ resultado PLACA SEGREGADA
→ aguardar retirada/rearme normalmente

repetir com NumPad 1
→ mesmo comportamento
~~~

---

## 30/09/2026 — Contorno desenhado da placa não aparecia na câmera ao vivo

**Resultado físico antes da correção:** FAIL visual.

### Cenário

- Produção Display F3;
- foco atual em Rastreamento Automático desativado;
- contorno da placa já desenhado e salvo em **Placa + Máscaras**;
- máscaras live já usam a geometria canônica da seção **Máscaras**.

### Sintoma observado

O operador solicitou que o contorno da placa desenhado durante a configuração
também apareça sobre a câmera ao vivo. O preview fixo mostrava as máscaras, mas
não publicava os pontos do contorno canônico.

### Causa identificada

No caminho final de preview com tracking OFF,
`_project_preview_context()` preenchia explicitamente `board_points=()`.
O renderer já sabia desenhar `board_points`, portanto a falha era de contexto,
não de desenho OpenCV.

### Correção D-037

- carregar o contorno por `canonical_board_points(...)` usando o store canônico;
- aplicar a mesma rotação visual usada pelas máscaras;
- publicar `board_points` no contexto live;
- incluir os pontos na chave de cache do preview fixo;
- manter contornos locais de CHECK/referência fora da câmera live.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking OFF
→ abrir F3
→ confirmar máscaras fixas + contorno da placa desenhado na câmera ao vivo
→ editar somente o contorno em Placa + Máscaras
→ reabrir/atualizar F3
→ confirmar novo contorno sem mover as máscaras

tracking ON + LOCK
→ confirmar que o mesmo contorno acompanha a pose rastreada
~~~



---

## 30/09/2026 — H1 correto não aprovava e SEGREGAR parecia inoperante

**Resultado físico antes da correção:** FAIL de decisão/apresentação.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico exibido: H1;
- sete segmentos esperados ON visivelmente acesos;
- operador tentou SEGREGAR pelo botão e pela tecla 1.

### Evidência objetiva do DEBUG

No frame congelado da auditoria manual:

- H1 possui 7 máscaras esperadas ON e 21 OFF;
- o aprendizado por mesma máscara classificou o CHECK como
  `approved=True`, 28/28;
- a autoridade de energia encontrou as sete máscaras ON esperadas como
  energizadas;
- a análise estrita observada pelo runtime tinha 21/28 e marcava justamente as
  sete máscaras ON de H1 como faltantes;
- simultaneamente o ciclo já estava terminal:
  `waiting_empty_rearm=true`, TOTAL 1, NG 1, `last_result=null`;
- a UI principal havia voltado para `AGUARDANDO H1`, apesar do status
  operacional informar `RETIRE A PLACA DO SUPORTE`.

### Causas

1. **D-038 / falso OFF do CHECK correto:** a proteção D-031 removia
   absolutamente a foto do CHECK atual do aprendizado. Em segmentos cuja
   assinatura óptica muda entre funções, H1 podia ficar mais próximo de OFF de
   outra função mesmo estando fisicamente aceso.
2. **D-039 / SEGREGAR aparentemente morto:** a segregação já havia sido
   contabilizada. O runtime resetou internamente a sequência para H1 e o hold
   visual terminou, mas o rearme físico ainda bloqueava qualquer novo ciclo e
   qualquer nova segregação. A apresentação não espelhava esse latch.

### Correções implementadas

- ON do próprio CHECK só pode ser referência local da mesma máscara quando prova
  emissão contra OFF externo com a margem óptica mínima já existente;
- OFF próprio continua proibido;
- uma máscara live divergente continua bloqueando OK;
- tela terminal não pode ser sobrescrita por H1 enquanto aguarda retirada;
- após EMPTY, a tela mostra explicitamente espera por nova placa;
- SEGREGAR fica visualmente desabilitado durante todo o rearme e volta somente
  após nova placa confirmada;
- botão, `1` e NumPad `1` permanecem na mesma ação oficial;
- regressões automatizadas cobrem o ON próprio válido, o ON escuro inválido,
  o latch terminal e o handoff visual do rearme.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
1) nova placa confirmada
→ H1 realmente aceso
→ 28/28
→ H1 aprova com um frame conforme

2) segmento esperado ON fisicamente apagado
→ continua divergente
→ nunca recebe OK por auto-referência

3) pressionar 1 ou clicar SEGREGAR uma vez
→ TOTAL +1 / NG +1
→ PLACA SEGREGADA permanece visível
→ botão SEGREGAR desabilitado
→ repetir 1 não duplica contagem

4) retirar placa
→ suporte vazio confirmado
→ AGUARDANDO NOVA PLACA

5) colocar nova placa
→ H1 volta a ficar ativo
→ SEGREGAR volta a ficar habilitado
~~~

---

## 30/09/2026 — Refinamento do SEGREGAR: estado deve permanecer vermelho

**Resultado físico informado:** FAIL/AMBÍGUO de feedback visual antes do
refinamento.

### Relato do operador

O operador informou que tanto a tecla **1** quanto o clique em
**SEGREGAR PLACA** pareciam não funcionar, ou o resultado vermelho podia estar
rápido demais. O requisito explícito é que, depois da segregação, o estado
terminal permaneça vermelho enquanto a placa continuar no suporte.

### Diagnóstico sobre o estado atual

D-039 já impede que snapshots posteriores voltem o status principal para H1 e
mantém SEGREGAR bloqueado durante o rearme. Porém:

- os cards ainda podiam renderizar os estados normais H1/PRÓXIMO;
- o status inferior do guard terminal era amarelo;
- as bordas da coluna de câmera/visor permaneciam neutras;
- portanto o latch existia, mas o feedback visual não era integralmente vermelho.

### Correção D-040

- registrar o tipo terminal `segregated` na própria janela;
- cards de CHECK ficam vermelhos e mostram `SEGREGADO`;
- painel principal continua em `COLOR_NG`;
- bordas de preview/visor/projeto ficam vermelhas;
- status operacional e status inferior ficam vermelhos e pedem retirada;
- repaint durante `waiting_empty_rearm` preserva esse estado;
- EMPTY remove o chrome vermelho e entra em espera por nova placa;
- câmera, contorno, máscaras e VISOR DO DISPLAY recebem vermelho terminal
  integral enquanto a placa segregada permanece no suporte;
- o vermelho é apenas apresentação; a classificação física interna permanece
  intacta para diagnóstico e telemetria.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
placa no suporte
→ clicar SEGREGAR
→ TOTAL +1 / NG +1
→ PLACA SEGREGADA
→ cards SEGREGADO em vermelho
→ câmera, contorno, máscaras e visor ficam vermelhos
→ bordas/status permanecem vermelhos
→ aguardar vários segundos
→ NÃO voltar a H1 e NÃO perder o vermelho

repetir com tecla 1 e NumPad 1 em nova placa
→ mesmo resultado

retirar placa
→ EMPTY confirmado
→ sai do terminal vermelho
→ COLOQUE OUTRA PLACA

colocar nova placa
→ H1 liberado
→ SEGREGAR reabilitado
~~~

---

## 30/09/2026 — H1 com segmentos esperados verdes, mas CHECK/análise visual não reconhece

**Resultado físico:** FAIL recorrente informado pelo operador.

### Sintoma observado

No Display F3 ocorre repetidamente o cenário em que os segmentos que H1 deve
manter acesos aparecem corretamente verdes no ao vivo, mas:

- o CHECK H1 não recebe aprovação; ou
- a análise visual não consegue reconhecer o estado como H1.

Não foi fornecido nesta entrada um novo bloco de DEBUG que identifique qual gate
específico vetou o registro. Portanto a causa técnica exata ainda não deve ser
inventada.

### Regra funcional confirmada pelo operador

As imagens cadastradas nos CHECKS e em **Referências Visuais** já contêm:

- contorno desenhado da placa/filtro;
- máscaras locais alinhadas aos segmentos;
- segmentos ACESOS e APAGADOS que compõem o estado ensinado.

O ODIN não deve usar a fotografia inteira de H1 como classificador final contra
a câmera inteira. A referência deve ser tratada como memória do padrão do
display:

```text
contorno da placa
→ recorte da região útil
→ alinhamento dos segmentos/máscaras
→ comparação dos mesmos MASK_xxx
→ padrão ON/OFF conforme
→ CHECK reconhecido
```

D-031 continua válida: além de todos os segmentos esperados ON estarem ON, os
segmentos esperados OFF também precisam permanecer OFF; `ignore` não participa.
Se o padrão estiver 100% conforme, diferença de fundo ou score de cena inteira
não pode rejeitar o CHECK.

### Providência desta etapa

- regra registrada como D-041;
- AGENTS.md e README.md atualizados para impedir que futuras correções voltem a
  usar matching de cena inteira como segunda autoridade semântica;
- nenhuma mudança de algoritmo foi aplicada nesta etapa, porque o relato atual
  define o contrato, mas ainda não contém a evidência de qual proprietário está
  bloqueando o H1 no runtime real.

### Próximo diagnóstico esperado

Reproduzir exatamente o caso em que todos os ON esperados de H1 aparecem verdes
e capturar o DEBUG no mesmo instante. O diagnóstico precisa responder, no mínimo:

- máscaras esperadas ON realmente classificadas ON;
- máscaras esperadas OFF realmente classificadas OFF;
- total de conformes e `failed_mask_ids`;
- alinhamento/contorno considerado válido;
- gate físico/frescor/rearme que eventualmente permaneceu bloqueado;
- qual componente publicou a mensagem de análise visual.

### Estado

**FAIL REGISTRADO — CONTRATO D-041 DOCUMENTADO — CAUSA DE RUNTIME PENDENTE DE EVIDÊNCIA.**

---

## 30/09/2026 — H1 28/28 ficou bloqueado por presença global ambígua

**Resultado físico antes da correção:** FAIL recorrente.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico: H1;
- os sete segmentos que H1 espera ON estavam fisicamente acesos e verdes na
  câmera/visor;
- estados OFF restantes também foram reconhecidos pela análise semântica.

### Evidência objetiva do DEBUG

No mesmo snapshot:

- gate produtivo: **BLOQUEADO**;
- motivo: `placa_nao_confirmada_no_suporte`;
- autoridade de presença: `board_present=false` e energia operacional `null`;
- análise estrita H1 já estava `ready=true`, `approved=true` e
  `check_conforme_mascaras_configuradas`;
- `failed_mask_ids=[]`;
- H1 tinha 7 ON + 21 OFF e o analyzer publicou 7 ON + 21 OFF;
- a evidência diagnóstica das máscaras do próprio H1 mostrou 7/7 votos de
  energia e zero votos OFF;
- as referências globais de cena ficaram todas abaixo do threshold absoluto,
  apesar de a placa e o padrão H1 estarem visíveis.

### Causa confirmada

O runtime canônico continha um deadlock de dependência:

```text
F3PresenceAuthority não confirma placa pela foto global
→ F3RuntimeAuthorities não chama F3PowerAuthority.evaluate()
→ energia das máscaras não existe no snapshot operacional
→ gate mantém decisão bloqueada
→ analyzer 28/28 fica apenas diagnóstico
```

Portanto o defeito não estava no H1 nem na classificação dos segmentos. O
sistema já sabia exatamente quais máscaras estavam ON/OFF, mas a informação era
impedida de chegar à autoridade de presença.

### Correção D-042

- a observação semântica das máscaras é calculada no mesmo frame mesmo quando a
  presença global ainda está ambígua;
- `F3PresenceAuthority` continua sendo a única autoridade de presença;
- ela pode confirmar ocupação quando um padrão configurado possui todo o núcleo
  ON confirmado e nenhuma observação confiante contradiz seus estados ON/OFF;
- essa confirmação não aprova CHECK;
- depois da presença, a energia produtiva e o analyzer estrito seguem o fluxo
  normal;
- EMPTY confirmado continua tendo precedência absoluta;
- não foi reativado o antigo monkey patch de confirmação por máscaras e não foi
  criada autoridade paralela, timer, thread ou worker.

### Proteção contra recorrência

Foram adicionadas regressões para:

1. cena global ambígua + padrão H1 conhecido → presença confirmada;
2. EMPTY confirmado + emissão candidata → EMPTY continua soberano;
3. padrão incompleto/contraditório → não promove presença;
4. builder canônico rompe o deadlock presença/energia e libera o gate;
5. `F3PowerAuthority.apply` continua incapaz de ignorar ausência de presença por
   conta própria.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
tracking OFF
→ placa H1 no suporte
→ 7 segmentos esperados ON ficam verdes
→ padrão semântico confirma presença
→ status deixa IDENTIFICANDO PRESENÇA
→ energia fica CONFIRMADA
→ strict analyzer confirma 7 ON + 21 OFF / 28 de 28
→ H1 aprova
→ sequência avança para BLUE
```

Teste de segurança adicional:

```text
retirar a placa
→ EMPTY confirmado
→ nenhuma emissão/reflexo residual promove presença
→ fluxo permanece aguardando nova placa
```

---

## 30/09/2026 — Reteste D-042 PASS e BLUE 28/28 bloqueado na transição H1 → BLUE

### Parte 1 — validação física de D-042

**Resultado:** PASS.

O operador confirmou que, com Rastreamento Automático desativado, o H1 passou a
ser reconhecido corretamente depois da correção D-042 e a sequência avançou para
BLUE.

Isso valida no equipamento real o contrato:

```text
H1 correto
→ padrão semântico confirma presença
→ energia confirmada
→ conformidade estrita H1
→ H1 concluído
→ BLUE atual
```

A entrada anterior de D-042 permanece preservada como histórico da falha e da
correção; este registro é a confirmação física posterior.

### Parte 2 — novo FAIL em BLUE

**Resultado antes da correção:** FAIL.

Cenário:

- Rastreamento Automático: DESATIVADO;
- H1 já concluído;
- CHECK lógico atual: BLUE / CHECK_002;
- BLUE configurado com 18 máscaras ON + 10 OFF;
- câmera e visor mostravam o padrão BLUE esperado.

Evidência do mesmo snapshot:

- presença: confirmada;
- energia: confirmada;
- gate produtivo: liberado;
- aprendizado semântico de BLUE: `ready=true`, `approved=true`, 28/28;
- UI: `BLUE DETECTADO • 28/28 CONFORMES • 18 ACESOS • 10 APAGADOS`;
- mesmo assim o status inferior permaneceu
  `BLUE BLOQUEADO • aguardando mudança física H1 → BLUE`;
- sequência: H1 completed / BLUE current;
- tracking: desativado.

### Causa confirmada

A falha não estava em presença, energia, máscaras ou no analyzer de BLUE.

O bloqueio vinha da camada mais externa de entrada física entre CHECKS,
`display_f3_physical_transition_authority.py`. Para CHECKS posteriores ao H1,
essa autoridade ainda exigia identificação independente por contorno/estado
físico ou preferência entre as fotos do CHECK anterior e do CHECK atual.

Como as fotografias globais permaneciam ambíguas, a comparação H1 → BLUE podia
falhar mesmo quando o padrão funcional BLUE já estava integralmente identificado
pelas 28 máscaras. O resultado era uma contradição interna:

```text
BLUE semanticamente 28/28
+ presença confirmada
+ energia confirmada
+ gate produtivo liberado

mas

transição física H1 → BLUE = não confirmada
→ registro do CHECK vetado
```

### Correção D-043

A autoridade existente de transição foi corrigida; não foi criada uma segunda
autoridade.

Agora, para CHECKS posteriores, a transição também pode ser confirmada quando:

1. o CHECK anterior já está concluído;
2. a análise canônica pertence ao CHECK atual;
3. a análise está pronta e 100% conforme;
4. `matched_mask_count == active_mask_count`;
5. o padrão ON/OFF do CHECK atual difere do CHECK anterior em pelo menos uma
   máscara ativa.

A conformidade 100% prova somente que a função de destino já chegou fisicamente.
Ela não enfraquece D-031 e não transforma análise parcial em autorização.

Proteções mantidas:

- 27/28 não libera a transição;
- análise de outro CHECK não libera;
- CHECK anterior não concluído não libera;
- dois CHECKS com o mesmo padrão ON/OFF não podem provar transição um ao outro;
- um CHECK defeituoso continua precisando da identificação física independente
  da chegada antes que NG seja permitido;
- EMPTY, presença, energia, frescor, alinhamento e rearme mantêm precedência;
- nenhum timer, worker, scheduler ou thread foi adicionado.

### Estado

**D-042 VALIDADA FISICAMENTE. D-043 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Próximo reteste esperado

```text
tracking OFF
→ H1 correto 28/28
→ H1 CONCLUÍDO
→ mudar fisicamente para BLUE
→ BLUE mostra 18 ON + 10 OFF / 28 de 28
→ transição H1 → BLUE é confirmada pelo padrão semântico completo
→ BLUE CONCLUÍDO
→ sequência avança para USB
```

Teste negativo de segurança:

```text
BLUE com qualquer máscara divergente (ex.: 27/28)
→ NÃO usar D-043
→ NÃO concluir BLUE por conformidade parcial
```

---

## 30/09/2026 — D-043 validada fisicamente: BLUE 28/28 avançou para USB

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: DESATIVADO;
- H1 já havia sido concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- BLUE atingiu conformidade semântica completa das máscaras;
- o operador confirmou que, após a correção D-043, o CHECK não permaneceu mais
  preso em `BLUE BLOQUEADO • aguardando mudança física H1 → BLUE`.

### Resultado observado

O fluxo esperado foi confirmado no equipamento real:

```text
H1 28/28
→ H1 CONCLUÍDO
→ BLUE
→ padrão BLUE 100% conforme
→ transição H1 → BLUE confirmada
→ BLUE CONCLUÍDO
→ sequência segue para USB
```

### Conclusão

D-043 está **VALIDADA FISICAMENTE** para o caso que originou a correção.

A validação confirma que a conformidade canônica 100% de um CHECK de destino,
quando seu padrão ON/OFF difere do CHECK anterior já concluído, é evidência
suficiente da chegada física à nova função e não deve ser vetada por matching de
cena inteira ambíguo.

As proteções permanecem obrigatórias e não foram alteradas pela validação:

- leitura parcial continua sem usar D-043;
- padrão semanticamente igual ao anterior continua sem provar transição;
- análise de outro CHECK não libera o gate;
- NG continua dependendo de confirmação de chegada da função defeituosa;
- EMPTY, presença, energia, frescor e rearme continuam soberanos.

### Estado

**PASS — D-043 VALIDADA FISICAMENTE.**

---

## 30/09/2026 — BLUE NG real: MASK_024 esperada ON permaneceu OFF

**Resultado físico antes da correção:** FAIL de captura de NG.

### Cenário

- Rastreamento Automático: DESATIVADO;
- H1 já concluído;
- CHECK lógico atual: BLUE / CHECK_002;
- BLUE configurado com 18 máscaras ON + 10 OFF;
- defeito físico intencional/real observado: segmento 24 não acendeu junto com
  os demais segmentos esperados de BLUE.

### Evidência objetiva do DEBUG

No frame congelado do mesmo clique:

- gate produtivo: BLOQUEADO;
- motivo: placa não confirmada no suporte;
- análise bruta produtiva ficou sem autoridade enquanto o gate permaneceu
  fechado;
- a evidência física de energia do próprio BLUE estava disponível e dizia:
  `powered_confirmed=true`, 18 ON esperados, **17 votos powered + 1 voto off**;
- `MASK_024` estava configurada como ON em BLUE;
- `MASK_024` foi classificada fisicamente como OFF, `matched=false`, confiança
  aproximada de 0,845 e `winner_semantic=off`;
- a análise por aprendizado ON/OFF das fotos dos CHECKS fechou BLUE em **27/28**;
- nessa análise, a divergência observada era exatamente `MASK_024 expected=on /
  classified=off`.

### Causa confirmada

A primeira trava era consequência direta do contrato anterior de presença:
D-042 só promovia presença sem cena global quando algum CHECK configurado
formava um padrão semântico completo.

Isso funciona para produto BOM, mas é circular para NG:

```text
BLUE defeituoso
→ 17 ON corretos + MASK_024 OFF
→ energia física está confirmada
→ nenhum CHECK fica 100% conforme
→ presença semântica não confirma placa
→ energia perde autoridade produtiva
→ analyzer não pode registrar NG
```

Mesmo depois de destravar presença, havia uma segunda proteção a preservar:
D-043 permitia provar H1 → BLUE semanticamente somente com BLUE 100% conforme.
Não seria seguro simplesmente transformar qualquer 27/28 em chegada, pois um
frame ainda em H1 poderia ser reprovado como BLUE antes da mudança física.

### Correção D-044

A correção foi aplicada nos proprietários existentes:

1. `F3PresenceAuthority` agora aceita a votação multi-máscara
   `powered_confirmed` como prova de **ocupação física** quando nenhum CHECK está
   completo. Nesse modo ela não inventa identidade de CHECK.
2. A autoridade de transição H1 → BLUE agora possui uma assinatura semântica
   adicional para CHECK defeituoso: considera somente máscaras cujo ON/OFF muda
   entre H1 e BLUE e exige maioria estrita dessas diferenças no padrão BLUE.
3. A assinatura confirma somente que BLUE chegou; ela não concede OK e não cria
   NG.
4. O analyzer estrito e o debounce NG existente continuam decidindo o defeito.
5. Se a assinatura ainda preferir H1, o NG permanece bloqueado.
6. EMPTY confirmado continua soberano.
7. Nenhum timer, worker, scheduler, thread ou autoridade paralela foi criado.

### Proteção contra regressão

Foram adicionados testes para:

- placa energizada com CHECK divergente ainda confirmar presença;
- emissão insuficiente não promover presença;
- BLUE 27/28 com assinatura H1 → BLUE predominantemente no destino confirmar a
  chegada física;
- assinatura ainda em H1 continuar bloqueando;
- o guard final permitir registrar `False/NG` somente depois da chegada
  semântica confirmada.

### Estado

**CORREÇÃO D-044 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
tracking OFF
→ H1 correto conclui
→ entrar em BLUE
→ manter MASK_024 fisicamente apagada
→ presença permanece confirmada
→ energia permanece confirmada
→ assinatura H1 → BLUE confirma chegada
→ analyzer identifica MASK_024 esperada ON / observada OFF
→ debounce NG existente confirma falha
→ placa recebe NG terminal
→ NÃO avançar para USB
→ TOTAL +1 e NG +1 exatamente uma vez
→ aguardar retirada/rearme conforme contrato terminal
```

---

## 01/10/2026 — D-044 validada fisicamente: BLUE com MASK_024 apagada gerou NG

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: DESATIVADO;
- H1 concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- BLUE com defeito real reproduzido;
- segmento 24 / `MASK_024`, configurado como ON em BLUE, permaneceu fisicamente
  APAGADO enquanto os demais segmentos esperados acenderam.

### Resultado observado

O operador confirmou no equipamento real que, após a correção D-044, o ODIN
passou a capturar corretamente esse caso como **NG**.

Fluxo físico validado:

```text
H1 correto
→ H1 CONCLUÍDO
→ BLUE chega fisicamente
→ energia permanece confirmada apesar da MASK_024 OFF
→ presença permanece confirmada
→ assinatura H1 → BLUE confirma a chegada da função
→ analyzer mantém MASK_024 como divergente
→ BLUE não recebe OK
→ defeito é confirmado como NG
```

### Conclusão

D-044 está **VALIDADA FISICAMENTE** no cenário que originou a correção.

A validação confirma que:

- uma placa energizada com defeito não precisa formar um CHECK 100% conforme
  para continuar sendo reconhecida como presente;
- a chegada a BLUE pode ser provada pela assinatura das máscaras que mudaram em
  relação a H1, sem transformar conformidade parcial em OK;
- a `MASK_024` apagada permanece disponível para a autoridade semântica de NG;
- o produto defeituoso não avança como BLUE aprovado;
- a correção não depende de Rastreamento Automático.

### Estado

**PASS — D-044 VALIDADA FISICAMENTE.**

---

## 01/10/2026 — D-045: NG correto, mas segmento defeituoso ainda sem destaque vermelho

**Resultado físico antes da correção visual:** FAIL de apresentação / PASS de decisão NG.

### Cenário

- CHECK lógico: BLUE / CHECK_002;
- placa já havia sido corretamente classificada como NG por D-044;
- frame e visor estavam congelados aguardando retirada da placa;
- `MASK_024` era o segmento defeituoso confirmado: deveria estar ON e permaneceu
  OFF;
- requisito do operador: o segmento 24 deve ficar vermelho tanto na máscara da
  câmera congelada quanto no VISOR DO DISPLAY.

### Evidência do DEBUG

O snapshot congelado mostrou:

- placa presente e energia confirmada;
- CHECK lógico BLUE;
- fluxo já em rearme terminal aguardando retirada;
- análise BLUE bruta com múltiplas divergências visuais no frame congelado;
- porém a autoridade efetiva publicou uma lista específica de falha persistente
  confirmada, distinta das divergências ainda transitórias;
- o visor/overlay continuavam priorizando o caminho luminoso ON/OFF e, por isso,
  uma máscara confirmada NG podia permanecer verde escuro em vez de vermelho.

### Causa

O contexto já carregava `effective_confirmed_failed_mask_ids`, mas os dois
renderers finais tinham uma precedência incorreta:

1. a câmera entrava em `live_luminous_only` e retornava pelo renderer clássico
   antes de aplicar o destaque de falha confirmada;
2. o VISOR DO DISPLAY também entrava primeiro no ramo `live_luminous_only`,
   ignorando o conjunto `failed_mask_ids` já filtrado para falhas confirmadas.

A decisão NG estava correta; faltava somente refletir a mesma autoridade na
apresentação congelada.

### Correção D-045

- câmera: `effective_confirmed_failed_mask_ids` agora tem prioridade sobre
  verde/verde escuro no renderer clássico;
- visor: `failed_mask_ids` confirmado recebe estado visual `ng` antes do ramo
  `live_luminous_only`;
- a fonte do vermelho final continua sendo somente a lista confirmada;
- `effective_failed_mask_ids` bruto e `effective_validating_mask_ids` não viram
  vermelho terminal;
- SEGREGAR continua com sua regra própria de vermelho total;
- nenhuma regra de decisão, debounce, energia, tracking ou rearme foi alterada.

### Proteção contra regressão

Foram adicionados testes para confirmar que:

1. câmera live/frozen pinta a máscara confirmada em vermelho enquanto mantém as
   demais máscaras ON/OFF em verde/verde escuro;
2. VISOR DO DISPLAY dá prioridade a vermelho para a falha confirmada mesmo no
   modo `live_luminous_only`;
3. o contexto do visor prefere `effective_confirmed_failed_mask_ids` à lista
   bruta de falhas.

### Estado

**D-045 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO VISUAL.**

### Reteste esperado

```text
tracking OFF ou ON
→ reproduzir BLUE NG com MASK_024 apagada
→ NG terminal congelado
→ somente MASK_024 fica vermelha na máscara da câmera
→ somente segmento 24 fica vermelho no VISOR DO DISPLAY
→ demais segmentos mantêm verde/verde escuro conforme ON/OFF físico
→ retirar placa
→ rearme continua normal
```

---

## 01/10/2026 — Reteste D-045 FAIL: MASK_024 continuou verde após o NG

**Resultado físico:** FAIL de apresentação. A decisão NG permaneceu correta.

### Evidência visual

No estado terminal mostrado na Produção Display F3:

- a tela principal estava em `PLACA NG / RETIRE A PLACA`;
- H1 permanecia concluído e BLUE era o CHECK que falhou;
- TOTAL=1, OK=0, NG=1;
- a câmera estava congelada no padrão BLUE;
- a máscara/segmento 24 continuava em verde escuro;
- o segmento 24 do VISOR DO DISPLAY também continuava em verde escuro.

Portanto, a primeira implementação de D-045 funcionava nos testes isolados do
renderer, mas não atingia a apresentação realmente congelada no fluxo completo.

### Evidência do DEBUG do mesmo caso

O relatório confirmou:

- CHECK lógico BLUE;
- NG/rearme já aguardando retirada da placa;
- análise semântica do BLUE em 27/28;
- `effective_confirmed_failed_mask_ids=['MASK_024']`;
- `effective_validating_mask_ids=[]`;
- no contexto reconstruído para o visor, `MASK_024` aparecia classificada como
  `off`, esperada `on` e listada como falha.

Isso descartou erro de classificação/autoridade. O ID correto existia; o
problema estava entre a confirmação final do NG e o repaint que ficou preservado
pelo latch visual.

### Causa de integração confirmada

O freeze ocorria depois de um último `update_camera_preview`, mas esse último
repaint ainda dependia do contexto live existente naquele instante. Em um CHECK
intermitente, a confirmação persistente pode ser publicada no fechamento do
debounce depois que o contexto visual usado pelo último repaint já havia sido
montado.

Assim, os testes unitários provavam corretamente que o renderer sabe pintar
`MASK_024` de vermelho quando recebe a lista confirmada, mas o canvas real podia
ser congelado com a versão imediatamente anterior do contexto.

Foi encontrado ainda um problema de observabilidade: a auditoria manual
reconstruía `visual_state.readout_context` sobre o frame congelado e substituía o
snapshot visual capturado da janela. Isso podia fazer o DEBUG mostrar a falha
corretamente mesmo quando o canvas real não a havia pintado.

### Segunda correção D-045

A apresentação terminal passou a ser determinística:

1. `freeze_ng_evidence(...)` recebe os IDs confirmados da análise exata que
   fechou o NG;
2. após levantar o latch, o readout congelado é sincronizado explicitamente e
   redesenhado;
3. o frame exato do NG é repintado diretamente após o freeze usando a geometria
   já congelada e `effective_confirmed_failed_mask_ids` da análise terminal;
4. esse repaint não captura novo frame e não roda nova análise;
5. os segmentos do canvas agora possuem tags por máscara/estado para diagnóstico
   do fill realmente desenhado;
6. o DEBUG preserva `runtime_visual_state_before_manual_recompute`, mantendo a
   evidência da janela antes de qualquer reconstrução manual;
7. nenhuma autoridade, thread, worker, timer ou scheduler novo foi criado.

### Testes adicionados

Foram adicionadas regressões que verificam:

- o freeze reaplica `MASK_024` no conjunto de falha do visor congelado;
- o repaint pós-freeze do frame terminal pinta `MASK_024` em vermelho e mantém
  os demais segmentos nas cores ON/OFF;
- o contexto diagnóstico preserva separadamente falhas brutas, confirmadas e em
  validação;
- o DEBUG salva o estado visual runtime antes de recalculá-lo.

### Estado

**SEGUNDA CORREÇÃO D-045 IMPLEMENTADA — PENDENTE DE NOVO RETESTE FÍSICO.**

### Reteste esperado

```text
reproduzir BLUE com MASK_024 fisicamente OFF
→ BLUE gera NG
→ PLACA NG / RETIRE A PLACA
→ câmera congela
→ SOMENTE a máscara 24 fica VERMELHA
→ no VISOR DO DISPLAY, SOMENTE o segmento 24 fica VERMELHO
→ demais ON permanecem verdes
→ demais OFF permanecem verde escuro
→ retirar placa
→ EMPTY/rearme segue normal
```

---

## 01/10/2026 — Reteste D-045 PASS: MASK_024 vermelha na câmera e no visor

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: desativado;
- H1 concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- `MASK_024` configurada como ON em BLUE e mantida fisicamente OFF;
- o ODIN confirmou o BLUE como NG e congelou a evidência terminal.

### Resultado observado

O operador confirmou no equipamento real que a segunda correção D-045 passou:

```text
BLUE com MASK_024 apagada
→ NG confirmado
→ PLACA NG / RETIRE A PLACA
→ câmera congela a evidência
→ máscara 24 fica VERMELHA na câmera
→ segmento 24 fica VERMELHO no VISOR DO DISPLAY
→ demais segmentos continuam com cores ON/OFF normais
```

### Conclusão

A falha visual de integração entre confirmação final do debounce e freeze foi
resolvida. O repaint terminal agora usa o mesmo frame/análise que fechou o NG e
reafirma `effective_confirmed_failed_mask_ids` depois do latch visual.

Com isso, D-045 está **VALIDADA FISICAMENTE** para o caso que originou a
correção: `MASK_024` apagada em BLUE é destacada em vermelho tanto na máscara da
câmera congelada quanto no VISOR DO DISPLAY.

### Estado

**PASS — D-045 VALIDADA FISICAMENTE.**

---

## 01/10/2026 — D-046: AUX aprovado correto, mas espelho visual mostrou falso ON e perdeu cores ao encerrar

**Resultado físico antes da correção:** PASS de decisão / FAIL de apresentação.

### Cenário

- sequência completa concluída com PLACA APROVADA;
- último estado físico da placa: AUX;
- AUX estava correto no equipamento;
- `MASK_010` em AUX deveria permanecer OFF;
- o VISOR DO DISPLAY mostrou o segmento 10 verde como se estivesse ON;
- após encerrar as análises, as máscaras da câmera também podiam voltar a cinza
  em vez de continuar reagindo ao estado luminoso enquanto a placa permanecia
  no suporte.

### Evidência do DEBUG

O relatório confirmou que o resultado produtivo não estava errado:

- aprendizado same-mask de AUX: `approved=True`, `matched=28/28`;
- `MASK_010` de AUX: `expected=off`, `classified=off`, `matched=true`;
- presença semântica: CHECK_003 / AUX;
- portanto o verde da MASK_010 no visor era somente erro do espelho visual.

A telemetria visual mostrou ao mesmo tempo:

- `live_visual_mask_ids` incluía `MASK_010`, gerado pelo sampler leve de brilho;
- o hook caiu em `fixed_render_exception`;
- erro: `_render_check_cards_f3_fixed() got an unexpected keyword argument
  'force_terminal_segregated'`;
- caminho de render virou `previous_window_update`.

### Causa

Foram confirmadas duas causas de apresentação:

1. o sampler visual latest-frame tinha prioridade absoluta e podia transformar
   brilho/glare dentro da ROI em falso ON mesmo quando a autoridade física
   same-mask do mesmo frame dizia OFF;
2. o wrapper de cards do layout fixo estava com assinatura antiga, quebrando o
   hook visual quando o estado terminal tentava usar `force_terminal_segregated`.

### Correção D-046

- se a autoridade física same-mask e o sampler observam o mesmo frame, a leitura
  same-mask prevalece visualmente;
- o sampler continua preenchendo máscaras sem classificação física e substituindo
  estado stale de frame anterior;
- o renderer fixo de cards passou a aceitar `force_terminal_segregated` e
  preservar o comportamento terminal;
- PLACA APROVADA não congela câmera/visor: o espelho visual continua live até
  EMPTY/rearme;
- NG congelado continua seguindo D-045 e SEGREGAR continua seguindo D-040;
- telemetria agora publica `live_visual_same_physical_frame` e os dois tokens de
  frame para diagnóstico.

### Estado

**D-046 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
AUX correto com MASK_010 fisicamente OFF
→ AUX conclui 28/28
→ PLACA APROVADA
→ segmento 10 permanece verde escuro no VISOR
→ máscaras da câmera continuam verdes/verde-escuro conforme o estado físico
→ alterar visualmente algum segmento ainda no suporte atualiza câmera + visor
→ nenhuma máscara volta a cinza apenas porque o ciclo terminou
→ retirar placa
→ EMPTY/rearme normal
```

---

## 01/10/2026 — FAIL: NG permaneceu congelado após retirada da placa do suporte

**Resultado físico:** FAIL de rearme/apresentação após retirada da placa.

### Cenário observado

- Display F3 em ciclo produtivo normal;
- uma placa concluiu o ciclo com resultado **NG**;
- durante o estado terminal, a apresentação ficou corretamente congelada em NG;
- o operador retirou fisicamente a placa do suporte;
- após a retirada, a tela permaneceu congelada no NG em vez de retornar ao estado normal de espera/rearme.

### Comportamento esperado

A retirada física da placa deve encerrar imediatamente a apresentação terminal da
placa anterior e liberar o F3 para o estado normal de espera/rearme.

O resultado anterior deve continuar identificável visualmente, porém em sua
variante escura/inativa:

- após **OK**, o verde terminal deve voltar para **verde escuro**;
- após **NG**, o vermelho terminal deve voltar para **vermelho escuro**;
- câmera/visor não podem permanecer congelados no frame terminal depois que a
  placa já saiu do suporte;
- a retirada da placa deve encerrar qualquer latch/freeze pertencente ao ciclo
  anterior e preparar a interface para a próxima placa.

### Sintoma observado

    placa gera NG
    → F3 congela corretamente no resultado NG
    → operador retira a placa do suporte
    → apresentação continua congelada no NG
    → F3 não volta ao estado visual normal de rearme/espera

### Evidência objetiva disponível

Neste relato não foi anexado DEBUG técnico. A evidência disponível é a observação
física direta do equipamento: a placa foi retirada do suporte, mas o estado visual
terminal de NG permaneceu congelado.

### Causa

**Ainda não diagnosticada.**

O próximo diagnóstico deve verificar o caminho que transforma a confirmação de
EMPTY/retirada física em limpeza do freeze/latch terminal e atualização da
apresentação pós-ciclo, sem alterar as regras já validadas de congelamento do NG
enquanto a placa ainda permanece no suporte.

### Alteração aplicada

Nenhuma. Este registro documenta somente o FAIL físico relatado.

### Próximo reteste esperado

    placa conclui OK ou NG
    → resultado terminal é mostrado normalmente enquanto a placa permanece no suporte
    → retirar fisicamente a placa
    → EMPTY/rearme é reconhecido
    → qualquer freeze/latch da placa anterior é encerrado
    → OK anterior passa para verde escuro
    → NG anterior passa para vermelho escuro
    → câmera/visor deixam de permanecer congelados no frame da placa retirada
    → F3 fica pronto para receber a próxima placa

### Estado

**FAIL REGISTRADO — PENDENTE DE DIAGNÓSTICO E CORREÇÃO.**

---

## 01/10/2026 — Correção do freeze NG após EMPTY confirmado

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Causa confirmada no código

O rearme físico já reconhecia corretamente a transição
`RESULTADO TERMINAL → EMPTY → AGUARDANDO NOVA PLACA`, porém o guard final
publicava a tela de espera chamando diretamente `show_waiting_new_plate()`.

No NG automático existem dois latches visuais coordenados:

- `_display_f3_ng_evidence_frozen` no runtime, que impede o repaint live;
- `_display_ng_evidence_frozen` na janela, que preserva câmera/visor congelados.

O método canônico `_liberar_evidencia_ng_display_f3()` já desmontava os dois
latches e só deveria ser executado depois que EMPTY estivesse confirmado, mas o
handoff final não o chamava. Assim, o estado físico avançava para suporte vazio
enquanto o preview continuava bloqueado pelo flag da placa NG anterior.

### Alteração aplicada

- o guard terminal passa pelo `_liberar_evidencia_ng_display_f3()` quando a
  transição de `waiting_empty` para `waiting_new_board` ocorre com evidência
  NG congelada;
- o caminho existente continua sendo usado para OK/SEGREGAR, sem criar timer,
  worker, scheduler ou autoridade paralela;
- `show_waiting_new_plate()` passa a escolher a cor escura pela memória
  `last_result`: OK usa verde escuro e NG usa vermelho escuro;
- o tema completo da janela recebe a mesma escolha imediatamente após EMPTY,
  em vez de assumir `ng_waiting` para qualquer resultado;
- D-045 permanece intacta: enquanto a placa NG ainda estiver no suporte, câmera
  e visor continuam congelados no frame exato que fechou o NG.

### Regressões adicionadas

- transição NG congelado → EMPTY confirma que o liberador canônico é chamado,
  o flag de freeze do runtime é removido e a UI entra uma única vez na espera
  por nova placa;
- seleção do tema pós-EMPTY confirma `ok_waiting` para último resultado OK e
  `ng_waiting` para último resultado NG.

### Reteste físico esperado

    placa gera NG
    → NG permanece congelado enquanto a placa está no suporte
    → retirar a placa
    → EMPTY é confirmado pelo rearme físico
    → freeze do runtime e da janela é liberado
    → câmera deixa imediatamente o frame congelado
    → tela entra em espera com identidade VERMELHO ESCURO
    → nova placa confirmada libera H1

Teste complementar:

    placa gera OK
    → retirar a placa
    → EMPTY confirmado
    → tela entra em espera com identidade VERDE ESCURO
    → nova placa confirmada libera H1

---

## 01/10/2026 — Reteste pós-correção: NG continuou congelado após retirada

**Resultado físico:** FAIL.

### Cenário

- placa entrou em NG normalmente;
- congelamento terminal do NG funcionou como esperado enquanto a placa permaneceu no suporte;
- a placa foi retirada fisicamente;
- visualmente, a câmera/visor continuaram presos no NG anterior;
- comportamento esperado: ao confirmar suporte vazio, o freeze deve ser encerrado e a interface deve voltar ao estado de espera normal da próxima placa.

### Evidência disponível

Neste reteste foi reportada evidência visual do equipamento. Não foi fornecido novo DEBUG textual.

A primeira correção havia passado nos testes unitários de `final_rearm_guard`, porém isso não representava a composição final do produto.

### Causa encontrada no caminho real

`DesktopProductionApp.__init__()` instala o rearme dedicado e o guard terminal,
mas, no final do bootstrap de `main_desktop.py`,
`instalar_autoridades_runtime_display_f3(app)` substitui
`operational_module._build_operational_state` pelo `canonical_builder`.

O builder canônico chamava apenas `aplicar_gate_rearme_ciclo_f3()`.
Esse gate libera o ciclo somente quando o classificador geral já devolve
`kind="empty"`.

O detector dedicado de rearme — criado justamente para o caso em que a cena
vazia ainda pode ser confundida com H1/um CHECK antigo e para usar a comparação
relativa EMPTY x placa — ficava fora do caminho final. Assim:

    placa NG retirada
    → builder canônico continua vendo estado geral não-EMPTY
    → waiting_empty_rearm permanece ativo
    → _liberar_evidencia_ng_display_f3() não é alcançado
    → câmera/visor continuam congelados corretamente pelo latch NG

### Correção aplicada

A responsabilidade foi consolidada dentro de `F3RuntimeAuthorities`, que é a
autoridade final do runtime:

- quando não existe rearme pendente, o fluxo normal permanece inalterado;
- quando `waiting_empty_rearm` ou `waiting_new_board_after_empty` está ativo,
  o builder canônico chama `aplicar_rearme_fisico_dedicado_f3()`;
- o detector dedicado mantém debounce de EMPTY, comparação específica de suporte
  vazio e a fase explícita de nova placa;
- ao confirmar EMPTY, o caminho existente chama
  `_liberar_evidencia_ng_display_f3()`, desmontando os latches de runtime e
  janela;
- nenhuma nova thread, timer, fila, scheduler ou segunda autoridade foi criada.

### Regressão adicionada

O teste do próprio `F3RuntimeAuthorities.build_operational_state()` agora exige
que, durante `waiting_empty_rearm`, o builder canônico use o rearme dedicado e
não o gate simples.

### Próximo reteste esperado

    gerar NG
    → manter placa no suporte
    → confirmar que NG continua congelado
    → retirar a placa
    → EMPTY dedicado confirma a retirada
    → freeze NG é liberado
    → câmera volta ao live mostrando o suporte vazio
    → tela entra em espera vermelho-escuro por ter vindo de NG
    → inserir nova placa
    → após confirmação física, H1 volta a ficar ativo

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE NOVO RETESTE FÍSICO.

---

## 01/10/2026 — PASS físico: NG libera freeze após retirada da placa

**Resultado físico:** PASS.

### Cenário validado

- o F3 concluiu uma placa em NG;
- enquanto a placa permaneceu fisicamente no suporte, câmera e VISOR DO DISPLAY permaneceram congelados no frame terminal do NG conforme D-045;
- o operador retirou a placa do suporte;
- o rearme dedicado confirmou o suporte vazio;
- o freeze terminal foi encerrado;
- câmera/visor voltaram ao estado normal de espera;
- a interface deixou de permanecer presa visualmente no NG anterior.

### Resultado observado

O comportamento esperado foi confirmado no equipamento real:

    placa gera NG
    → NG permanece congelado enquanto a placa está no suporte
    → operador retira a placa
    → EMPTY é confirmado
    → freeze NG é liberado
    → câmera/visor deixam o frame congelado
    → F3 volta ao estado normal de espera/rearme

### Correção validada

Commit validado fisicamente:

`a4966084efca890490291192d343ee017c0d6c02`
— `fix(f3): integrar rearme dedicado na autoridade canônica`.

A validação confirma que o rearme dedicado precisa permanecer integrado em
`F3RuntimeAuthorities`, pois essa é a autoridade final instalada no runtime.
Não é suficiente depender apenas de wrappers anteriores de
`_build_operational_state`, porque eles podem ser substituídos pela composição
canônica posterior.

### Estado

**PASS FÍSICO — CORREÇÃO VALIDADA.**

---

## 01/10/2026 — Zoom de câmera e zoom ODIN no Projeto Display

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Requisito

Adicionar dentro de **CONFIGURAR** do F3 dois controles independentes:

- zoom digital da Logitech BRIO/driver;
- zoom por software do próprio ODIN.

### Implementação

O Projeto Display passou a persistir:

- `camera_zoom.enabled`;
- `camera_zoom.value` entre 100 e 500;
- `software_zoom` entre 1.0× e 5.0×.

A janela **Projeto Display** possui agora a seção
`ZOOM DA CÂMERA / ODIN`, com:

- checkbox para habilitar o zoom da câmera;
- slider de 1× a 5× para o zoom da câmera;
- slider de 1× a 5× para o zoom ODIN;
- ação `Salvar e aplicar zoom`;
- aviso para revisar referências, contorno e máscaras depois de alterar o
  enquadramento.

### Zoom da câmera

O serviço canônico de câmera recebeu suporte a `CAP_PROP_ZOOM`.

No perfil BRIO/DirectShow:

    100 → 1×
    ...
    500 → 5×

O mesmo mecanismo usado para foco/ganho/exposição confirma o ajuste por
readback e aceita passos discretos do driver. Ao sair do F3, o controle é
desabilitado e o baseline anterior é restaurado.

### Zoom ODIN

O zoom por software:

    frame bruto
    → crop central conforme fator de zoom
    → resize para a resolução original
    → frame F3 derivado

O `F3RuntimeCoordinator` publica temporariamente essa mesma visão derivada para
todo o ciclo F3, de modo que câmera ao vivo, tracking, presença, energia,
máscaras, CHECKS, análise OK/NG e congelamento terminal trabalhem sobre o mesmo
frame.

O frame bruto global da câmera permanece preservado para não alterar o F2.

### Performance

O frame ampliado por software é armazenado em cache por:

- frame da câmera;
- Projeto Display;
- fator de zoom;
- resolução.

Repintar o mesmo frame não refaz o `crop + resize`.

Nenhum novo timer, worker, scheduler ou loop foi criado.

### Reteste físico esperado

1. abrir F3 → CONFIGURAR;
2. habilitar **zoom digital da câmera**;
3. testar aproximadamente 1×, 2× e 3× e confirmar se a BRIO/DirectShow aceita;
4. salvar e confirmar que o enquadramento permanece no projeto;
5. testar **zoom ODIN** em 1×, 1.5×, 2× e 3×;
6. confirmar que preview e máscaras observam exatamente a mesma imagem ampliada;
7. fechar e reabrir o F3 e confirmar persistência do Projeto Display;
8. fechar o F3 e confirmar que o zoom de hardware não permanece contaminando o F2;
9. após escolher o zoom definitivo, recapturar/revisar referência, contorno e
   máscaras antes de validar produção.

**Validação física:** pendente.

---

## 01/10/2026 — PASS físico: zoom de câmera e zoom ODIN

**Resultado físico:** PASS.

### Cenário validado

Após a implementação da D-047, o operador testou no F3 os controles de zoom
adicionados ao Projeto Display e confirmou que o comportamento funcionou no
equipamento real.

Foram validados no fluxo real de configuração:

- controle de zoom digital da câmera exposto ao F3;
- controle de zoom por software do ODIN;
- aplicação do zoom no fluxo do Display F3.

Não foi fornecido novo DEBUG textual neste reteste; a validação reportada foi
visual/operacional.

### Estado

**PASS FÍSICO — CONTROLES DE ZOOM VALIDADOS.**

A próxima evolução solicitada é tornar o enquadramento configurável visualmente:
preview ao vivo + janela de captura arrastável para escolher qual região da
imagem ampliada será efetivamente entregue à câmera do Display F3.

---

## 01/10/2026 — Enquadramento arrastável e preview ao vivo do zoom

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Requisito

Após o PASS físico dos controles de zoom, foi solicitado:

- uma visualização ao vivo da câmera dentro das configurações do F3;
- uma segunda visualização que funcione como a "câmera virtual" do ODIN;
- possibilidade de clicar/arrastar a janela de enquadramento para escolher
  exatamente qual região ampliada será exibida e analisada pelo F3 Display.

### Implementação

A seção de zoom da configuração passou a exibir:

1. **ENQUADRAMENTO • ARRASTE A JANELA**
   - mostra o frame-fonte ao vivo;
   - desenha um retângulo sobre a região que o zoom ODIN recortará;
   - clique ou arraste reposiciona o centro do recorte;
   - o retângulo é limitado para não sair da imagem.

2. **VISUALIZAÇÃO AO VIVO • SAÍDA FINAL DO F3**
   - mostra o frame após zoom ODIN;
   - usa o mesmo centro X/Y;
   - mantém a resolução de saída;
   - aplica também a rotação visual usada pela câmera do F3.

O centro do recorte é persistido por Projeto Display como coordenadas
normalizadas `software_zoom_center.x/y`.

### Runtime e performance

- o `F3RuntimeCoordinator` continua sendo o único scheduler periódico;
- durante cada callback ele mantém disponível o frame bruto apenas para o
  seletor visual e entrega a visão transformada ao runtime F3;
- não foi criado novo `after()`, worker, fila ou thread para o preview;
- durante CONFIGURAR a cadência de repaint foi ajustada para aproximadamente
  10 FPS, sem executar o pipeline pesado de análise;
- o frame global bruto é restaurado ao final do callback.

### Reteste físico esperado

    abrir F3 → CONFIGURAR
    → ajustar zoom da câmera e/ou zoom ODIN
    → confirmar imagem ao vivo no quadro de enquadramento
    → arrastar a janela para a região desejada
    → confirmar que SAÍDA FINAL DO F3 acompanha imediatamente
    → Salvar e aplicar zoom
    → fechar CONFIGURAR
    → confirmar que a câmera produtiva do F3 mostra exatamente o enquadramento salvo
    → fechar/reabrir F3
    → confirmar persistência do mesmo enquadramento

Depois de definir o enquadramento definitivo, revisar/recapturar referências,
contorno e máscaras antes de validar inspeção produtiva.

**Validação física:** pendente.

---

## 01/10/2026 — FAIL físico: CONFIGURAR deixou de abrir após preview/enquadramento de zoom

**Resultado físico:** FAIL.

### Cenário

Após a implementação do preview ao vivo e do enquadramento arrastável do zoom,
o operador abriu o F3 e tentou acessar **CONFIGURAR**.

### Sintoma observado

- a janela **CONFIGURAR** não abriu;
- o sistema apresentou erro durante a tentativa de construção da janela;
- o problema surgiu após a inclusão dos novos widgets de preview/enquadramento.

Não foi fornecido traceback textual deste teste físico.

### Diagnóstico

O smoke em Linux/Xvfb abria a janela, portanto o problema foi tratado como
incompatibilidade/ordem de construção do Tk no ambiente Windows real.

Foram identificados dois riscos introduzidos pela nova UI:

1. os `Scale` de zoom possuem callbacks e alguns builds do Tk podem dispará-los
   durante a construção do widget, antes de `zoom_source_canvas` e
   `zoom_final_canvas` existirem;
2. o cursor `"fleur"` usado no canvas de arraste depende do backend Tk e não é
   necessário para a regra funcional.

### Correção aplicada

- `zoom_source_canvas` e `zoom_final_canvas` agora nascem explicitamente como
  `None` antes da criação dos sliders;
- `_rerender_zoom_preview()`, `update_live_zoom_preview()` e o desenho do
  viewport retornam com segurança enquanto os canvases ainda não existem;
- o cursor do viewport passou de `"fleur"` para `"hand2"`, já usado no ODIN
  e mais seguro entre Windows/Linux;
- nenhum novo timer, worker, scheduler ou autoridade foi criado;
- o runtime de inspeção e as regras de zoom/enquadramento não foram alterados.

### Regressão

Foi adicionado teste que chama o caminho de rerender antes da existência dos
canvases e exige que a operação não gere exceção. O contrato também proíbe o
retorno do cursor `"fleur"` nessa janela.

### Próximo reteste esperado

    abrir F3
    → clicar CONFIGURAR
    → janela deve abrir normalmente
    → seção de zoom deve aparecer
    → preview ao vivo deve carregar
    → viewport deve aceitar clique/arraste

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 01/10/2026 — Segundo FAIL físico: CONFIGURAR continua sem abrir

**Resultado físico:** FAIL.

### Cenário

Após a primeira correção defensiva para a nova UI de zoom, o operador repetiu:

    F3
    → CONFIGURAR

### Sintoma observado

- a janela ainda não abriu;
- ao clicar, aparentemente nada acontece;
- não foi exibido traceback ou mensagem útil ao operador.

### Regra das duas tentativas

Este é o segundo FAIL consecutivo do mesmo defeito de abertura de CONFIGURAR.
Conforme AGENTS.md, a etapa seguinte não altera novamente o algoritmo da UI sem
evidência. O trabalho passa para **diagnóstico/instrumentação**.

### Diagnóstico encontrado no caminho de abertura

O método `abrir_configuracao_projeto_display()` captura qualquer exceção do
construtor e grava apenas:

- `_display_f3_last_config_error`.

A exceção era escondida do operador. O status visual também pode não ser
percebido porque a própria janela CONFIGURAR não chegou a existir.

Além disso, o smoke anterior construía a janela com
`frame_provider=lambda: None`, portanto não exercitava a parte nova que:

- recebe frame real;
- renderiza os dois canvases de zoom;
- cria `PhotoImage`;
- aplica callback de preview do zoom físico.

### Instrumentação aplicada

Sem alterar novamente a regra de zoom/enquadramento:

- o traceback completo agora é salvo em
  `_display_f3_last_config_traceback`;
- o traceback também é enviado ao console;
- a falha de abertura agora exibe uma caixa
  **F3 • Erro ao abrir CONFIGURAR** com tipo e mensagem reais da exceção;
- o smoke de CONFIGURAR foi ampliado para usar um frame NumPy 1920x1080 real,
  `source_frame_provider` e callback de zoom físico;
- o teste exige que os canvases e os dois `PhotoImage` de preview tenham sido
  realmente construídos.

### Próximo reteste esperado

    clicar CONFIGURAR
    → se abrir: registrar PASS
    → se ainda falhar: copiar exatamente a mensagem exibida
      em "F3 • Erro ao abrir CONFIGURAR"

Com essa mensagem será possível atacar a causa específica sem terceira tentativa
às cegas.

**Estado:** DIAGNÓSTICO/INSTRUMENTAÇÃO IMPLEMENTADOS — AGUARDANDO EVIDÊNCIA REAL.

---

## 01/10/2026 — Causa reproduzida do CONFIGURAR: contrato de construtor desatualizado

**Estado:** CAUSA IDENTIFICADA E CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Reprodução objetiva

Após o segundo FAIL físico, o smoke de CONFIGURAR foi ampliado para abrir a
janela final com:

- frame NumPy 1920x1080 real;
- `source_frame_provider`;
- callback `on_camera_zoom_preview`;
- construção dos dois canvases e dos dois `PhotoImage`.

O CI reproduziu o mesmo defeito de abertura com:

    TypeError:
    presence_init() got an unexpected keyword argument 'source_frame_provider'

### Causa

`display_f3_runtime_contract_fix._install_configuration_constructor_contract()`
instala wrappers explícitos sobre o construtor de CONFIGURAR.

Esses wrappers ainda descreviam o contrato anterior:

    root
    repository
    frame_provider
    heavy_executor
    on_change
    on_close

A nova configuração de zoom acrescentou:

    source_frame_provider
    on_camera_zoom_preview

O construtor real aceitava os novos argumentos, mas o wrapper final
`presence_init` os rejeitava antes que a janela fosse criada. Por isso:

    clicar CONFIGURAR
    → build()
    → DisplayProjectConfigPresenceWindow(...)
    → wrapper presence_init antigo
    → TypeError
    → exceção capturada
    → janela não aparece

### Correção aplicada

O contrato explícito foi atualizado no proprietário do wrapper:

- `DisplayProjectConfigWindow.__init__` wrapper agora aceita e encaminha
  `source_frame_provider` e `on_camera_zoom_preview`;
- `DisplayProjectConfigPresenceWindow.__init__` wrapper agora aceita e encaminha
  os mesmos argumentos;
- o teste permanente do contrato passou a exigir esses dois parâmetros;
- a instrumentação de erro visível permanece ativa para que futuras falhas de
  abertura não sejam silenciosas.

### Próximo reteste esperado

    F3
    → CONFIGURAR
    → janela abre
    → preview fonte aparece
    → saída final aparece
    → zoom físico/software respondem
    → viewport aceita clique/arraste

**Validação física:** pendente.

---

## 01/10/2026 — FAIL físico: viewport de zoom não arrasta e enquadramento volta

**Resultado físico:** FAIL.

### Cenário

Com **CONFIGURAR** novamente abrindo, o operador testou o novo viewport
arrastável da seção de zoom.

### Sintoma observado

- o cursor de mão aparece sobre a área de enquadramento;
- ao tentar pegar e arrastar a janela, ela não acompanha corretamente o mouse;
- durante a tentativa, o zoom/enquadramento visual parece se desfazer.

Não foi fornecido traceback porque o problema é comportamental/visual e a
janela permanece aberta.

### Causa identificada no código

O primeiro contrato de drag fazia duas coisas inadequadas para uma interação
contínua:

1. cada evento `<B1-Motion>` chamava `_rerender_zoom_preview()`;
2. esse rerender reconstruía o canvas-fonte inteiro com `delete("all")`,
   recriando imagem, viewport e cruz central enquanto o botão do mouse ainda
   estava pressionado.

Além disso, o centro do viewport é definido exclusivamente pelo
`software_zoom`. Em `1×`, o recorte é o frame inteiro e o normalizador fixa
o centro em 50%/50%; portanto não existe margem física para deslocar a janela.
O zoom digital da BRIO continua sendo um zoom central controlado pelo driver e
não equivale ao pan do viewport ODIN.

Por fim, o enquadramento alterado em CONFIGURAR só era persistido após SALVAR;
o runtime principal do F3 podia continuar exibindo a configuração salva anterior
durante a edição, dando a impressão de que o zoom havia voltado.

### Correção aplicada

- o gesto agora possui fases explícitas:
  - `Button-1` inicia o drag e guarda o offset entre a mão e o centro;
  - `B1-Motion` atualiza somente centro/overlay/saída final;
  - `ButtonRelease-1` encerra o gesto;
- durante o drag, o canvas-fonte não é mais destruído e recriado a cada pixel;
- somente o overlay `zoom_viewport` é redesenhado enquanto a mão se move;
- o preview final é atualizado separadamente;
- o Zoom ODIN e o centro em edição são publicados em memória no runtime F3,
  sem salvar em disco, para a câmera principal acompanhar imediatamente;
- ao fechar CONFIGURAR sem salvar, o valor persistido continua sendo restaurado;
- em `1×`, o sistema não tenta mais simular um arraste inexistente e informa
  que é necessário usar **Zoom ODIN > 1×** para existir margem de enquadramento;
- nenhum novo timer, worker, scheduler ou autoridade foi criado.

### Próximo reteste esperado

    F3 → CONFIGURAR
    → colocar Zoom ODIN acima de 1×
    → pressionar dentro da janela azul
    → arrastar mantendo o botão pressionado
    → janela acompanha a mão sem piscar/resetar
    → SAÍDA FINAL acompanha o movimento
    → câmera principal do F3 acompanha o enquadramento provisório
    → soltar mouse
    → posição permanece
    → SALVAR fixa o enquadramento no Projeto Display

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 01/10/2026 — Segundo FAIL físico do drag: Zoom ODIN volta ao iniciar movimento

**Resultado físico:** FAIL.

### Esclarecimento do operador

O defeito é especificamente no **Zoom ODIN (software)**:

    ajustar Zoom ODIN acima de 1×
    → imagem aproxima corretamente
    → iniciar o arraste do enquadramento
    → o próprio zoom software volta/diminui
    → o operador perde o enquadramento ampliado

Não se trata do zoom digital da Logitech BRIO.

### Regra das duas tentativas

Como o comportamento continuou após a primeira correção do gesto, não foi feita
nova alteração no algoritmo sem reprodução objetiva.

### Diagnóstico adicionado

Foi criado um smoke com **Tkinter real via Xvfb** que:

1. abre a janela CONFIGURAR final;
2. seleciona um Projeto Display;
3. publica frame 1920x1080 real;
4. ajusta `software_zoom_var` explicitamente para 2.0×;
5. executa o mesmo caminho real:
   - `<Button-1>`;
   - `<B1-Motion>`;
   - `<ButtonRelease-1>`;
6. captura o valor do Zoom ODIN após cada fase;
7. exige que continue exatamente em 2.0×;
8. verifica que o centro X realmente se deslocou;
9. registra todos os valores publicados por
   `on_software_zoom_preview` e exige que nenhum callback publique 1.0×.

### Objetivo

Identificar de forma controlada se o reset ocorre:

- no evento Tk de press;
- no evento de motion;
- no release;
- no callback de preview;
- ou em algum refresh assíncrono da janela.

Nenhuma nova correção funcional foi aplicada nesta etapa.

**Estado:** DIAGNÓSTICO EM EXECUÇÃO — AGUARDANDO RESULTADO DO SMOKE REAL.

---

## 01/10/2026 — Diagnóstico do reset do Zoom ODIN durante drag

**Estado:** CAUSA NÃO REPRODUZIDA EM LINUX/XVFB; PROTEÇÃO DEFENSIVA IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Resultado do diagnóstico controlado

O smoke com Tkinter real foi ampliado para executar o gesto completo:

    Zoom ODIN = 2.0×
    → Button-1
    → B1-Motion
    → ButtonRelease-1

Primeiro contra a classe base e depois contra a composição final realmente usada
pelo botão CONFIGURAR, incluindo presença, ROI, tracking e contratos instalados.

Nos dois casos o Zoom ODIN permaneceu em 2.0× durante todo o gesto.

Isso indica que o reset físico observado no Windows não foi reproduzido no
backend Tk/Xvfb do CI e pode depender da ordem real de callbacks/variáveis do Tk
no ambiente Windows.

### Proteção aplicada

O drag passou a possuir um snapshot explícito do fator de zoom:

- no `Button-1`, o valor atual de `software_zoom` é capturado em
  `_zoom_drag_software_zoom`;
- enquanto `_zoom_drag_active=True`, `_zoom_values()` usa esse valor travado
  como autoridade do gesto;
- em cada `B1-Motion`, a `DoubleVar` é reafirmada com o zoom capturado;
- no `ButtonRelease-1`, o mesmo valor é reafirmado antes de encerrar o gesto;
- o latch é descartado somente após o release ou fechamento da janela.

Foi incluída uma regressão que simula explicitamente a condição suspeita:

    inicia drag em 2.0×
    → força software_zoom_var = 1.0 no meio do gesto
    → executa motion
    → Zoom ODIN deve voltar imediatamente para 2.0×
    → release mantém 2.0×

Esse contrato garante que um refresh/evento de backend não possa alterar o fator
de zoom enquanto o operador estiver arrastando o enquadramento.

Nenhum novo timer, worker, scheduler ou persistência foi introduzido.

### Próximo reteste esperado

    F3 → CONFIGURAR
    → Zoom ODIN = 2× ou 3×
    → pressionar dentro da janela de enquadramento
    → arrastar mantendo o botão pressionado
    → o fator exibido do Zoom ODIN deve permanecer exatamente no valor escolhido
    → saída final deve apenas mudar de posição, sem perder aproximação
    → soltar
    → zoom continua no mesmo fator

**Validação física:** pendente.

---

## 01/10/2026 — Redesign do zoom: mapa 1× + quadro azul único

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Solicitação

A visualização anterior estava confusa porque:

- havia duas imagens grandes;
- a saída final podia aparecer rotacionada;
- não estava claro qual área correspondia ao zoom usado pelo F3;
- ao usar zoom digital da câmera, o operador também queria deslocar a região.

### Implementação

A seção de zoom passou a usar:

**MAPA DA CÂMERA • ARRASTE O QUADRO AZUL**

- mostra a visão completa de referência em 1×;
- sempre usa orientação natural da câmera;
- não aplica rotação visual do F3;
- mantém um quadro azul sobre a área efetivamente usada;
- o tamanho do quadro reflete a composição do zoom da câmera com o Zoom ODIN.

Exemplo:

    câmera 1× + ODIN 2× = quadro 2×
    câmera 2× + ODIN 1× = quadro 2×
    câmera 2× + ODIN 2× = quadro 4×

A visualização secundária foi reduzida para:

**RECORTE ATUAL DO F3 • SEM ROTAÇÃO**

Ela serve apenas para confirmar o conteúdo atual selecionado.

### Movimento do quadro

- com zoom físico da BRIO acima de 1×:
  - arrastar o quadro atualiza `camera_zoom_center.x/y`;
  - o centro é convertido para `CAP_PROP_PAN` e `CAP_PROP_TILT`;
  - Zoom ODIN é recentrado para evitar duas autoridades de deslocamento;
- sem zoom físico:
  - o quadro move `software_zoom_center.x/y`.

O centro físico é salvo por Projeto Display.

### Referência 1×

Antes de aplicar zoom físico, o ODIN preserva em memória uma cópia do frame 1×.
Essa imagem funciona como mapa de navegação enquanto a BRIO passa a entregar
frames já ampliados.

Ela não entra na análise, decisão, tracking, presença ou OK/NG.

### Regressões validadas automaticamente

- composição câmera × ODIN gera o viewport efetivo correto;
- pan/tilt seguem o centro do quadro azul;
- drag com zoom físico altera o centro da câmera;
- drag com Zoom ODIN continua funcionando;
- zoom software não é perdido durante drag;
- centro físico persiste por Projeto Display;
- CONFIGURAR abre com Tkinter real;
- nenhum timer adicional foi criado;
- rearme F3 e controles manuais da câmera permanecem verdes.

### Reteste físico esperado

    F3 → CONFIGURAR
    → observar o MAPA DA CÂMERA em orientação natural
    → ativar zoom digital da câmera em 2×
    → quadro azul deve reduzir para representar a área 2×
    → arrastar quadro azul para esquerda/direita/cima/baixo
    → a BRIO deve mover digitalmente o enquadramento
    → RECORTE ATUAL deve acompanhar sem rotação/inversão
    → testar Zoom ODIN adicional
    → confirmar que o quadro encolhe conforme o zoom combinado
    → Salvar
    → fechar/reabrir F3
    → confirmar persistência do mesmo centro/enquadramento

**Validação física:** pendente.

