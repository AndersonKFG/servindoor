# Comunicações de homologação que voltam a aparecer como pendentes

O botão antigo gravava o e-mail em uma transação própria e marcava as
solicitações apenas ao final do lote. Um timeout, reinício ou erro antes desse
commit deixava mensagens enviadas sem `comunicado = true`. A correção atômica
evitou esse caminho nos novos disparos, mas não recompôs o histórico anterior.
Sem consultar esse histórico, os registros antigos continuavam elegíveis.
O número e a causa dos casos de produção devem ser confirmados no diagnóstico.

Cada nova comunicação passa a ter uma chave única na fila:
`validacao:<solicitacao_id>:<status>`. O contador, os cards e os disparos
consultam esse registro além de `comunicado`. A restrição única no PostgreSQL
impede outro enfileiramento com a mesma chave mesmo se a marcação for perdida.
`Comunicado` continua significando **registrado na fila**, sem prometer entrega
na caixa de entrada. Falhas SMTP continuam sob responsabilidade do dispatcher.

## Recuperar o histórico sem enviar novamente

Manter todos os processos da aplicação parados durante a publicação e a
recuperação. Criar a coluna `email_queue.idempotency_key` e o índice único
pela migração abaixo, sem iniciar o servidor nem o dispatcher. A recuperação
é uma etapa explícita: publicar o código sozinho não altera os 929 registros.

Executar no ambiente que já possui o banco e as variáveis do backend:

```bash
python -m pip install -r tools/requirements-reconciliacao.txt
python tools/reconciliar_comunicacoes_validacao.py
```

Por padrão, a ferramenta usa uma transação somente de leitura. O relatório
mostra `pendentes_antes`, `recuperaveis`, `sem_comprovacao`,
`duplicatas_na_fila` e os IDs das solicitações/mensagens associadas. Não imprime
endereços, nomes, CPFs, tokens de ingresso ou anexos.

A associação exige todos estes critérios:

- solicitação aprovada, ainda sem marcação nem chave de comunicação;
- ingresso ativo do mesmo participante e do mesmo lote;
- mensagem do tipo `ticket` para o endereço cadastrado;
- QR Code do anexo contendo exatamente o token desse ingresso;
- pelo menos uma mensagem com `status = sent` e `sent_at` preenchido.

