# Central de Documentos Legais

## Acesso e estado inicial

Painel: `/admin/documentos-legais`. Somente **Super Administrador**, papel existente
`admin_geral`, pode acessar a rota, o menu (desktop/mobile), as métricas, os arquivos
privados e **todas** as APIs de gestão em `/api/admin/legal/*`. Administradores comuns,
validadores, portaria, entregadores e participantes recebem 403 na API.

Não houve deploy, publicação de documentos, envio real de e-mails ou ativação de
controles durante o desenvolvimento. Os ensaios utilizam schemas descartáveis.

Na primeira inicialização:

| Controle persistido | Valor |
| --- | --- |
| `require_on_redemption` | `false` |
| `voluntary_enabled` | `false` |
| `communications_enabled` | `false` |
| `token_days` | `30` (ajustável entre 1 e 180 dias) |
| `legacy_cutoff` | `NULL`, congelado quando o primeiro par de documentos é publicado |

Publicar um documento não altera controles nem cria campanhas. A inicialização não
cria documentos ou aceites. Desativar os comunicados pausa as mensagens legais na fila;
uma mensagem já em trânsito SMTP pode concluir. Habilitar novamente permite continuar
uma campanha anteriormente autorizada.

## Banco e migração

O projeto utiliza migrações idempotentes em `app/db/session.py`, sem Alembic. A nova
`app/db/legal_migration.py:migrate_legal` segue esse mecanismo, sob o mesmo advisory lock
de `init_db`. Não executar manualmente em produção durante esta entrega.

Tabelas aditivas:

- `legal_config`: singleton com os controles independentes.
- `legal_documents`: conteúdo binário privado, tipo, título, versão, notas, hash,
  estado, responsável e instantes de criação/publicação.
- `legal_acceptances`: participante interno, documentos exatos e respectivos hashes,
  método, operação e instante UTC. A política apresentada é registrada separadamente.
- `legal_campaigns`: autorização explícita, versões e responsável pelo disparo.
- `legal_invitations`: público congelado, hash do token, validade, geração e utilização.
- `legal_audit`: publicações, rascunhos, controles, testes, disparos e reenvios.

Reutiliza `usuarios`, `ingressos`, `rate_limit_tentativas` e `email_queue`. Não altera
colunas de participantes, ingressos, reservas ou validações existentes. Não gera
aceites retroativos. Defaults iniciais são inseridos com `ON CONFLICT DO NOTHING`,
preservando escolhas administrativas em reinícios.

Índices únicos impedem versões repetidas por tipo, dois documentos vigentes do mesmo
tipo, aceites duplicados por participante/Termos, campanhas repetidas por par de
documentos e tokens repetidos. Triggers PostgreSQL protegem documentos publicados,
auditoria e aceites contra alteração/exclusão, e validam hashes/documentos no aceite.
Arquivar/substituir preserva os bytes, o título, a versão e os dados de publicação.

O rollback da aplicação não deve excluir essas tabelas: são evidências independentes
do ciclo operacional do evento. Um binário anterior pode ignorá-las sem modificar os
dados existentes. Instalar as novas dependências de `requirements.txt` antes de iniciar
a nova versão (`pypdf` e `defusedxml`).

## Arquivos e consulta pública

Uploads são limitados a 5 MB (corpo HTTP limitado pela proteção existente), aceitam
PDF/DOCX estruturalmente válidos e rejeitam conteúdo ativo, macros, arquivos embutidos,
PDF criptografado, ZIP excessivo, caminhos inseguros, XML com entidades e relações
externas. DOCX com campos ativos ou links externos deve ser exportado como PDF seguro
antes do envio. A validação é conservadora; não substitui um antivírus especializado.

Os bytes ficam em PostgreSQL, fora de `/static`, sem arquivo executável ou caminho
escolhido pelo usuário. Downloads usam nomes internos por ID, MIME fixo, `nosniff`,
`no-store` e CSP sandbox. PDF tem visualização integrada; DOCX é baixado. Não há
extração ou renderização de HTML de documentos. Backups do PostgreSQL passam a conter
também esses arquivos e devem manter o controle de acesso já utilizado para o banco.

