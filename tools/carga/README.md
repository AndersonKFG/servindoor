# Teste de carga do Serv indoor: passo a passo

O gerador roda no **Ubuntu/WSL do seu computador**. O destino é o site da VPS,
passando pela Cloudflare. Não execute o gerador na VPS: ele consumiria os recursos
que queremos medir. Hoje o site ainda não foi divulgado; execute antes da abertura
ao público e acompanhe a VPS em outro terminal.

## 1. Primeiro teste: somente 10 visitantes

No Ubuntu/WSL do computador, dentro da pasta do projeto:

```bash
cd /home/anderson/Projetos/festa_servidor
bash tools/carga/executar.sh
```

Responda às perguntas:

| Pergunta | Resposta no primeiro teste |
| --- | --- |
| Endereço | Enter para `https://www.servindoor.com.br` |
| Modo | Enter para `home` |
| Máximo | Enter para `10` |
| PIN | O PIN atual do site; ele não aparece ao digitar |
| Confirmação | `TESTAR` |

O Docker prepara o k6 1.3.0 com a extensão comunitária SSE 0.1.11 na primeira
execução (pode levar alguns minutos) e reutiliza esse binário depois. É necessário
ter Docker funcionando no WSL, como já acontece com o ambiente de desenvolvimento.
O acompanhamento do gerador usa também o Python 3 disponível no Ubuntu.
Não há instalação de ferramenta na VPS para executar o gerador.

O primeiro teste dura aproximadamente 3 minutos, além do download e da preparação.
Ele consulta o acesso, verifica o PIN uma única vez, carrega o HTML da home e mantém
o SSE aberto por visitas de aproximadamente 90–110 segundos. Cada visitante usa uma
identificação própria e reconecta entre visitas. **Não chama `live-status`.**

O PIN é validado uma vez e a autorização é compartilhada com os visitantes
sintéticos: a carga do próprio formulário do PIN não é avaliada neste roteiro.

`Ctrl+C` interrompe. Um percentual de falhas superior aos limites configurados
também interrompe o teste depois de 30 segundos. Essa proteção mede requisições;
não substitui acompanhar CPU, memória e saúde do servidor.

## 2. Acompanhar a VPS

Em outro terminal conectado à VPS:

```bash
cd ~/servindoor
docker stats festa_web festa_db
```

Este comando mostra consumo de CPU e memória em tempo real. `Ctrl+C` fecha apenas
o monitor. Para consultar os erros depois:

```bash
docker compose logs --tail=100 web
```

Acompanhe também o computador gerador: se ele ou sua conexão saturar, o resultado
não prova que a VPS chegou ao limite. Muitos acessos vindos de um único IP podem
ativar proteções da Cloudflare; o mecanismo temporário abaixo só atua no aplicativo.
Não invente IPs usando `X-Forwarded-For`/`CF-Connecting-IP`, nem desligue todas as
proteções da Cloudflare. Se houver bloqueio, identifique a regra/evento antes de
definir uma exceção temporária restrita ao IP do gerador.

## 3. Home até 4.000; reservas até 2.000

Depois de analisar o resultado de 10 visitantes, execute o mesmo comando e escolha
`100`, depois `500`, `1000`, `2000`, `3000` e `4000`, conforme os resultados.
Essa sequência completa vale para o modo `home`. No modo `reservas`, o máximo
permitido é `2000`: avance por `10`, `100`, `500`, `1000` e `2000`.

Para máximos de 500 ou mais, a execução sobe direto até 500 e depois passa por
1.000, 2.000, 3.000 e 4.000, até o máximo escolhido. Cada subida dura 1 minuto,
cada patamar permanece por 2 minutos e a saída dura 30 segundos. Até 2.000 são
9min30s; até 4.000, 15min30s. Os testes pequenos de 10 e 100 mantêm suas etapas.
Não existe promessa de que todos os patamares serão alcançados: erros podem parar
o teste antes. Os visitantes chegam gradualmente; este roteiro não simula 4.000
pessoas clicando exatamente no mesmo instante.

## 4. Onde fica o resultado?

No computador gerador:

```text
tools/carga/resultados/IDENTIFICACAO_DO_TESTE/
  resumo.json
  metricas.json
  execucao.log
  gerador.jsonl
```

