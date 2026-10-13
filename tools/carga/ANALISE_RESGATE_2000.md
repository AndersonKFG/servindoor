# Reservas e confirmação de resgate com 2.000 visitantes

Revisão de 12/10/2026, sobre o código em `6ce3b31` e os resultados enviados da VPS.
Este documento propõe a correção; não comprova capacidade de 2.000 visitantes.

## 1. O que o último teste demonstrou

Execução: `20261012T211419_6044`.

| Medida | Resultado | Interpretação |
| --- | --- | --- |
| Visitantes planejados | 2.000 | A execução não chegou ao alvo. |
| VUs máximos observados | 500 | Patamar em que a execução foi interrompida. |
| Reservas aceitas acumuladas | 585 | Inclui novas reservas depois de desistências; não mede simultaneidade. |
| Tempo de criação de reserva, p95 | 8.076 ms | Acima da meta atual de 3.000 ms. |
| Falhas técnicas de criação | 1,349% | Acima do limite de 1% que aborta a execução. |
| Recusas por vagas em preenchimento/esgotadas | 0 / 0 | A reprovação não foi por esgotamento do lote. |
| Continuidade / token no F5 / prazo / desistência | 100% nas verificações registradas | Não demonstra defeito dessas operações nessa execução. |
| Falhas da home / SSE | 0 / 0 | A home e a conexão de atualização funcionaram nas amostras. |

Os critérios estão em `tools/carga/carga.js:59`. O p95 de reserva acima de
3 segundos reprova a meta, mas não aborta sozinho. O critério de falhas técnicas
tem `abortOnFail`; o critério global de checks passou nesta execução.

O primeiro POST de criação não registra os detalhes da falha técnica
(`carga.js:202`). Por isso, o material enviado não distingue timeout, HTTP 429,
erro 5xx ou resposta inválida nesses 1,349%. Os status zero de F5 e desistência
no instante do aborto também sofrem o efeito de `gracefulStop: '0s'`; não devem
ser interpretados automaticamente como falhas anteriores à interrupção.

Não há limite de 500 reservas. A regra em `app/routers/resgate.py:798` é:

```text
vagas livres = quantidade total - resgates contabilizados - reservas ativas
```

Com 1.500 vagas, 2.000 visitantes podem tentar. No máximo 1.500 vagas podem estar
ocupadas entre reservas e resgates contabilizados. Os demais devem receber uma
recusa de negócio rápida e compreensível. Essas recusas não são falhas técnicas.

## 2. Gargalos e falhas confirmados no código

### 2.1. Uma seção longa serializa as novas reservas do lote

Em `resgate.py:718`, a criação usa `FOR UPDATE` na mesma linha do lote e mantém
esse bloqueio durante buscas de dispositivo, contagem de reservas, savepoint,
consultas/inserção/limpeza do limitador e inserção/commit da reserva.

Os logs anteriores da VPS mostraram espera por esse bloqueio. A fila local por
worker evita que todos os pedidos aguardem segurando conexões, mas não encurta
a seção nem aumenta, por si só, a velocidade de criação.

A busca por fingerprint também não tem índice específico
(`app/models/all_models.py:228`). O índice de capacidade existente inclui
`utilizada`, enquanto a consulta atual usa `status`.

### 2.2. Cada alteração produz trabalho para todos os visitantes

`app/core/events.py:51` distribui cada criação, desistência e conclusão a todas
as conexões SSE. O barramento PostgreSQL faz os outros workers distribuírem o
evento às suas conexões. Cada mudança também invalida o cache público inteiro.

Assim, alterações frequentes e muitos visitantes multiplicam entregas e
reconstruções do cache. A conexão SSE aberta não faz consulta ao banco a cada
evento; o custo está na distribuição e nos snapshots de conexões/reconexões.

O custo exato de CPU desse mecanismo ainda não foi medido. O teste aprovado de
4.000 visitantes na home não exercitou o mesmo volume de alterações de reservas.

### 2.3. A confirmação HTTP depende da publicação após gravar

Depois do commit, `resgate.py:878` ainda consulta o estado do lote e aguarda o
broadcast. Isso pode atrasar a entrega do token mesmo com a reserva já salva.

No formulário, `resgate.py:1190` abre uma nova leitura e publica sem devolver
antes a conexão; o publicador precisa de outra conexão. Esse caminho reintroduz
pressão sobre o pool que a correção de criação já havia evitado.

