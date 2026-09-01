#!/bin/bash

# Diretório raiz do projeto
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Garantir que o Node.js e ferramentas estejam no PATH
export PATH="$HOME/nodejs/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

echo "========================================================"
echo "🚀 INICIANDO AMBOS OS SERVIDORES (FASTAPI + VUE 3)"
echo "========================================================"

# 1. Inicia o Banco de Dados PostgreSQL e o Backend FastAPI via Docker
echo "📦 Subindo containers do Banco de Dados (PostgreSQL) e Backend (FastAPI)..."
docker compose up -d db web

# Aguarda 2 segundos para o healthcheck
sleep 2

# 2. Inicia o Front-end Vue 3 (Vite Dev Server com Hot-Reload na porta 5173)
echo "⚡ Iniciando Front-end Vue 3 (Vite com Hot-Reload)..."
cd "$DIR/frontend"

# Função de limpeza para encerrar os processos filhos ao pressionar Ctrl+C
cleanup() {
    echo ""
    echo "🛑 Finalizando servidores..."
    if [ -n "$VITE_PID" ]; then
        kill "$VITE_PID" 2>/dev/null
    fi
    echo "✅ Servidor Vite finalizado com sucesso."
    exit 0
}

trap cleanup SIGINT SIGTERM

npm run dev &
VITE_PID=$!

echo ""
echo "========================================================"
echo "🎉 AMBOS OS SERVIDORES ESTÃO ONLINE E MANTIDOS ATIVOS!"
echo "   👉 Front-end Vue 3 (Dev/HMR): http://localhost:5173"
echo "   👉 Back-end FastAPI:          http://localhost:8000"
echo "   👉 Painel Administrativo:     http://localhost:5173/admin"
echo "   👉 Portaria / Scanner:        http://localhost:5173/portaria"
echo "========================================================"
echo "Pressione [Ctrl + C] para parar o servidor frontend."
echo ""

# Mantém o processo em primeiro plano
wait "$VITE_PID"