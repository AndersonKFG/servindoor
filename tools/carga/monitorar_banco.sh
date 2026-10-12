#!/usr/bin/env bash
# Executar na VPS, em outro terminal durante a carga. Somente SELECT.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

duration="${1:-180}"
[[ "$duration" =~ ^[0-9]+$ && "$duration" -ge 1 && "$duration" -le 900 ]] || {
  echo 'Informe a duração em segundos, entre 1 e 900.' >&2
  exit 1
}
command -v docker >/dev/null || { echo 'Docker não encontrado.' >&2; exit 1; }
mkdir -p tools/carga/resultados
output="tools/carga/resultados/banco_$(date -u +%Y%m%dT%H%M%SZ)_$$.csv"

# Não exporta o texto SQL nem parâmetros: somente a categoria da operação,
# estado, tempos e PIDs. O identificador da conexão permite seguir o bloqueador.
sql=$(cat <<'SQL'
WITH atividade AS MATERIALIZED (
  SELECT pid, state, wait_event_type, wait_event, xact_start, query_start,
         pg_blocking_pids(pid) AS bloqueadores,
         CASE
           WHEN query ILIKE '%pg_notify(%' THEN 'publicacao_evento'
           WHEN query ILIKE '%FOR UPDATE%' AND query ILIKE '%lotes%' THEN 'lock_lote'
           WHEN query ILIKE '%rate_limit_tentativas%' THEN 'limitador'
           WHEN query ILIKE '%reservas_ingressos%' AND query ILIKE 'INSERT%' THEN 'criar_reserva'
           WHEN query ILIKE '%reservas_ingressos%' AND query ILIKE 'UPDATE%' THEN 'atualizar_reserva'
           WHEN query ILIKE '%reservas_ingressos%' THEN 'consulta_reservas'
           WHEN query ILIKE '%lotes%' THEN 'consulta_lote'
           WHEN query ILIKE 'COMMIT%' THEN 'commit'
           WHEN query ILIKE 'ROLLBACK%' THEN 'rollback'
           ELSE 'outra'
         END AS operacao
  FROM pg_stat_activity
  WHERE datname = current_database()
    AND backend_type = 'client backend' AND pid <> pg_backend_pid()
)
SELECT clock_timestamp() AT TIME ZONE 'UTC' AS instante_utc, pid, state, wait_event_type, wait_event,
       ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - xact_start)) * 1000) AS transacao_ms,
       ROUND(EXTRACT(EPOCH FROM (clock_timestamp() - query_start)) * 1000) AS consulta_ms,
       bloqueadores, operacao
FROM atividade
WHERE state IS DISTINCT FROM 'idle' OR cardinality(bloqueadores) > 0
   OR pid IN (SELECT unnest(bloqueadores) FROM atividade)
ORDER BY pid;
SQL
)

echo "Monitorando o banco por ${duration}s. Arquivo: $output"
echo 'Inicie o teste no outro terminal. Ctrl+C encerra apenas este monitor.'
deadline=$((SECONDS + duration))
first=1
while (( SECONDS < deadline )); do
  if (( first )); then
    options='--csv'
    first=0
  else
    options='--csv --tuples-only'
  fi
  # POSTGRES_USER/DB vêm do ambiente do container, sem ler ou imprimir a .env.
  docker compose exec -T db sh -c '
    exec psql -X -v ON_ERROR_STOP=1 "$@" -U "$POSTGRES_USER" -d "$POSTGRES_DB"
  ' sh $options -c "$sql" >> "$output"
  sleep 2
done
echo "Coleta concluída: $output"