### 2.4. O formulário mantém o bloqueio durante a API externa e a foto

`resgate.py:1072` bloqueia o lote; a consulta externa em `:1094` pode esperar até
8 segundos, e a foto é escrita de forma síncrona em `:1112`. O commit vem em
`:1189`. Durante esse intervalo, outras confirmações e novas reservas do lote
podem ficar esperando.

O teste atual não envia formulário, foto nem e-mail, portanto não validou esse
caminho.

### 2.5. A conclusão não protege suficientemente a transição da reserva

A reserva é lida sem bloqueio em `resgate.py:980` e seu prazo é conferido antes
da espera pelo lote. Não há releitura protegida depois dessa espera. Desistência,
expiração ou outro envio podem alterar a reserva nesse intervalo.

Existem proteções úteis no banco: CPF único, ingresso ativo único por usuário e
solicitação pendente/aprovada única por usuário. Elas não substituem a garantia
de que um token de reserva só pode concluir uma vez. Dois envios do mesmo token
com CPFs diferentes, por exemplo, não são protegidos pela unicidade do CPF.

### 2.6. Falta recuperar um resultado já confirmado

Em `resgate.py:993`, repetir um token concluído devolve erro. Se o commit ocorrer
e a resposta HTTP se perder, o cadastro pode estar salvo, mas o navegador não
consegue recuperar a confirmação pela repetição.

O e-mail pendente também é iniciado em uma tarefa em memória depois do commit
(`resgate.py:1215`). Um reinício antes de essa tarefa inserir na fila pode perder
a notificação. A fila já aceita uma sessão do chamador em
`app/services/email_queue.py:16`, permitindo persistência junto do cadastro.

## 3. Correção proposta como um conjunto

### A. Encurtar a criação preservando a capacidade no PostgreSQL

1. Recuperar reservas existentes por buscas indexadas, preservando token e prazo.
2. Tirar o limitador e sua limpeza da seção que bloqueia o lote. Preservar sua
   atomicidade por chave, em uma operação curta, sem manter conexão durante espera
   na fila de criação. Executar limpeza periódica fora de pedidos de reserva.
3. Dentro do bloqueio do lote, deixar somente revalidação de disponibilidade,
   exclusividade do dispositivo, contagem indexada, inserção e commit.
4. Criar índices parciais para capacidade `(lote_id, expira_em)` e buscas de
   fingerprint/device, restritos a reservas ativas. Aplicar exclusividade ativa
   no banco, com tratamento explícito de reservas expiradas e dados existentes.
5. Retornar o token depois do commit sem esperar consultas/publicação pública.

Manter uma única fonte de capacidade, baseada nas reservas e resgates existentes.
Um contador novo isolado exigiria adaptar todas as saídas, expirações,
cancelamentos, restaurações e alterações administrativas; não é um atalho seguro.

### B. Atualizar visitantes sem transmitir cada reserva para todos

1. Usar `RESERVA_ATUALIZADA` para o interessado e `LOTE_ATUALIZADO` para o estado
   público. Os consumidores atuais já escutam ambos.
2. Agrupar atualizações públicas por lote numa janela de 250–500 ms, enviando o
   estado mais recente. Alterações administrativas continuam imediatas.
3. Usar tarefas duráveis/supervisionadas, com processamento limitado, para
   publicação; não criar uma tarefa independente sem controle por pedido.
4. Reconstruir o cache público uma vez por lote/worker de cada vez; compartilhar
   esse resultado entre pedidos simultâneos. Separar dados públicos dos dados
   individuais da reserva.
5. Reconexão sempre reconcilia o estado pelo banco. Corrigir deduplicação entre
   workers e sinalizar ressincronização quando o histórico/fila não cobrir o gap.
6. Não usar fingerprint como prova de posse nem transmitir tokens publicamente.
   A recuperação individual deve respeitar a identidade autorizada da reserva.

A janela de atualização afeta somente o que a tela mostra. A aceitação de vaga
continua sendo decidida atomicamente no banco, nunca pelo cache.

### C. Tornar o formulário seguro sob concorrência e repetição

1. Validar campos e preparar/gravar a foto antes da transação que bloqueia o
   lote. Usar escrita fora do loop assíncrono, arquivo exclusivo e finalização
   atômica; limpar arquivos sem vínculo em falhas. Confirmar só referências a
   fotos já finalizadas. Corrigir o limite de corpo para a rota efetiva.
