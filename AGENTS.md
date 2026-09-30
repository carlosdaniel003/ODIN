# AGENTS.md — Protocolo obrigatório de desenvolvimento do ODIN

Este arquivo define as regras de trabalho para qualquer agente de IA que analise, planeje ou modifique este repositório.

## 1. Leitura obrigatória antes de qualquer trabalho

Antes de analisar, planejar ou alterar código:

1. Leia este arquivo integralmente.
2. Leia `README.md`.
3. Leia `docs/ARCHITECTURE.md`.
4. Leia `docs/ENGINEERING_RULES.md`.
5. Leia `docs/PERFORMANCE.md`.
6. Leia `docs/AI_WORKFLOW.md`.
7. Leia `docs/DECISIONS.md`.
8. Leia documentação específica do subsistema afetado, quando existir.
9. Para qualquer trabalho no Display F3, leia também `docs/F3_PHYSICAL_VALIDATION_LOG.md`.
10. Para qualquer trabalho no **Rastreamento Automático do Display F3**, leia também `docs/F3_AUTOMATIC_TRACKING_LOG.md` integralmente antes de analisar ou modificar o runtime.
11. Inspecione a branch e o código atuais. Não assuma que o estado lembrado de uma conversa anterior ainda é o estado do repositório.

Esses documentos são instruções obrigatórias do projeto.

### Precedência em caso de conflito

1. instrução explícita mais recente do usuário;
2. `AGENTS.md`;
3. decisões aceitas em `docs/DECISIONS.md`;
4. `docs/ARCHITECTURE.md`, `docs/ENGINEERING_RULES.md`, `docs/PERFORMANCE.md` e `docs/AI_WORKFLOW.md`;
5. documentação específica de subsistema;
6. `README.md`;
7. documentos marcados como históricos ou legados.

Nunca use comentário antigo, nome de classe legado ou implementação histórica para contrariar uma decisão arquitetural aceita.

## 2. O que é o ODIN

O ODIN é um sistema desktop de inspeção industrial por visão computacional, desenvolvido principalmente em Python, OpenCV e Tkinter.

O produto possui três áreas principais:

- engenharia e parametrização;
- Produção F2;
- Produção Display F3.

F2 e F3 podem compartilhar infraestrutura e primitivas de visão, mas devem manter estado operacional, regras de decisão, ciclo produtivo e persistência de domínio isolados.

## 3. Plataformas suportadas

As plataformas de produto suportadas são:

- Windows;
- Linux desktop.

Raspberry Pi não é mais plataforma alvo.

Nomes como `main_rpi.py`, `RaspberryPi3ProductionApp`, mixins Raspberry e código GPIO podem continuar temporariamente por compatibilidade histórica durante a migração, mas:

- não devem orientar novas decisões arquiteturais;
- não devem receber novas dependências específicas de Raspberry, salvo pedido explícito;
- devem ser gradualmente substituídos pela composição desktop definida na arquitetura;
- não devem ser removidos em massa sem prova de que não possuem consumidores.

## 4. Restrições do ambiente de desenvolvimento

O desenvolvimento deve continuar viável em notebook corporativo com restrições administrativas.

Por padrão:

- não exigir Docker;
- não exigir banco de dados local como serviço;
- não exigir software que peça privilégios de administrador;
- não introduzir serviço residente do sistema operacional;
- preferir dependências Python existentes, ferramentas portáteis e execução local;
- qualquer nova dependência operacional pesada precisa de justificativa e aprovação explícita do usuário.

## 5. Forma obrigatória de trabalhar

O projeto é desenvolvido por etapas.

Quando existir um plano em fases:

- trabalhe somente na etapa atual;
- não avance automaticamente para a próxima;
- conclua implementação, testes e revisão da etapa atual;
- apresente o resultado;
- aguarde o usuário confirmar com **OK** antes de iniciar a etapa seguinte.

Se o usuário pedir apenas análise, visualização, diagnóstico ou planejamento:

**não altere nenhum arquivo.**

### Registro obrigatório de validação física do F3

Sempre que o usuário relatar um teste físico do Display F3, registre o resultado em
`docs/F3_PHYSICAL_VALIDATION_LOG.md`, inclusive quando o resultado for negativo.

O registro deve preservar:

- data;
- cenário/CHECK;
- PASS, FAIL ou PENDENTE DE RETESTE;
- sintoma observado;
- evidência objetiva disponível no DEBUG;
- causa identificada, quando houver;
- alteração aplicada;
- próximo reteste esperado.

