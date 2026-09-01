# 🚀 Guia Rápido: Rodando a Festa do Servidor no Ubuntu / Docker

Este guia orienta como transferir e executar o projeto no seu ambiente **Ubuntu (WSL ou Nativo)** utilizando **Docker** e **PostgreSQL Local de Alta Performance**.

---

## 📁 1. Transferindo o Projeto para o Ubuntu (via Explorador de Arquivos)

Se você utiliza **WSL no Windows**, você pode acessar o sistema de arquivos do Ubuntu diretamente pelo Explorador de Arquivos do Windows:

1. Abra o **Explorador de Arquivos** no Windows.
2. Na barra de endereços, digite:
   ```text
   \\wsl$\Ubuntu\home\seu_usuario
   ```
   *(Substitua `seu_usuario` pelo seu nome de usuário no Ubuntu)*
3. Cole a pasta inteira `festa_servidor` dentro desse diretório.

---

## 🖥️ 2. Abrindo o Terminal do Ubuntu

1. Abra o terminal do **Ubuntu** (ou PowerShell com `wsl`).
2. Navegue até a pasta do projeto:
   ```bash
   cd ~/festa_servidor
   ```

---

## ⚡ 3. Executando o Projeto com Docker Compose

Suba o banco de dados PostgreSQL local e a aplicação web com 1 comando:

```bash
docker compose up --build -d
```

> 💡 **O que este comando faz?**
> - Inicia o container do **PostgreSQL 16 Alpine** otimizado em memória RAM (buffers de 256MB, zero latência de rede externa).
> - Constrói e sobe o container **FastAPI** com **Gunicorn** e 4 workers assíncronos de alta performance.
> - As tabelas do banco de dados são verificadas e criadas automaticamente na inicialização.

---

## 👤 4. Criando os Dados Iniciais e Usuário Administrador

Após os containers estarem rodando, execute o script de semente (seed) diretamente dentro do container:

```bash
docker compose exec web python init_admin.py
```

Isso criará:
- **Secretarias padrão** (Geral, Saúde, Educação, Administração).
- **1º Lote de Ingressos** ativo com 500 vagas.
- **Usuário Administrador**:
  - **CPF**: `00000000000` (ou `000.000.000-00`)
  - **Senha**: `admin123`

---

## 🌐 5. Acessando a Aplicação

Abra o seu navegador no Windows:
- **Página Pública / Resgate**: [http://localhost:8000](http://localhost:8000)
- **Painel Administrativo**: [http://localhost:8000/login](http://localhost:8000/login)
- **Portaria / Validação**: [http://localhost:8000/portaria](http://localhost:8000/portaria)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🛠️ Comandos Úteis do Dia a Dia

- **Ver logs da aplicação em tempo real**:
  ```bash
  docker compose logs -f web
  ```

- **Ver logs do banco de dados**:
  ```bash
  docker compose logs -f db
  ```

- **Resetar senhas de staff para um novo valor**:
  ```bash
  docker compose exec web python resetar_senhas.py nova_senha_aqui
  ```

- **Parar os containers**:
  ```bash
  docker compose down
  ```

- **Reiniciar os containers**:
  ```bash
  docker compose restart
  ```

---

## 🏎️ O que foi otimizado para Performance Extrema?

1. **Latência de Banco Sub-Milissegundo**: PostgreSQL local rodando na mesma rede interna do container (`festa_net`).
2. **Connection Pooling Ativo**: Pool de conexões assíncronas persistentes (`pool_size=20`, `max_overflow=10`), eliminando overhead de TCP handshake a cada request.
3. **Statement Caching**: Cache de compilação de SQL habilitado no `asyncpg` (`statement_cache_size=1024`).
4. **Índices no Banco**: Chaves estrangeiras e campos de filtro (`usuario_id`, `lote_id`, `validado`, `tipo`, `data_hora`, `ativo`) indexados para evitar `Seq Scan`.
5. **Prevenção de Concorrência**: Bloqueio de linha (`with_for_update`) no resgate para garantir integridade e velocidade sob milhares de acessos simultâneos.
6. **Compressão HTTP GZip**: Respostas HTML/JSON comprimidas no ar para carregamento instantâneo no navegador/mobile.
7. **Múltiplos Workers**: Servidor de aplicação rodando com Gunicorn + Uvicorn Workers assíncronos.
