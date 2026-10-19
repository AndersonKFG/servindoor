# Ocupação permanente após cancelamentos e extravios

O resgate confirmado consome a cota do lote definitivamente. Cancelar ou
extraviar invalida o ingresso e mantém o bloqueio do CPF, sem diminuir
`lotes.quantidade_resgatada`. Ocupação, vagas disponíveis e esgotamento usam
esse contador. As prioridades atuais de prazo e pausa continuam valendo:
um lote com prazo vencido aparece como Encerrado, mesmo que esteja cheio.

## Preparação da correção histórica

Publicar primeiro a correção dos dois fluxos em **todos** os processos da
aplicação e retirar os processos antigos. A ferramenta é executada
manualmente no ambiente que já possui a configuração de banco da aplicação;
não há migração automática nem conexão com produção durante os testes.

Antes da aplicação, manter um backup/snapshot restaurável do banco e abrir
uma janela curta de manutenção para resgates, validações, cancelamentos e
importações/restaurações de lotes. Se houver reservas temporárias em andamento,
aguardar sua conclusão ou expiração antes de gerar o plano definitivo.
Não editar diretamente o plano para resolver divergências.

## Gerar e revisar o diagnóstico (somente leitura)

Na raiz do projeto, usando o mesmo Python e as variáveis de ambiente do backend:

```bash
python tools/reconciliar_ocupacao_lotes.py --lote-id 2 --saida plano-lote-2.json
```

O ID 2 corresponde ao lote mostrado na captura; conferir o ID no ambiente antes
de executar. Para mais de um lote, repetir `--lote-id`. Não há seleção implícita
de todos os lotes. O destino deve ser um arquivo novo.

O diagnóstico usa uma transação PostgreSQL `REPEATABLE READ, READ ONLY`.
O JSON contém apenas contagens, IDs dos lotes e hashes das evidências/origem;
não expõe CPFs, nomes, e-mails ou credenciais. Conferir para cada lote:

- `contador_atual`, `ocupacao_reconstruida`, `contador_proposto` e `acrescimo`;
- `ingressos_cancelados_ou_extraviados`, `bloqueios` e `avisos`;
- se uma ocupação superior à capacidade representa resgates extras que já
  ocorreram. O valor real não será truncado na capacidade do lote.

### Como o histórico é reconstruído

Cada solicitação de validação representa um resgate já confirmado, inclusive
pendentes e rejeitadas: a confirmação consome a cota antes da emissão do
ingresso, e a rejeição também não a libera. Solicitações legadas sem reserva
vinculada continuam contando. O ingresso do mesmo usuário no mesmo lote não
é somado novamente se a solicitação estiver aprovada e a emissão não for anterior
à solicitação; caso contrário, o vínculo fica bloqueado para revisão.
Ingressos legados sem solicitação contam individualmente,
incluindo os cancelados/extraviados.

A aplicação fica bloqueada quando há múltiplas solicitações ou ingressos do
mesmo usuário no lote, vínculos de reserva inconsistentes, reservas concluídas
sem solicitação, status de solicitação desconhecido, contadores negativos, histórico menor que o contador atual
ou diferença maior que o número de ingressos invalidados. Esses casos exigem
investigação dos registros e backups; a ferramenta não tenta adivinhar vínculos
nem corrigir outras inconsistências. Para aplicar apenas lotes sem bloqueios,
gerar um plano separado com os IDs correspondentes.

## Aplicar exatamente o plano revisado

```bash
python tools/reconciliar_ocupacao_lotes.py --aplicar plano-lote-2.json --saida recibo-lote-2.json
```

Antes dos UPDATEs, a ferramenta:

1. Reserva o arquivo do recibo, sem sobrescrever arquivos existentes.
2. Obtém locks `SHARE ROW EXCLUSIVE` nas quatro tabelas de evidência/contadores
   (`lotes`, `reservas_ingressos`, `solicitacoes_validacao`, `ingressos`). Esses
   locks bloqueiam escritas **em todos os lotes** durante a transação. O timeout
   de aquisição é de 5 segundos; o timeout por comando é de 30 segundos.
3. Confere a origem do banco/servidor/schema e recalcula todas as evidências.
   Se algo mudou desde o diagnóstico ou o plano foi editado, recusa a aplicação.
4. Recusa qualquer plano com bloqueios e atualiza apenas
   `lotes.quantidade_resgatada`, exclusivamente para cima, comparando também
   o valor anterior. Todos os lotes do plano são aplicados em uma transação.

A ferramenta não altera capacidade, datas, pausa, ingressos, CPFs ou reservas.
Qualquer erro antes do commit reverte a transação inteira. Não some o total de
cancelados ao contador manualmente: isso duplicaria ocupações já recompostas.

## Conferência após a execução

```bash
python tools/reconciliar_ocupacao_lotes.py --lote-id 2 --saida conferencia-lote-2.json
```

O novo plano deve apresentar `acrescimo: 0` e nenhum bloqueio. Reexecutar um
plano antigo com alterações já aplicadas é recusado como desatualizado; um plano
novo sem diferenças não faz UPDATE. Essa regra evita aumentos repetidos.

Guardar o plano, o recibo e a conferência. Um recibo com `estado: aplicado`
confirma que a transação retornou após o commit. Se o processo for interrompido,
a conexão cair durante o commit ou a gravação final do recibo falhar, ele pode
ficar em `estado: verificar_banco`. Nesse caso, conferir o banco com um novo
diagnóstico antes de repetir qualquer ação.

Reiniciar os workers após a reconciliação para renovar snapshots e conexões SSE
e conferir o painel administrativo e o status público antes de encerrar a
manutenção. Lotes dentro do prazo com ocupação igual/superior à capacidade
devem continuar Esgotados, sem permitir novas reservas.

Se for necessário desfazer a correção, manter a manutenção e investigar o
histórico com o plano/recibo/backup. Não reduzir automaticamente o contador:
podem existir novos resgates, e uma redução reabriria capacidade indevida.

## Testes isolados

Instalar `requirements-test.txt` no ambiente de desenvolvimento. Executar:

```bash
python -m unittest discover -s tests -p test_ocupacao_cancelamentos.py -v
python -m unittest discover -s tests -p test_reconciliar_ocupacao_lotes.py -v
```

Os testes padrão usam SQLite em memória. Os dois testes específicos de
PostgreSQL exigem `RECONCILIACAO_TEST_DATABASE_URL` apontando explicitamente
para um servidor descartável em localhost e banco `codex_ocupacao_test`.
Eles criam e removem apenas schemas com prefixo `ocupacao_test_` nesse banco.
Sem essa variável, os testes PostgreSQL são ignorados.