`/termos-de-uso` e `/politica-de-privacidade` são públicos e independem do PIN do site.
Sem publicação, apresentam indisponibilidade controlada. Links no rodapé e no resgate
só aparecem para tipos publicados. Arquivos de versões **anteriormente publicadas**
continuam consultáveis por ID para permitir a leitura do conteúdo exato dos convites
e aceites históricos. Rascunhos e arquivos arquivados sem publicação nunca ficam públicos.

## Resgates

Desativado, o backend mantém as regras atuais e não grava evidência legal. Ativado,
exige `legal_accepted=true`, `legal_terms_id` e `legal_privacy_id` correspondentes ao par
vigente, além de todas as validações existentes da reserva e do participante.

O formulário apresenta, antes do botão de envio, o aviso compacto “Ao enviar o
formulário, concordo com os Termos de Uso da Servindoor”, com links para os Termos e a
Política de Privacidade. Não há checkbox no resgate: a ação de enviar o formulário
encaminha a concordância e as versões consultadas. Carregar a página ou abrir os links
não registra aceite. Uma tentativa pendente em memória preserva as versões originalmente
enviadas. O backend verifica novamente o par no commit; publicação concorrente é
coordenada pelo lock da configuração. Em caso de substituição, o participante deve
recarregar, consultar e confirmar os novos documentos.

O aceite entra na mesma transação da solicitação/ingresso, reserva, ocupação do lote e
filas existentes. Uma falha nessa transação não deixa um aceite isolado. Repetir um
resgate já confirmado recupera a operação existente sem exigir novo aceite nem duplicá-lo.
Vale tanto para o fluxo público quanto para os lotes ocultos, que compartilham esse código.

## Confirmação voluntária e comunicação

Destinatários: usuários ativos, não excluídos, com ingresso ativo resgatado antes de
`legacy_cutoff` e e-mail cadastrado. Quem já confirmou os Termos selecionados é ignorado.
A campanha congela esse público em um único `INSERT SELECT`; geração de tokens e
composição dos e-mails acontecem em lotes de 50 no dispatcher existente.

O token tem 256 bits aleatórios, é independente do ingresso, fica armazenado por SHA-256
e vincula participante e par documental. A URL não contém CPF. Abrir o link ou o e-mail
não aceita documentos. GET retorna apenas primeiro nome e documentos; confirmação é
POST explícito com checkbox e versões. Repetições e POSTs concorrentes não duplicam a
evidência. A posse do link é o método registrado (`email_link`), sem alegação de prova
absoluta da identidade do titular.

Depois do prazo, o titular pode solicitar outro link pelo link expirado. O destino
continua sendo o e-mail já cadastrado, sujeito aos controles e rate limit. O novo link
invalida o anterior. Se os comunicados estiverem pausados, a interface orienta procurar
a equipe. Em nenhum estado são alterados, cancelados ou bloqueados ingressos existentes.

A prévia usa nome/âncora fictícios, sem criar tokens. O teste só pode ir ao endereço da
conta autenticada do Super Administrador e seu botão abre a consulta pública, sem
registrar aceite. O disparo real exige digitar `AUTORIZAR ENVIO` e confirmar o modal.
Repetir a autorização do mesmo par não cria outra campanha.

Prévia, teste e campanha utilizam o mesmo HTML formatado em `email_body`: card fluido
de até 600 px, identidade escura com ciano, magenta e âmbar, destaque para a validade
do ingresso, botão de confirmação e links públicos no rodapé. Estilos inline, tabelas
de apresentação e largura de fallback para Outlook evitam depender do CSS do site,
fontes externas ou imagens remotas. A alteração do template vale para as mensagens
geradas após a atualização; não altera e-mails já enviados ou corpos já enfileirados.

O dispatcher reutiliza eleição PostgreSQL, quota diária, taxa SMTP configurada e
retentativas com backoff (30, 60, 120 e 240 segundos; até cinco tentativas).
`Message-ID` é estável por item da fila. E-mails não compartilham destinatários.