Envie o `resumo.json` para análise. `metricas.json` contém a evolução das métricas
por tempo e pode crescer bastante. Esses arquivos são ignorados pelo Git.
`execucao.log` guarda a saída do gerador, incluindo os diagnósticos de falhas.
`gerador.jsonl` acompanha CPU/memória/PIDs pelo Docker, memória e swap do WSL,
arquivos abertos do k6 quando acessíveis e contagens de sockets web por estado.
São amostras durante o teste; a memória do WSL inclui outros processos locais.
Os sockets são lidos no namespace de rede do gerador, compartilhado com o host
do Docker por `--network host`, e também podem incluir outros processos.
O monitor não lê ambiente, argumentos, payloads ou
credenciais, e não altera limites do sistema.

| Informação | Como interpretar |
| --- | --- |
| `limite_planejado` | Máximo escolhido, não é prova de capacidade |
| `vus_max_observado` | Visitantes virtuais em execução, incluindo quem ainda espera conexão |
| `conexoes_abertas_acumuladas` | Total de aberturas, incluindo reconexões; não é simultaneidade |
| `estados_recebidos_acumulados` | Total de snapshots SSE recebidos |
| `falhas_sse` | Proporção de visitas SSE malsucedidas; idealmente zero |
| `falhas_home` | Proporção das GETs iniciais à `/` que não responderam HTTP 200 |
| `home_total_p95_ms` | Tempo total p95 da GET inicial, incluindo abertura de conexão |
| `sse_estado_p95_ms` | 95% dos snapshots chegaram em até esse tempo |
| `verificacoes_ok` | Proporção das verificações que passaram |
| `continuidade_reserva` | No modo reservas, deve ser 1: mesmo token e expiração após F5 |
| `token_preservado_apos_f5` | O POST repetido retorna o mesmo token; deve ser 1 |
| `prazo_preservado_no_sse` | O SSE entrega prazo válido e mantém a expiração após F5; deve ser 1 |
| `desistencia_confirmada` | A desistência confirma sucesso e o SSE fica sem token e prazo; deve ser 1 |
| `reservas_aceitas_acumuladas` | Visitas que conseguiram criar ou recuperar uma reserva; não é ocupação simultânea |
| `sem_vaga_em_preenchimento_acumuladas` | Recusas esperadas porque as vagas estão reservadas |
| `sem_vaga_esgotado_acumuladas` | Recusas esperadas porque os ingressos já foram resgatados |
| `falhas_tecnicas_reserva` | Proporção de tentativas iniciais com erro inesperado, como HTTP 429/500 |

O alvo inicial é receber 95% dos snapshots em até 3 segundos. É um critério de
avaliação inicial, não uma capacidade previamente comprovada.

O tempo HTTP de um SSE inclui a duração de toda a conexão: **90 segundos em
`http_req_duration` do stream não significam que o site levou 90 segundos para
responder**. Use `sse_estado_ms` e `sse_abertura_ms` para avaliar a abertura.

### Se o teste parar com timeout

As linhas `[diagnostico_home]` de `execucao.log` mostram o horário UTC, o código
de erro do k6, o IP remoto quando disponível, o protocolo, o identificador
Cloudflare quando recebido e os tempos da requisição. A primeira visita do VU 1
também gera uma linha para referência, mesmo se responder HTTP 200. Não são
registrados cabeçalhos de autenticação, cookies, corpos de resposta, PIN ou chave.

Status `0` significa que não houve uma resposta HTTP utilizável; não é um erro
HTTP 500 da aplicação. Tempos zerados de uma tentativa interrompida não provam
sozinhos em qual etapa ela travou. Compare o código/mensagem do erro e o horário
com os logs do servidor. Este diagnóstico mantém os timeouts e critérios de
interrupção do roteiro.

### Comparar HTTP/2 com HTTP/1.1

Os acessos normais negociam o protocolo automaticamente. A extensão SSE 0.1.11
usa HTTP/1.1. Se os timeouts afetarem as GETs iniciais e os SSE permanecerem
rápidos, uma comparação possível é repetir a mesma carga forçando HTTP/1.1 no
gerador:

```bash
LOAD_HTTP1=1 bash tools/carga/executar.sh
```

Mantenha endereço, modo e máximo iguais aos da execução anterior. Esta opção
configura `GODEBUG=http2client=0` somente no processo do k6; o aplicativo, o Nginx
e a Cloudflare continuam com a mesma configuração. Timeouts, etapas e limites
de falha também permanecem iguais. O resumo identifica `http1_forcado: true` e
a linha de referência `[diagnostico_home]` deve mostrar `proto: "HTTP/1.1"`.

Se melhorar, há evidência de que o protocolo ou seu tratamento no caminho
influencia a falha; isso não identifica sozinho o responsável nem comprova a
capacidade com HTTP/2. Se falhar igual, investigue DNS, abertura de conexões,
recursos/rede do gerador e o caminho até a VPS. Para voltar à negociação normal,
execute o comando habitual sem `LOAD_HTTP1=1`.

