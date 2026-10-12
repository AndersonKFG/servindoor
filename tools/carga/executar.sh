#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v docker >/dev/null || { echo 'É necessário ter Docker disponível neste Ubuntu/WSL.'; exit 1; }
echo 'Execute no Ubuntu/WSL do seu computador, separado da VPS.'
echo 'Este teste gera tráfego real. Ctrl+C interrompe.'
read -r -p 'Endereço [https://www.servindoor.com.br]: ' TARGET_URL
export TARGET_URL="${TARGET_URL:-https://www.servindoor.com.br}"
read -r -p 'Modo: home ou reservas [home]: ' TEST_MODE
export TEST_MODE="${TEST_MODE:-home}"
[[ "$TEST_MODE" == home || "$TEST_MODE" == reservas ]] || { echo 'Modo inválido.'; exit 1; }
read -r -p 'Máximo: 10, 100, 500, 1000, 2000, 3000 ou 4000 [10]: ' MAX_VISITORS
export MAX_VISITORS="${MAX_VISITORS:-10}"
case "$MAX_VISITORS" in 10|100|500|1000|2000|3000|4000) ;; *) echo 'Limite inválido.'; exit 1 ;; esac
export TEST_RUN_ID="$(date -u +%Y%m%dT%H%M%S)_${RANDOM}"
read -r -s -p 'PIN do site (não aparece; Enter se desativado): ' SITE_PIN
echo
export SITE_PIN
export TEST_LOTE_ID=0 LOAD_TEST_SECRET=''
if [[ "$TEST_MODE" == reservas ]]; then
  echo 'Use um lote exclusivo de teste, sem inscrições reais, com pelo menos 4000 vagas.'
  read -r -p 'ID desse lote: ' TEST_LOTE_ID
  [[ "$TEST_LOTE_ID" =~ ^[1-9][0-9]*$ ]] || { echo 'ID inválido.'; exit 1; }
  read -r -s -p 'Chave temporária LOAD_TEST_SECRET (não aparece): ' LOAD_TEST_SECRET
  echo
  [[ ${#LOAD_TEST_SECRET} -ge 32 ]] || { echo 'A chave precisa ter pelo menos 32 caracteres.'; exit 1; }
fi
read -r -p "Destino: $TARGET_URL | modo: $TEST_MODE | até $MAX_VISITORS. Digite TESTAR: " confirmation
[[ "$confirmation" == TESTAR ]] || { echo 'Cancelado.'; exit 0; }
mkdir -p resultados
output_dir="$(pwd)/resultados/$TEST_RUN_ID"
mkdir -p "$output_dir"
echo "Resultados em: $output_dir"
echo 'O Docker prepara o k6 com SSE na primeira execução (pode levar alguns minutos).'
if [[ ! -f .runtime/k6-1.3.0-sse-0.1.11 ]]; then
  mkdir -p .runtime
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$(pwd)/.runtime:/runtime" grafana/xk6:latest \
    build v1.3.0 --with github.com/phymbert/xk6-sse@v0.1.11 --output /runtime/k6-1.3.0-sse-0.1.11
fi
docker run --rm --init --network host --ulimit nofile=16384:16384 \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e K6_AUTO_EXTENSION_RESOLUTION=false \
  -e TARGET_URL -e TEST_MODE -e MAX_VISITORS -e TEST_RUN_ID -e SITE_PIN \
  -e TEST_LOTE_ID -e LOAD_TEST_SECRET \
  --entrypoint /runtime/k6-1.3.0-sse-0.1.11 -v "$(pwd)/.runtime:/runtime:ro" \
  -v "$(pwd)/carga.js:/scripts/carga.js:ro" -v "$output_dir:/resultados" \
  grafana/k6:latest run --out json=/resultados/metricas.json /scripts/carga.js