Não apague falhas antigas depois que uma correção funcionar. O histórico deve
mostrar a sequência real de tentativa, evidência, correção e validação.

Quando o teste, tentativa ou correção envolver **rastreamento automático do F3**,
atualize também `docs/F3_AUTOMATIC_TRACKING_LOG.md` com o resultado e a lição,
para preservar inclusive caminhos abandonados e impedir repetição de estratégias
que já falharam.

## 6. Princípios arquiteturais obrigatórios

Priorize, nesta ordem:

1. correção funcional;
2. segurança operacional;
3. responsividade e desempenho;
4. baixo acoplamento;
5. alta coesão;
6. clareza de responsabilidade;
7. testabilidade;
8. legibilidade;
9. manutenção;
10. escalabilidade.

Escalabilidade neste projeto significa permitir crescimento sem multiplicar autoridades, loops, threads, wrappers ou dependências cruzadas.

### Modularização saudável

Modularidade não significa maximizar o número de arquivos.

Um módulo novo deve existir porque representa uma responsabilidade estável e coesa.

Evite:

- um arquivo por pequena função sem benefício arquitetural;
- módulos cujo único propósito seja sobrescrever outro módulo;
- cadeias de `fix -> fix_v2 -> final_fix -> authority -> compat`;
- heranças e mixins adicionados apenas para injetar mais uma correção;
- dependências circulares;
- estado global compartilhado sem proprietário claro.

Para novas arquiteturas, prefira composição de serviços com contratos explícitos a cadeias crescentes de herança ou monkey patching.

## 7. Regra de proprietário único

Toda responsabilidade crítica de runtime deve possuir um proprietário canônico.

Exemplos:

| Responsabilidade | Regra |
| --- | --- |
| captura de câmera | um serviço proprietário |
| frame atual | um buffer/estado proprietário |
| scheduler periódico do F3 | um coordenador proprietário |
| trabalho pesado de visão F3 | um executor proprietário |
| presença física | uma autoridade canônica |
| energia do display | uma autoridade canônica |
| sequência de CHECKS | uma máquina de estados |
| decisão OK/NG | uma autoridade de decisão |
| persistência | repositório responsável |
| UI | apresenta estado; não cria segunda regra de negócio |
| debug | observa; não altera resultado produtivo |

Se uma responsabilidade já possui proprietário, corrija ou evolua esse proprietário. Não crie uma segunda autoridade paralela.

## 8. Antes de modificar uma funcionalidade existente

Mapeie obrigatoriamente:

- definição atual;
- chamadores;
- subclasses e mixins;
- funções `instalar_*`;
- wrappers e monkey patches;
- timers `after()`;
- threads/executores;
- estado compartilhado;
- persistência;
- testes relacionados.

Responda internamente às perguntas:

- Qual é o caminho real de execução?
- Quem é a autoridade atual?
- Existe solução histórica concorrente?
- Qual é a causa provável?
- Qual comportamento não pode mudar?
- Como a alteração será validada?

Não implemente uma nova solução antes de entender as soluções já existentes.

## 9. Correções e novas implementações

Uma correção deve atacar a causa, não apenas esconder o sintoma.

É proibido como estratégia padrão:

- criar outro `*_fix.py`;
- criar `*_v2.py` ou `*_final.py` porque a versão anterior falhou;
- adicionar outro debounce sem entender os existentes;
- adicionar outro `after()` periódico para aliviar um `after()` anterior;
- criar thread arbitrária em cada funcionalidade;
- manter duas implementações ativas "por segurança";
- deixar código substituído participando silenciosamente do runtime.

Uma solução experimental pode existir temporariamente, mas precisa de estratégia explícita de saída: consolidar no módulo canônico, desligar o caminho anterior e remover resíduos após validação.

## 10. Regra das duas tentativas

Se duas tentativas para o mesmo defeito não resolverem a causa:

**pare de modificar o algoritmo.**

A próxima etapa deve ser diagnóstico/instrumentação:

- medir duração;
- contar chamadas;
- identificar thread;
- registrar frame IDs;
- identificar callbacks ativos;
- verificar transições de estado;
- verificar qual autoridade realmente decidiu;
- reproduzir o problema de forma controlada.

Somente depois disso proponha a próxima correção.

## 11. Performance é requisito funcional

O ODIN é software de tempo real interativo.

Regras detalhadas estão em `docs/PERFORMANCE.md`, mas são obrigatórias desde já:

- Tkinter não deve esperar visão computacional pesada;
- não criar busy loops;
- não criar filas ilimitadas de frames;
- usar política latest-frame-wins em pipelines ao vivo;
- manter concorrência pesada limitada;
- evitar I/O de disco e decodificação repetida no hot path;
- evitar render pesado diretamente em eventos de resize;
- todo worker deve possuir lifecycle de início/parada;
- nenhum thread de background deve manipular widgets Tk.

Uma mudança de performance precisa ser comparada com um baseline mensurável sempre que possível.

## 12. Testes e regressões

Toda alteração funcional deve possuir validação proporcional ao risco.

Antes de considerar uma etapa concluída:

- execute testes específicos do componente;
- execute testes de integração relevantes;
- verifique isolamento F2/F3 quando aplicável;
- verifique lifecycle de câmera/timers/threads quando aplicável;
- revise o diff procurando código morto, duplicação e caminhos substituídos.

Não modifique testes apenas para fazer uma implementação incorreta passar.

Quando o comportamento esperado mudar intencionalmente, documente a decisão e altere teste + implementação de forma coerente.

## 13. Código residual

Após cada correção ou refatoração concluída, faça uma auditoria de resíduos no escopo tocado:

- imports sem uso;
- métodos não chamados;
- wrappers substituídos;
- aliases temporários;
- flags que perderam função;
- timers redundantes;
- estados duplicados;
- caches sem invalidação;
- arquivos de experimento;
- comentários que descrevem comportamento antigo.

Não remova código apenas por parecer antigo. Confirme consumidores e testes primeiro.

## 14. Trabalho concorrente entre agentes

Pode haver mais de um agente trabalhando no projeto.

Antes de escrever:

- confirme a branch atual e o HEAD;
- releia arquivos que serão modificados;
- preserve commits alheios;
- não use force push;
- não reverta mudanças não relacionadas;
- mantenha commits pequenos e semanticamente focados.

Se a branch avançar durante uma alteração, reaplique a mudança sobre o novo HEAD em vez de sobrescrever o trabalho concorrente.

## 15. Definition of Done

Uma tarefa só está concluída quando:

- o requisito da etapa atual foi atendido;
- a causa foi tratada no proprietário correto;
- os testes relevantes passam;
- não foi criada autoridade concorrente desnecessária;
- não foi criado loop, timer, worker ou fila sem lifecycle claro;
- o desempenho não foi degradado sem justificativa;
- resíduos introduzidos ou substituídos no escopo foram tratados;
- documentação/decisões foram atualizadas quando a arquitetura mudou;
- nenhuma etapa seguinte foi iniciada sem o **OK** do usuário.

O objetivo não é adicionar código até o sintoma desaparecer.

O objetivo é deixar uma única solução clara, mensurável e sustentável.


## 16. Invariantes de regressão do Display F3 — D-038 e D-039

As seguintes regras são obrigatórias em qualquer alteração futura do Display F3:

- a conformidade estrita de D-031 continua sendo a autoridade semântica:
  uma máscara configurada divergente continua bloqueando OK;
- excluir a foto do CHECK atual não pode transformar um segmento fisicamente
  ACESO e corretamente configurado em falso APAGADO apenas por diferença de
  brilho/cor entre funções;
- a única exceção permitida à exclusão da foto atual é uma referência **ON**
  local da **mesma máscara física**, validada contra referências OFF externas
  dessa mesma máscara por separação óptica mínima já definida pelo F3;
- referência OFF do próprio CHECK nunca pode autoaprovar esse CHECK;
- a exceção ON validada nunca entra no pool global nem pode substituir
  `mask_states`;
- qualquer alteração nessa política exige dois testes opostos:
  1. CHECK correto/segmento realmente ON continua aprovável;
  2. segmento esperado ON, mas realmente apagado, continua incapaz de ensinar o
     defeito como correto;
- resultado terminal (APROVADA, NG ou SEGREGADA) e rearme físico são um único
  contrato visual: a tela não pode voltar a mostrar H1 como ativo enquanto a
  placa anterior ainda aguarda retirada;
- SEGREGAR por botão, tecla `1` e NumPad `1` deve chamar a mesma ação oficial;
- a primeira SEGREGAÇÃO válida contabiliza exatamente uma vez; enquanto aguarda
  suporte vazio/nova placa, novas tentativas permanecem bloqueadas para impedir
  dupla contabilização;
- o botão SEGREGAR deve refletir esse bloqueio visualmente e só voltar a ficar
  habilitado quando o rearme físico confirmar a nova placa;
- nenhuma correção desses contratos pode criar novo timer, worker, scheduler ou
  autoridade paralela.