O QR é lido dos anexos guardados na fila usando
[ZXing-C++](https://github.com/zxing-cpp/zxing-cpp/tree/master/wrappers/python).
E-mail compartilhado, isoladamente, não comprova identidade. Anexos ilegíveis,
ingressos cancelados, mensagens genéricas, rejeições, envios falhos e registros
apenas aguardando envio permanecem sem alteração. Se o histórico foi apagado,
o cadastro mudou de e-mail ou o envio ocorreu antes da fila durável, será
necessário conferir outras evidências; não zerar o contador indiscriminadamente.

Depois de conferir o diagnóstico, manter **todos** os processos da aplicação
(inclusive workers) parados e executar com o mesmo ambiente do backend:

```bash
python tools/reconciliar_comunicacoes_validacao.py --aplicar
```

O modo de aplicação recalcula o diagnóstico dentro da própria transação.
Obtém o lock do dispatcher e bloqueia escritas nas tabelas de evidência durante
a conferência. Se houver um dispatcher ativo, recusa a aplicação. Marca como
comunicadas apenas as solicitações comprovadas e vincula a mensagem enviada
à chave única. Usa a data original de registro na fila. Cópias ainda em
`queued`/`sending` com o mesmo token comprovadamente enviado passam a
`cancelled`, evitando que o reinício do dispatcher as envie outra vez.
Mantém as mensagens já enviadas e os anexos como histórico.

Repetir o diagnóstico após o commit deve mostrar zero recuperáveis para os
registros tratados. Reiniciar a aplicação e conferir o contador. Homologações
novas e casos sem comprovação continuam pendentes. A ferramenta não envia
e-mails nem gera ingressos. A transação reverte todas as alterações se houver
erro; em caso de perda de conexão durante o commit, conferir o diagnóstico
novamente antes de repetir.

## Executar pelo Docker Compose de produção

Na pasta do servidor que contém `docker-compose.yml`, executar em Bash.
O site ficará indisponível até a última etapa. Se houver outras instâncias
da aplicação usando o mesmo banco, pará-las também. O banco permanece ativo.
O container temporário herda a configuração do backend e executa apenas o CLI;
a dependência de QR é instalada só nesse container temporário.

### 1. Parar envios, guardar backup e preparar a imagem nova

```bash
set -euo pipefail
umask 077
docker compose stop web
DIR_EMAILS="$HOME/servindoor-emails-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DIR_EMAILS"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DIR_EMAILS/banco-antes.dump"
git pull --ff-only origin main
docker compose build web
```

### 2. Criar apenas a coluna e o índice necessários

Esta é a mesma migração idempotente de `migrar_idempotencia_emails`. Não
executar `docker compose up` nesta etapa, pois isso iniciaria o dispatcher.

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
BEGIN;
SET LOCAL lock_timeout = '5s';
ALTER TABLE email_queue ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR;
CREATE UNIQUE INDEX IF NOT EXISTS uq_email_queue_idempotency ON email_queue (idempotency_key);
COMMIT;
SQL
```

### 3. Diagnosticar sem alterar registros

```bash
docker compose run --rm --no-deps -T web sh -c 'python -m pip install -r tools/requirements-reconciliacao.txt >&2 && python tools/reconciliar_comunicacoes_validacao.py' | tee "$DIR_EMAILS/diagnostico.json"
```

Conferir `recuperaveis`, `sem_comprovacao` e `duplicatas_na_fila`. O total
recuperável pode ser menor que 929: a ferramenta exige evidência do envio
de cada ingresso. Não transformar os casos sem comprovação em comunicados.

### 4. Aplicar a recuperação e conferir com o site ainda parado

```bash
docker compose run --rm --no-deps -T web sh -c 'python -m pip install -r tools/requirements-reconciliacao.txt >&2 && python tools/reconciliar_comunicacoes_validacao.py --aplicar' | tee "$DIR_EMAILS/aplicacao.json"
docker compose run --rm --no-deps -T web sh -c 'python -m pip install -r tools/requirements-reconciliacao.txt >&2 && python tools/reconciliar_comunicacoes_validacao.py' | tee "$DIR_EMAILS/conferencia.json"
```

O primeiro relatório deve ter `estado: aplicado`; a conferência deve apresentar
`recuperaveis: 0`. Os casos sem evidência permanecem pendentes. Se algum comando
falhar, resolver a falha e conferir o banco antes de reativar a aplicação.

### 5. Reativar a aplicação

Somente após concluir a conferência:

```bash
docker compose up -d --no-deps web
docker compose logs --tail=80 web
```

A recuperação não envia mensagens. Ao reativar o serviço, mensagens legítimas
que já estavam na fila retomam seu processamento normal. As duplicatas
canceladas não são selecionadas pelo dispatcher. Novas homologações sem
comunicação registrada continuam aguardando o botão de envio.

## Verificação isolada

```bash
python -m pip install -r requirements-test.txt -r tools/requirements-reconciliacao.txt
python -m unittest discover -s tests -p test_validacoes_comunicacao.py -v
python -m unittest discover -s tests -p test_validacoes_paginacao.py -v
python -m unittest discover -s tests -p test_reconciliar_comunicacoes_validacao.py -v
```

Os testes usam SQLite em memória, sem SMTP nem acesso à produção. Incluem
929 registros enviados com marcação perdida e uma homologação nova, QR real,
e-mail compartilhado, duplicatas na fila, rollback e repetição idempotente.

A suíte `test_validacoes_comunicacao_postgres.py` exige
`COMUNICACAO_TEST_DATABASE_URL` apontando explicitamente para PostgreSQL local
descartável (`localhost`, `127.0.0.1` ou `db` no Docker Compose local). Ela cria
e remove apenas schemas com prefixo `comunicacao_test_`, sem executar `init_db`.
Valida o índice único, a migração repetida, dois disparos concorrentes, rollback,
a recuperação do histórico e a preservação de UTC. Não apontar para produção.