Estados mostrados: pendente, enfileirado, em envio, enviado ao SMTP, falha, concordância
registrada e envio incerto. **Não há webhook de entrega no projeto**: portanto não se
afirma entrega confirmada, leitura ou aceite a partir de `sent`.

SMTP não garante exactly-once após perda da resposta a DATA. Em caso de queda de conexão
ambígua ou interrupção do worker durante um comunicado legal, o item fica `uncertain`,
sem reenvio automático. A operação deve conferir o provedor usando o ID da fila e
`Message-ID` antes de decidir, por procedimento operacional auditado, se houve envio.
Falhas conhecidas e links enviados já expirados permitem reenvio explícito pelo painel;
mensagens ainda na fila ou com link enviado válido não são reenviadas pelo botão.
Links que expiram antes do despacho falham sem chamar SMTP.

## Segurança, registros e retenção

As operações administrativas usam a autenticação existente por cookie e a dependência
`get_current_admin_geral`. Mutações legais exigem `X-Legal-Action: 1` e rejeitam
`Sec-Fetch-Site: cross-site`. O valor protegido `same-origin`, definido pelo navegador,
permite reconhecer a origem legítima mesmo quando um proxy altera Host ou esquema.
Sem essa indicação, `Origin` deve corresponder ao endereço público configurado ou à
origem da requisição recebida. O proxy `/api` do Vite preserva Host (`changeOrigin: false`)
também para navegadores sem Fetch Metadata. Headers de encaminhamento arbitrários não
são usados para autorizar origens. Não se habilita CORS. Confirmação
usa o token em header, sem colocar o token nos caminhos da API, e possui rate limit
persistente por IP/ação. Não são coletados IP, user-agent ou CPF adicionais no aceite.

As páginas com token recebem `Referrer-Policy: no-referrer`, `no-store`, `noindex` e CSP
restrita à própria origem, inclusive bloqueando fontes externas e rastreamento externo.
O middleware redige o token durante a emissão do access log Uvicorn/Gunicorn. Na
infraestrutura externa, manter também o caminho `/confirmar_termos/*` fora de analytics
e redigir/desabilitar seus access logs no proxy/CDN; cabeçalhos da aplicação não podem
apagar logs de um intermediário que recebeu a URL antes dela.

Tokens/hashes não são retornados nas listagens administrativas. O corpo com link é
retido temporariamente na fila porque é necessário para o envio e suas retentativas;
é removido após sucesso ou expiração antes do despacho. Restringir acesso de operação
à tabela da fila. Logs do processamento legal não imprimem corpo ou parâmetros SQL.

Política técnica de retenção: documentos publicados, aceites e auditoria **não sofrem
exclusão automática**, nem entram em rotinas de limpeza operacional dos eventos. O
responsável deve revisar a necessidade de guarda anualmente e aprovar formalmente o
prazo final e eventuais bloqueios de descarte conforme as finalidades e obrigações da
Servindoor, antes de qualquer expurgo. O módulo preserva as evidências e sua integridade;
não atribui um prazo jurídico universal nem executa descarte presumido. O procedimento
de expurgo autorizado exige administração do banco, backup e registro da decisão, pois
os triggers impedem exclusão comum pela aplicação.

## Publicação e ativação após aprovação

1. Entrar como Super Administrador e abrir **Documentos Legais**.
2. Cadastrar o PDF/DOCX aprovado dos Termos com versão única e observações.
3. Cadastrar a Política de Privacidade aprovada.
4. Abrir os arquivos pela prévia e conferir conteúdo, versão e SHA-256.
5. Publicar cada documento aprovado; conferir as duas páginas públicas.
6. Habilitar somente **Exigir aceite nos novos resgates** e salvar/confirmar; isso
   apresenta o aviso de concordância por envio do formulário.
7. Fazer um resgate controlado conforme autorização de operação; conferir o histórico.
8. Habilitar a confirmação voluntária e os comunicados quando autorizado.
9. Pré-visualizar o e-mail e solicitar teste para a própria conta autorizada.
10. Selecionar os documentos, digitar a autorização e confirmar o disparo.
11. Atualizar o painel para acompanhar fila, falhas, pendências e confirmações.