### Diagnóstico curto do gerador

Para investigar a falha antes de repetir toda a escada de patamares:

```bash
LOAD_PROFILE=diagnostico bash tools/carga/executar.sh
```

Escolha `home` e máximo `1000`. Esse perfil chega ao máximo em 1 minuto, mantém
por 2 minutos e sai em 30 segundos (aproximadamente 3min30s, além do setup).
Preserva os critérios de interrupção, os timeouts e as visitas SSE. Compare
execuções desse mesmo perfil ao alterar um fator por vez. A chegada é mais
rápida que no perfil normal, portanto seus resultados não são diretamente
equivalentes aos testes anteriores nem substituem a validação completa até
4.000. O perfil curto só aceita home e até 1.000 VUs. Sem a variável, o roteiro
continua usando a escada normal. Envie `gerador.jsonl` e `execucao.log` junto do
resumo para investigar falhas de conexão.

## 5. Segunda etapa: reservas e F5

Esta etapa altera o banco: cria reservas sintéticas, recupera-as simulando F5,
verifica o prazo pelo SSE e desiste delas ao fim da visita. **Não cadastra pessoas,
não envia fotos, não emite ingresso e não envia e-mails.** Esses fluxos precisam
de um roteiro posterior com dados fictícios e destino de e-mail controlado.

O token é conferido na resposta do POST de reserva. O SSE por fingerprint pode
retornar `minha_reserva_token: null`, pois a publicação desse token exige um
vínculo adicional no aplicativo. Isso não reprova o prazo: o teste continua
exigindo expiração numérica, tempo restante entre zero e cinco minutos e a mesma
expiração após F5. Se o SSE publicar um token, ele deve coincidir com o POST.
As linhas `[diagnostico_reserva]` identificam a etapa que falhou sem registrar
tokens ou cookies. A desistência só passa quando o prazo também desaparece;
um token nulo sozinho não comprova a liberação.

As linhas com `etapa: "post_reservar"` registram a falha da criação inicial:
HTTP, código da API, código de transporte do k6, duração e identificador Cloudflare.
Não incluem CPF, token, corpo, cookies ou chave. Desistências com status zero
exatamente no aborto podem ser requisições canceladas pelo próprio gerador;
compare primeiro a falha inicial registrada antes da interrupção.

Antes, publique os ajustes do aplicativo na VPS, pois o limite temporário depende
do código novo:

```bash
cd ~/servindoor
git pull
docker compose up -d --build --no-deps --force-recreate web
```

No painel administrativo, crie um lote exclusivo chamado `TESTE DE CARGA`, aberto
agora, com **1.500 vagas** e sem inscrições reais, representando o primeiro lote.
Anote seu ID. Durante o teste, mantenha outros lotes pausados para a home não
anunciar o lote errado. As outras aberturas, com **1.000 e 500 vagas**, acontecem
em dias diferentes e podem ser representadas em execuções separadas.

O limite de **2.000 visitantes** dá uma margem de demanda sobre as 1.500 vagas
do primeiro lote. HTTP 400 com código `em_preenchimento` ou `esgotado` é uma recusa
esperada por lotação e aparece separadamente no resumo. HTTP 429, HTTP 500,
respostas inválidas e outros códigos continuam contando como falha técnica.
A métrica genérica `http_req_failed` do k6 também inclui esses HTTP 400 esperados;
use os contadores específicos e `falhas_tecnicas_reserva` para distinguir as causas.

Quem não consegue vaga acompanha o SSE por uma visita de aproximadamente 90–110
segundos antes de tentar novamente. Quem consegue verifica o F5 e desiste ao fim
da visita, liberando a vaga. Como a chegada é gradual e há liberação de vagas,
**não esperamos exatamente 1.500 reservas aceitas e 500 recusas**: os contadores
são acumulados ao longo do teste. Este cenário ainda não reproduz uma disputa
simultânea por todas as vagas na abertura nem o preenchimento do formulário.

O limitador normal permite 300 novas reservas por minuto por IP. Para simular
milhares de dispositivos saindo do mesmo computador, configure uma exceção
temporária na `.env` da VPS. Gere uma chave e um prazo com:

```bash
openssl rand -hex 32
date -u -d '+60 minutes' +'%Y-%m-%dT%H:%M:%S+00:00'
nano .env
```

Acrescente as três linhas, substituindo os textos indicados:

```dotenv
LOAD_TEST_SECRET=COLE_A_CHAVE_GERADA
LOAD_TEST_LOTE_ID=COLOQUE_O_ID_DO_LOTE_DE_TESTE
LOAD_TEST_UNTIL=COLE_O_PRAZO_GERADO
```

