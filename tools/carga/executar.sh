#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v docker >/dev/null || { echo 'É necessário ter Docker disponível neste Ubuntu/WSL.'; exit 1; }
command -v python3 >/dev/null || { echo 'É necessário ter Python 3 disponível para acompanhar o gerador.'; exit 1; }
echo 'Execute no Ubuntu/WSL do seu computador, separado da VPS.'
echo 'Este teste gera tráfego real. Ctrl+C interrompe.'
case "${LOAD_HTTP1:-0}" in
  0) export GODEBUG=''; echo 'HTTP: negociação automática (padrão).' ;;
  1) export GODEBUG='http2client=0'; echo 'Diagnóstico: HTTP/1.1 forçado no gerador; os critérios de falha permanecem iguais.' ;;
  *) echo 'LOAD_HTTP1 deve ser 0 ou 1.'; exit 1 ;;
esac
export LOAD_PROFILE="${LOAD_PROFILE:-normal}"
[[ "$LOAD_PROFILE" == normal || "$LOAD_PROFILE" == diagnostico ]] || { echo 'LOAD_PROFILE inválido.'; exit 1; }
if [[ "$LOAD_PROFILE" == diagnostico ]]; then
  echo 'Diagnóstico curto: somente home, até 1000 VUs; rampa de 1 min + patamar de 2 min + saída de 30s.'
fi
read -r -p 'Endereço [https://www.servindoor.com.br]: ' TARGET_URL
export TARGET_URL="${TARGET_URL:-https://www.servindoor.com.br}"
read -r -p 'Modo: home, reservas ou resgate [home]: ' TEST_MODE
export TEST_MODE="${TEST_MODE:-home}"
[[ "$TEST_MODE" == home || "$TEST_MODE" == reservas || "$TEST_MODE" == resgate ]] || { echo 'Modo inválido.'; exit 1; }
if [[ "$TEST_MODE" != home ]]; then
  read -r -p 'Máximo: 10, 100, 500, 1000 ou 2000 [10]: ' MAX_VISITORS
else
  read -r -p 'Máximo: 10, 100, 500, 1000, 2000, 3000 ou 4000 [10]: ' MAX_VISITORS
fi
export MAX_VISITORS="${MAX_VISITORS:-10}"
case "$MAX_VISITORS" in 10|100|500|1000|2000|3000|4000) ;; *) echo 'Limite inválido.'; exit 1 ;; esac
if [[ "$TEST_MODE" != home && "$MAX_VISITORS" -gt 2000 ]]; then
  echo 'Reservas e resgate aceitam até 2000 visitantes.'
  exit 1
fi
if [[ "$LOAD_PROFILE" == diagnostico && ( "$TEST_MODE" != home || "$MAX_VISITORS" -gt 1000 ) ]]; then
  echo 'O diagnóstico curto permite somente home, até 1000 visitantes.'
  exit 1
fi
export TEST_RUN_ID="$(date -u +%Y%m%dT%H%M%S)_${RANDOM}"
read -r -s -p 'PIN do site (não aparece; Enter se desativado): ' SITE_PIN
echo
export SITE_PIN
export TEST_LOTE_ID=0 LOAD_TEST_SECRET=''
export TEST_SECRETARIA_ID=0 LOAD_TEST_EMAIL='' LOAD_TEST_EMAIL_CONFIRMED=''
if [[ "$TEST_MODE" != home ]]; then
  echo 'Use um lote exclusivo de teste, sem inscrições reais, com 1500 vagas para representar a primeira abertura.'
  echo 'Para representar as outras aberturas, teste separadamente lotes de 1000 ou 500 vagas.'
  read -r -p 'ID desse lote: ' TEST_LOTE_ID
  [[ "$TEST_LOTE_ID" =~ ^[1-9][0-9]*$ ]] || { echo 'ID inválido.'; exit 1; }
  read -r -s -p 'Chave temporária LOAD_TEST_SECRET (não aparece): ' LOAD_TEST_SECRET
  echo
  [[ ${#LOAD_TEST_SECRET} -ge 32 ]] || { echo 'A chave precisa ter pelo menos 32 caracteres.'; exit 1; }
fi
if [[ "$TEST_MODE" == resgate ]]; then
  echo "Resgate: $MAX_VISITORS visitantes chegam diretamente; cada um tenta enviar um formulário com foto sintética."
  echo 'Este modo GRAVA cadastros e fotos, consome vagas e enfileira e-mails reais.'
  echo 'A consulta externa de servidores é dispensada somente com a autorização temporária válida.'
  read -r -p 'ID de uma secretaria cadastrada (permitida nesse lote): ' TEST_SECRETARIA_ID
  [[ "$TEST_SECRETARIA_ID" =~ ^[1-9][0-9]*$ ]] || { echo 'Secretaria inválida.'; exit 1; }
  read -r -p "E-mail controlado que receberá até $MAX_VISITORS mensagens: " LOAD_TEST_EMAIL
  [[ "$LOAD_TEST_EMAIL" =~ ^[^[:space:]@,\;\<\>]+@[^[:space:]@,\;\<\>]+\.[^[:space:]@,\;\<\>]+$ ]] || { echo 'Informe um único e-mail válido.'; exit 1; }
  read -r -p 'Para autorizar esses e-mails de teste, digite ENVIAR_EMAILS: ' LOAD_TEST_EMAIL_CONFIRMED
  [[ "$LOAD_TEST_EMAIL_CONFIRMED" == ENVIAR_EMAILS ]] || { echo 'Cancelado.'; exit 0; }
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
container_name="servindoor-carga-$TEST_RUN_ID"
python3 monitorar_gerador.py "$container_name" "$output_dir/gerador.jsonl" &
monitor_pid=$!
trap 'kill "$monitor_pid" 2>/dev/null || true' EXIT
docker run --rm --init --name "$container_name" --network host --ulimit nofile=16384:16384 \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e K6_AUTO_EXTENSION_RESOLUTION=false -e GODEBUG \
  -e TARGET_URL -e TEST_MODE -e MAX_VISITORS -e TEST_RUN_ID -e SITE_PIN -e LOAD_PROFILE \
  -e TEST_LOTE_ID -e LOAD_TEST_SECRET -e TEST_SECRETARIA_ID -e LOAD_TEST_EMAIL -e LOAD_TEST_EMAIL_CONFIRMED \
  --entrypoint /runtime/k6-1.3.0-sse-0.1.11 -v "$(pwd)/.runtime:/runtime:ro" \
  -v "$(pwd)/carga.js:/scripts/carga.js:ro" -v "$(pwd)/foto_teste.jpg:/scripts/foto_teste.jpg:ro" -v "$output_dir:/resultados" \
  grafana/k6:latest run --out json=/resultados/metricas.json /scripts/carga.js \
  2>&1 | tee "$output_dir/execucao.log"
