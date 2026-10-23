# Lotes ocultos e cadastros avulsos

No painel de lotes, o superadministrador pode marcar **Lote oculto** ao criar um lote.
O botão **Configurações adicionais** abre um segundo modal com:

- Reserva de cinco minutos ou consumo da vaga somente no envio.
- Análise pelo superadministrador ou aprovação e envio automático do ingresso.
- Secretaria, setor e vínculo nos modos livre, pré-preenchido editável e travado.
- Senha opcional de exatamente seis caracteres, incluindo letras, números e símbolos.

Todos os demais campos, inclusive foto, permanecem obrigatórios. Continua valendo
um ingresso ativo por CPF, inclusive entre lotes públicos e ocultos. O mesmo link
permite cadastrar participantes diferentes sucessivamente.

## Acesso e alterações

A ação de link na linha do lote permite copiar ou abrir o formulário. Regenerar
o link exige a senha atual do superadministrador. Apenas superadministradores
recebem o endereço e as configurações na API administrativa.

O link dispensa o PIN geral do site e autoriza exclusivamente o respectivo lote.
Lotes ocultos são excluídos das consultas, alternativas, caches e eventos públicos.
As rotas comuns de reserva por ID não aceitam esses lotes.

Salvar uma edição, pausar, encerrar, trocar/remover senha ou regenerar o link
invalida os formulários em andamento. A interface verifica a autorização a cada
cinco segundos; o servidor verifica novamente no envio, sob bloqueio transacional.
Alterar configurações mantém o mesmo link, mas exige reinício do formulário.
Regenerar o link e restaurar/importar um backup produzem um endereço novo.

A condição público/oculto é imutável depois da criação, tanto na API quanto no
banco PostgreSQL. Os demais campos continuam editáveis, respeitando a capacidade
já consumida e as regras de período e secretaria exclusiva.

## Validação e gerenciamento

Cadastros pendentes aparecem na tela de validações existente. Administradores
comuns podem consultar os registros, mas somente superadministradores podem
aprovar, rejeitar, editar, cancelar, reenviar e-mail ou solicitar correção de foto.
Validadores sem função administrativa não recebem as pendências avulsas.

Uma mudança de aprovação manual para imediata afeta somente novos cadastros.
Pendências anteriores continuam pendentes. Aprovação imediata emite o ingresso
e registra o e-mail na fila na mesma transação; reenviar o mesmo formulário
recupera o resultado, sem consumir outra vaga nem enviar outro ingresso.
A aprovação automática não declara que houve identificação pela API externa.

Rejeição, cancelamento, portaria, consulta do ingresso e sorteios mantêm as regras
existentes. Cadastros rejeitados continuam consumindo vaga e bloqueando novo
resgate para o CPF, conforme o fluxo atual.

## Banco e validação

A migração `migrar_lotes_ocultos` roda automaticamente na inicialização do backend,
sob o lock de inicialização existente. Lotes antigos permanecem públicos.
`migrar_fuso_lotes` converte abertura, fechamento e exclusão de colunas legadas
sem fuso para `TIMESTAMPTZ`, interpretando os valores antigos como horários de
São Paulo. Colunas já migradas são preservadas, inclusive em reinícios repetidos.
Não execute o frontend atualizado com um backend antigo: publique as duas partes
juntas e reinicie o backend para aplicar a migração.

A interface cria lotes pela rota `/api/admin/lotes` e confere a confirmação
JSON da visibilidade antes de fechar o modal. Um backend anterior, que ignora
campos novos na rota legada, recebe uma rota desconhecida em vez de criar
silenciosamente um lote público. A rota `/admin/lote` continua compatível com
clientes anteriores.

Testes principais:

```sh
python -m unittest discover -s tests -p 'test_lotes_ocultos.py'
RUN_POSTGRES_TESTS=1 python -m unittest discover -s tests -p 'test_lotes_ocultos_postgres.py'
RUN_EXISTING_DB_TESTS=1 python -m unittest discover -s tests -p 'test_lotes_banco_existente.py'
node --test tests/test_front_lotes_ocultos.mjs tests/test_front_admin_lotes_permissoes.mjs
node tests/test_browser_criacao_lote.mjs
cd frontend && npm run build
```

A suíte PostgreSQL cria e remove schemas próprios, sem chamar `init_db` nem enviar
e-mails reais. Execute-a em um ambiente com acesso ao PostgreSQL configurado e
permissão para criar schemas.

A suíte `test_lotes_banco_existente.py` usa transações externas e savepoints no
banco local já existente. Ela verifica migração, cadastros públicos e ocultos,
senha, exclusão das consultas públicas e liberação de portaria, desfazendo todas
as escritas de teste. IDs negativos evitam alterações nas sequências. Ao terminar,
ela compara os registros reais e o controle de portaria com o estado inicial.
O teste de navegador intercepta todas as APIs e não grava lotes reais.

O ensaio `tests/test_browser_fluxos_resgate.mjs` usa HTTP, frontend compilado e
PostgreSQL reais, sem interceptar APIs. Seu servidor auxiliar é
`tests/flow_e2e_server.py`, iniciado separadamente na porta local 8127 com
`RUN_FLOW_E2E=1`. Ele aceita somente o banco Docker local, usa schema, fotos e
chave de sessão descartáveis e não inicia workers de SMTP ou validação externa.
Encerre o servidor por SIGTERM para remover o schema ao final.
O ensaio cobre senha, foto, submissão, confirmação, múltiplos participantes,
CPF duplicado entre lotes, aprovação manual/imediata, PIN público, câmera e
isolamento dos campos, autorizações, listagens e contadores entre os fluxos.
