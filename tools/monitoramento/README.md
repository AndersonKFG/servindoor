# Monitoramento da VPS

Painel Netdata opcional e independente do Compose do site. Permite acompanhar
CPU, memória, swap, discos, processos, containers e conexões TCP. O coletor Nginx
acrescenta conexões ativas, estados reading/writing/waiting e requisições por
segundo. Conexões não equivalem a pessoas: o proxy Cloudflare e o keep-alive
mudam essa relação. O painel não conta reservas nem inscrições concluídas.

## 1. Na VPS

Sem teste de carga acontecendo, dentro da pasta do projeto:

```bash
cd ~/servindoor
git pull
docker compose -f tools/monitoramento/compose.yml up -d
curl --fail http://127.0.0.1:19999/api/v1/info
```

Esse Compose só inicia o monitor. Não é necessário reconstruir web nem db.
Ele usa namespaces do host, capacidades de inspeção e o socket Docker conforme
a instalação oficial do Netdata. O mount `:ro` do socket não transforma a API
Docker em uma API sem escrita; por isso o painel fica restrito ao localhost e
é acessado pelo SSH. Não publique 19999 nem encaminhe esse painel no domínio
público do site. Não foi configurada conexão com Netdata Cloud.

## 2. Abrir no computador

No PowerShell ou Ubuntu/WSL do seu PC (substitua IP_DA_VPS):

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:19999:127.0.0.1:19999 root@IP_DA_VPS
```

Informe sua senha SSH se solicitada. O terminal permanece ocupado; mantenha-o
aberto. No navegador do mesmo PC, abra http://127.0.0.1:19999 . `Ctrl+C` fecha
somente o túnel. Alguns recursos adicionais do Netdata exigem conta Cloud;
o acompanhamento local das métricas Linux não depende de conectar o servidor.

## 3. Acrescentar métricas do Nginx

Na VPS, confira primeiro se a porta está livre:

```bash
ss -ltn 'sport = :18080'
```

Se houver um serviço usando essa porta, não prossiga com a configuração padrão.
O arquivo abaixo deve ser incluído no contexto `http`; no Nginx Ubuntu padrão,
`/etc/nginx/conf.d/*.conf` já está incluído nesse contexto. Confirme com `nginx -T`.

```bash
cd ~/servindoor
test ! -e /etc/nginx/conf.d/servindoor-status.conf && cp tools/monitoramento/nginx-status.conf /etc/nginx/conf.d/servindoor-status.conf
nginx -t && systemctl reload nginx
curl --fail http://127.0.0.1:18080/basic_status
```

O `test` evita sobrescrever um arquivo existente. O reload só ocorre se a
configuração passar na validação. Se o teste falhar, não recarregue; remova apenas
o novo arquivo que acabou de copiar e confira novamente com `nginx -t`.
O coletor tentará novamente; se necessário:

```bash
docker compose -f tools/monitoramento/compose.yml restart netdata
```

Procure por Nginx, CPU, RAM, Network, TCP e Containers no painel. Verifique também
o consumo do próprio `festa_netdata`: o monitor acrescenta consumo ao servidor.

## 4. Banco e fila de e-mail, sem expor credenciais

O painel monitora os recursos do container db; as consultas abaixo acrescentam
o estado interno do PostgreSQL e da fila. Execute na pasta principal do projeto:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state;"'
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW max_connections;"'
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT status, count(*) FROM email_queue GROUP BY status;"'
docker compose logs --since=5m --tail=100 web
```

Não interpretar conexões `idle` como falha: pools mantêm conexões para reutilizar.
Investigue aumento de `idle in transaction`, esgotamento de conexões, filas que
só crescem e erros. Logs da aplicação podem conter dados de requisições; não
publique o conteúdo integral sem revisar.

## Parar e atualizar

```bash
docker compose -f tools/monitoramento/compose.yml stop
```

Para atualizar voluntariamente (não durante a abertura do lote):

```bash
docker compose -f tools/monitoramento/compose.yml pull
docker compose -f tools/monitoramento/compose.yml up -d
```

Os volumes mantêm o histórico entre reinícios. O monitor não substitui a medição
de tempos de resposta, validação do SSE, reservas e disponibilidade do site.

Referências: [Netdata em Docker](https://learn.netdata.cloud/docs/netdata-agent/installation/docker),
[coletor Nginx](https://learn.netdata.cloud/docs/collecting-metrics/web-servers-and-proxies/nginx),
[bind do painel](https://learn.netdata.cloud/docs/netdata-agent/configuration/securing-agents/web-server-reference)
e [Nginx stub_status](https://nginx.org/en/docs/http/ngx_http_stub_status_module.html).