Salve (`Ctrl+O`, Enter) e saia (`Ctrl+X`). A aplicação lê a `.env` montada no
container ao iniciar; reinicie o serviço:

```bash
docker compose restart web
```

No WSL do computador, execute novamente `bash tools/carga/executar.sh`, escolha
`reservas`, comece com `10` e informe o ID do lote e a mesma chave secreta.
O gerador não grava PIN nem chave em seus arquivos de resultados. As variáveis
existem na memória/processo e no container durante a execução; trate a chave como
uma credencial e não compartilhe dumps de ambiente ou inspeções do container.

### O que a exceção faz?

O limitador continua executando a consulta e o registro no banco. Somente as
requisições com **chave correta + lote configurado + fingerprint `loadtest_` +
prazo válido** recebem um contador separado por visitante sintético. O IP real
continua salvo normalmente nas reservas. As demais requisições seguem o limite
original. As regras de horário, disponibilidade, concorrência e duração da
reserva não são ignoradas.

Sem as três configurações, com chave incorreta, prazo sem fuso, prazo expirado ou
prazo superior a duas horas a partir do horário atual, não existe exceção.
Isso mede o servidor com o limitador particionado; não comprova que milhares de
pessoas atrás de um mesmo IP seriam aceitas pela configuração normal.

### Ao terminar

Na `.env` da VPS, apague a chave e desative o lote permitido:

```dotenv
LOAD_TEST_SECRET=
LOAD_TEST_LOTE_ID=0
LOAD_TEST_UNTIL=
```

Depois:

```bash
docker compose restart web
```

Pause o lote de teste. As reservas sintéticas ficam no histórico identificadas
pelo prefixo `loadtest_`. As visitas concluídas desistem pela rota normal; ao
interromper o processo, algumas podem permanecer ativas até a expiração normal
de 5 minutos. Não é necessário apagar o banco inteiro.

## 6. Resgate com formulário, foto e confirmação repetida

Escolha o modo **`resgate`** no mesmo comando:

```bash
bash tools/carga/executar.sh
```

Este cenário inicia o máximo escolhido **diretamente**, sem passar pelos
patamares de 500 e 1.000. Cada VU executa um ciclo e termina. O limite de dez
minutos encerra visitantes que ficaram presos; o teste termina antes se todos
concluírem. O preenchimento é representado por uma pausa de 2–10 segundos.
Não é necessário esperar dez minutos se o ciclo levar apenas alguns segundos.

Além do lote exclusivo e da chave temporária, informe:

| Campo | Valor |
| --- | --- |
| Máximo | Até `2000` |
| Secretaria | ID de uma secretaria cadastrada e permitida no lote |
| E-mail | Uma única caixa controlada por você, apta a receber os testes |
| Autorização de e-mails | Digite `ENVIAR_EMAILS` para autorizar as mensagens reais |
| Confirmação final | `TESTAR` |

**Este modo grava usuários, solicitações pendentes e fotos, consome vagas e
enfileira e-mails reais.** O destino informado é usado em todos os formulários.
A fila poderá continuar enviando depois que o k6 terminar. Considere a cota do
provedor antes de autorizar até 2.000 mensagens. A consulta à API externa de
servidores é dispensada somente quando o aplicativo aceita a chave temporária,
o lote autorizado, o prazo e a identificação de teste; o teste não mede essa API.

Cada visitante:

1. Carrega a home, recebe o estado SSE e tenta reservar uma vaga.
2. Mantém uma conexão SSE aberta enquanto envia o formulário multipart com
   uma foto JPEG sintética de **320×240 e aproximadamente 69 KB**, sem pessoa real.
3. Usa um CPF matematicamente válido, determinístico para o teste. Cada décimo
   visitante reutiliza o CPF do anterior, com outro dispositivo.
4. Confere a confirmação pendente e repete o mesmo token, CPF e conteúdo,
   exigindo o mesmo protocolo e endereço de confirmação. A repetição não pode
   criar cadastro, foto ou e-mail adicional.
5. Se encontrar `cpf_ja_atendido`, libera a própria reserva e encerra seu ciclo.
   Quem encontra lotação também encerra. Esses dois resultados são esperados.

Uma falha de transporte/HTTP 5xx permite uma tentativa de recuperação com os
mesmos dados. A primeira falha continua contando na métrica; a recuperação não
esconde o erro. Não se envia desistência quando o resultado é incerto, pois o
servidor pode já ter concluído a gravação. Reservas restantes expiram normalmente.

### Como avaliar