Nova redação exige nova versão. Publicar a substituta arquiva a anterior sem sobrescrever
o arquivo. Desabilitar os controles pelo painel permite pausar o recurso preservando
os ingressos e os registros já feitos.

## Validação

- `npm run build` em `frontend`: sem erros; permanece o aviso de chunk principal >500 kB.
- `tests/test_legal_documents.py`: 27 testes com PostgreSQL isolado, incluindo upload,
  imutabilidade no banco, CSRF/RBAC de todos os endpoints, resgate desativado/obrigatório,
  rollback, GET/POST, token inválido/expirado/utilizado, concorrência/idempotência,
  deduplicação, fila real com SMTP simulado, backoff, pausa, falhas e envio incerto.
- `tests/test_legal_origin.py`: 10 testes de origem, incluindo upload através de proxies
  Vite/HTTPS, ausência de Fetch Metadata, origens externas e headers de encaminhamento
  forjados. O teste de upload com banco também verifica a restrição ao Super Administrador.
- `tests/test_front_legal_proxy.mjs`: aprovado com o proxy HTTP real do Vite, verificando
  preservação de Host/Origin, header CSRF e corpo multipart do documento.
- `tests/test_front_resgate_recuperacao.mjs`, `test_front_multiplas_reservas.mjs` e
  `test_front_resgate_foto.mjs`: três suítes de regressão do fluxo existente, aprovadas.
- `test_resgate_confirmation.py`, `test_resgate_startup.py` e `test_http_protection.py`:
  30 testes existentes aprovados, incluindo o `init_db` completo e repetido.
- `tests/test_browser_legal_documents.mjs`: ensaio opt-in com a interface compilada e
  o servidor `tests/legal_e2e_server.py`, APIs reais e schema descartável, sem workers;
  aprovado em Chromium/Edge, incluindo o bloqueio do administrador comum na rota/menu/API.

O teste de backend é habilitado por `RUN_LEGAL_POSTGRES_TESTS=1` somente no Docker local
`db`, com dependências de teste instaladas. Executar:

```sh
python -m unittest discover -s tests -p test_legal_documents.py -v
```

O servidor de browser deve usar exclusivamente a porta local 8137 e `PYTHONPATH`
incluindo a raiz e `tests`. Encerrar por SIGTERM para remover o schema. Nenhuma rota
`/__test/*` é incluída em `app/main.py`.

## Arquivos da entrega

Criados:

- `app/models/legal.py`, `app/db/legal_migration.py`, `app/core/legal_protection.py`;
- `app/services/legal.py`, `app/services/legal_uploads.py`, `app/routers/legal.py`;
- `frontend/src/views/AdminLegalView.vue`, `LegalDocumentView.vue`, `LegalConfirmationView.vue`;
- `frontend/src/components/DocumentPreview.vue`, `LegalConsent.vue`, `LegalFooterLinks.vue`, `RecordPager.vue`;
- `frontend/src/assets/css/components/documents.css`;
- `tests/test_legal_documents.py`, `tests/legal_e2e_server.py`, `tests/test_browser_legal_documents.mjs`;
- `tests/test_legal_origin.py`, `tests/test_front_legal_proxy.mjs`;
- `docs/documentos_legais.md`.

Modificados:

- `app/main.py`, `app/db/session.py`, `app/core/http_protection.py`, `app/routers/resgate.py`;
- `app/services/email_queue.py`, `app/services/email_service.py`, `requirements.txt`;
- `frontend/src/router/index.js`, `frontend/src/App.vue`, `frontend/src/components/Navbar.vue`;
- `frontend/src/views/ResgateView.vue`, `frontend/src/assets/main.css`;
- `frontend/vite.config.js` (preservação de Host no proxy da API);
- `tests/test_front_resgate_recuperacao.mjs` (fixture de controles desativados).

Novas views/componentes não têm CSS scoped. Reutilizam modais, confirmação, KPIs,
autenticação, tabelas, botões e paginação globais. O novo CSS contém contratos genéricos
para documentos, escolhas e layout, sem cores hardcoded ou `!important`.
