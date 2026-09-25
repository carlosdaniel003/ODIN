# Fluxo de Desenvolvimento com IA

## 1. Objetivo

O ODIN é desenvolvido com forte participação de agentes de IA. Este documento reduz perda de contexto, repetição de tentativas e acúmulo de código residual.

## 2. Regra de ouro

**Entender primeiro, modificar depois.**

Uma nova sessão de IA não deve assumir que conhece o runtime porque reconhece nomes de arquivos ou lembra uma conversa anterior.

O repositório atual é a fonte de verdade do código.

## 3. Início obrigatório de uma tarefa

Antes de qualquer análise técnica:

1. leia todos os `.md` obrigatórios;
2. confirme repository/branch/HEAD;
3. verifique mudanças recentes relevantes;
4. leia os módulos canônicos do caminho afetado;
5. leia testes relacionados;
6. pesquise wrappers, mixins e `instalar_*`;
7. só então produza diagnóstico ou plano.

## 4. Quando o pedido for apenas análise

Se o usuário disser:

- somente visualize;
- somente analise;
- não altere;
- faça diagnóstico;
- faça plano;

não realize nenhuma escrita no repositório.

Não crie "instrumentação temporária" sem autorização, pois isso também é alteração.

## 5. Trabalho por etapas

Quando existir plano em fases:

~~~text
ETAPA ATUAL
 ↓
análise
 ↓
implementação
 ↓
testes
 ↓
revisão
 ↓
relatório
 ↓
aguardar OK
~~~

Nunca começar a próxima etapa automaticamente.

O **OK** do usuário é o gate de progressão.

## 6. Registro mental mínimo antes de editar

Antes de escrever, a IA deve conseguir resumir:

~~~text
PROBLEMA:
CAUSA/HIPÓTESE:
CAMINHO REAL:
AUTORIDADE ATUAL:
ARQUIVOS QUE PRECISAM MUDAR:
ARQUIVOS QUE NÃO DEVEM MUDAR:
TESTES:
CRITÉRIO DE ACEITAÇÃO:
RISCO PRINCIPAL:
~~~

Se isso não estiver claro, continuar investigando.

## 7. Evitar perda de contexto

Não tente carregar todo o ODIN mentalmente em toda tarefa.

Use navegação dirigida:

~~~text
entrada do evento
 ↓
coordenador/controller
 ↓
serviço responsável
 ↓
dependências diretas
 ↓
testes
~~~

Consulte `docs/DECISIONS.md` para não redescobrir decisões arquiteturais já tomadas.

## 8. Pesquisa obrigatória antes de criar nova solução

Antes de criar método ou módulo:

- pesquise o nome/conceito no repositório;
- procure implementações equivalentes;
- procure código substituído;
- procure testes;
- procure comentários que indiquem autoridade final;
- confirme se o comportamento já é modificado em runtime.

A IA não deve resolver um problema conhecido criando uma implementação paralela porque não encontrou a existente de primeira.

## 9. Falha de tentativa

Depois de uma tentativa que não resolveu:

1. registre o que foi testado;
2. identifique o que a evidência descartou;
3. não duplique a mesma estratégia com pequenas variações.

Depois de duas tentativas sem causa confirmada, aplique a regra das duas tentativas de `docs/ENGINEERING_RULES.md`.

## 10. Mudança mínima, solução completa

"Mudança mínima" significa menor alteração coerente na autoridade correta.

Não significa deixar código antigo ativo por medo de removê-lo.

Uma solução completa pode incluir:

- alterar o proprietário;
- adaptar consumidor;
- remover wrapper substituído;
- atualizar testes;
- atualizar documentação.

Tudo isso ainda pode ser uma única mudança focada.

## 11. Revisão após implementar

Antes de apresentar a etapa como concluída:

- execute testes;
- revise o diff;
- procure import residual;
- procure método antigo ainda chamado;
- procure timer/thread extra;
- procure estado duplicado;
- procure tratamento de exceção silencioso novo;
- confirme que nenhum subsistema fora do escopo foi alterado inadvertidamente.

## 12. Relatório ao usuário

Ao concluir uma etapa, informe objetivamente:

- causa encontrada;
- arquivos alterados;
- solução adotada;
- o que foi removido/substituído;
- testes executados e resultado;
- impacto de performance quando medido;
- riscos ou pendências da própria etapa.

Não avance para a próxima etapa.

## 13. Trabalho concorrente com outro agente

Antes de qualquer escrita:

- releia o HEAD;
- releia os arquivos que serão modificados;
- não sobrescreva commits de outro agente;
- não use force push;
- não "restaure" arquivo inteiro para uma versão lembrada;
- se o HEAD avançou, reaplique a sua alteração sobre o novo estado.

Quando dois agentes trabalham em áreas diferentes, preservar essa separação.

## 14. Commits

Commits de IA devem ser:

- pequenos;
- descritivos;
- focados;
- reversíveis.

A mensagem deve explicar intenção, não apenas "update".

## 15. Atualização de documentação

Atualize `docs/DECISIONS.md` quando surgir decisão arquitetural duradoura.

Atualize arquitetura quando:

- mudar proprietário de responsabilidade;
- mudar plataforma;
- mudar fluxo entre camadas;
- introduzir/remover serviço canônico.

Não transforme documentação em diário de cada bug.

## 16. Anti-loop de desenvolvimento

Sinais de que a IA entrou em loop improdutivo:

- terceiro arquivo de fix para o mesmo comportamento;
- troca repetida de thresholds sem nova evidência;
- vários debounces concorrentes;
- wrapper para corrigir wrapper;
- teste alterado várias vezes para acompanhar implementação instável;
- comportamento muda em outra tela a cada correção;
- o agente já não consegue explicar qual método é executado por último.

Ao detectar esses sinais, interrompa implementação e volte ao diagnóstico do caminho real.