O resumo acrescenta `formularios_enviados`, `resgates_confirmados`,
`cpf_ja_atendido`, `formulario_p95_ms`, `falhas_tecnicas_formulario`,
`confirmacao_idempotente` e `recuperacao_apos_falha`. A idempotência deve ser `1`.
Recuperação nula significa que não houve falha recuperável para avaliar.
Os critérios de tempo continuam em p95 menor que três segundos e falhas
técnicas abaixo de 1%; os critérios não foram afrouxados para aprovar a execução.

Com 1.500 vagas e 2.000 visitantes, o total confirmado nunca deve superar 1.500.
Não exija exatamente 500 recusas: CPFs repetidos podem liberar vagas durante a
disputa, e falhas precisam ser investigadas individualmente. O resumo HTTP precisa
ser confrontado com solicitações, usuários, contador do lote e arquivos na VPS.
Contar URLs de fotos no banco não comprova que os arquivos existem no disco.

Na VPS, depois que as requisições terminarem, confira o banco e os arquivos sem
baixar nada. Substitua a identificação, o ID do lote e o número confirmado:

```bash
docker compose exec web python tools/carga/conferir_resgates.py IDENTIFICACAO_DO_TESTE 1 --confirmados 1500
```

O script abre uma transação somente de leitura, limita consultas ao teste e
confere os arquivos vinculados dentro da pasta de fotos. Mostra contagens,
estados da fila e verificações, sem CPF, token ou e-mail. `consistente: true`
exige unicidade, fotos presentes com assinatura JPEG, tarefas e e-mails
registrados e ocupação dentro da capacidade. E-mail `sent` indica aceite do
SMTP, sem comprovar chegada à caixa. O script não procura arquivos órfãos e
não confirma a integridade visual de uma selfie.

Os cadastros recebem `setor = TESTE_CARGA_IDENTIFICACAO_DO_TESTE` e nome iniciado
por `TESTE CARGA`. Anote a identificação exibida para localizar esses registros.
Depois de conferir os resultados, limpe apenas os dados do teste e revogue a
autorização temporária. Este roteiro não executa limpeza automática no banco.

## Investigar espera no banco durante reservas

Na VPS, abra outro terminal e inicie a coleta antes da carga:

```bash
cd ~/servindoor
bash tools/carga/monitorar_banco.sh 180
```

Em seguida, execute o teste de reservas no terminal principal. O monitor coleta
a cada dois segundos durante três minutos e salva um CSV em
`tools/carga/resultados/banco_*.csv`. Ele executa somente consultas de diagnóstico;
registra PIDs, estados, tempos, categorias de operação e quais conexões bloqueiam
outras. Não exporta SQL bruto, parâmetros, CPF, tokens ou credenciais.
`consulta_ms` inclui tempo de espera; em uma conexão ociosa em transação, é o tempo
desde o início da última consulta, não uma medida da duração daquela consulta.
As amostras podem perder bloqueios curtos entre coletas. Não representam toda a
latência HTTP, a fila do pool na aplicação nem o uso de CPU do servidor.

Para copiar um resumo pelo console, sem baixar o CSV, aguarde a coleta terminar:

```bash
python3 tools/carga/resumir_banco.py
```

O comando lê o CSV mais recente e mostra estados, esperas e até cinco cadeias de
bloqueadores. Para escolher outra coleta, passe o caminho do CSV como argumento.
O resumo é uma seleção das amostras; o arquivo original continua disponível.

## Limites deste roteiro

- Não executa 4.000 navegadores completos: carrega HTML e simula o protocolo/API.
  Não mede renderização Vue, câmera, CSS, fontes, imagens ou Web Analytics.
- Uma conexão SSE aberta não basta: confira se ela recebe estado/eventos no tempo
  esperado, quantos visitantes chegam ao patamar e o consumo do servidor.
- O resumo agregado pode esconder piora em um patamar; use as métricas por tempo.
- `home` e `reservas` não enviam fotos ou formulários. `resgate` cobre upload,
  gravação do cadastro pendente e repetição da confirmação; não cobre aprovação,
  PDF do ingresso, entrega SMTP, câmera ou expiração completa. Nenhum resumo HTTP
  sozinho comprova os arquivos salvos ou a consistência do banco.
- Não lê ou altera configurações da Cloudflare. Um único IP não representa a
  distribuição de milhares de visitantes em diferentes redes.

Referências: [instalação do k6](https://grafana.com/docs/k6/latest/set-up/install-k6/),
[extensões](https://grafana.com/docs/k6/latest/extensions/explore/) e
[API da extensão SSE](https://github.com/phymbert/xk6-sse).