2. Retirar a API externa da seção de bloqueio. Como a indisponibilidade já segue
   para análise manual, a opção preferida é persistir o cadastro e um trabalho
   durável de consulta, com concorrência limitada e acompanhamento de resultado.
   A tela/equipe devem distinguir consulta pendente de consulta não confirmada.
3. Adotar uma ordem única de bloqueios em criação/conclusão/desistência/expiração.
   Na transação final, reler e proteger a reserva, conferir novamente prazo,
   estado, lote e elegibilidade, e concluir exatamente uma vez.
   Definir explicitamente o instante de admissão do envio: se um envio aceito
   dentro dos cinco minutos puder terminar depois, registrar essa admissão
   atomicamente. Um estado `processando` deve continuar ocupando a vaga, ter
   trabalho durável e permitir recuperação após reinício; não pode liberar
   capacidade silenciosamente enquanto a confirmação ainda estiver em andamento.
4. Persistir um vínculo único entre reserva e solicitação, permitindo recuperar
   o resultado autorizado. Repetir o mesmo envio, com identidade autorizada e
   mesmo CPF, retorna a mesma solicitação e confirmação; não consome outra vaga,
   não duplica cadastro nem e-mail. Outro CPF deve receber conflito.
5. Gravar cadastro, solicitação, conclusão da reserva, contador do lote e entrada
   da fila de e-mail na mesma transação. Falha de enqueue precisa impedir o
   sucesso silencioso; o helper atual pode retornar `False`.
6. SMTP e publicação SSE ficam fora da transação e não transformam um cadastro
   confirmado em erro HTTP. O navegador pode recuperar o resultado com o mesmo
   token depois de uma falha de rede.

O resultado atual do formulário é uma solicitação em análise. A emissão do
ingresso após aprovação continua sendo uma etapa posterior.

## 4. Como validar a solução para 2.000

Antes de outra rodada manual longa na VPS:

1. Exercitar localmente, em banco isolado, disputas pelo mesmo token e CPF,
   desistência/expiração durante envio, repetição depois do commit e falha de
   publicação/e-mail. Conferir foto, solicitação e contadores persistidos.
2. Registrar no primeiro POST falho do k6: etapa, status HTTP, código público da
   resposta, erro de transporte e duração. Não registrar token, CPF ou foto.
3. Medir tempo na fila local, espera e duração do bloqueio, espera por conexão,
   atraso do loop assíncrono, publicações públicas e entregas SSE. Separar uso
   de CPU do gerador quando ele rodar na própria VPS.
4. Rodar cenário com alvo de 2.000, lote de 1.500 e confirmação de formulário,
   incluindo os CPFs compartilhados combinados. A tentativa barrada por resgate
   já concluído encerra seu ciclo e libera eventual reserva própria.
5. Incluir uma chegada concentrada de 2.000 tentativas, além da subida gradual;
   documentar a janela de chegada para não confundir simultaneidade com pedidos
   espaçados. Controlar foto, destino de e-mail e consulta externa de teste.
6. Comparar o resultado do k6 com o banco ao final. Só o HTTP não comprova
   gravação correta nem ausência de duplicidade.

Critérios de aceite:

- No máximo 1.500 vagas ocupadas entre reservas válidas e resgates contabilizados.
- Um resultado por reserva e respeito às restrições de participante.
- Recusas por capacidade/CPF já atendido são resultados de negócio, não falhas.
- Nenhum sucesso HTTP sem cadastro/foto correspondente; retries recuperam
  resultados já confirmados sem duplicá-los.
- E-mail confirmado como enfileirado no mesmo commit; entrega SMTP acompanhada
  separadamente.
- Meta de criação p95 abaixo de 3 segundos e falhas técnicas abaixo de 1%, com
  cada falha identificada. Qualquer violação de integridade reprova o teste,
  mesmo com boas médias de desempenho.

Se o bloqueio curto ainda limitar a chegada exigida após essas mudanças medidas,
a evolução estrutural é uma linha por vaga, adquirida com `FOR UPDATE SKIP
LOCKED`. Isso distribui as disputas entre vagas, mas exige migrar todos os fluxos
de capacidade conjuntamente. Não deve ser aplicado somente à criação de reserva.
