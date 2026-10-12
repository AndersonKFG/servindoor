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

Cada execução passa por todos os patamares até o máximo escolhido, mantendo cada
patamar por 2 minutos. O roteiro completo até 4.000 dura aproximadamente 20min30s.
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
```

Envie o `resumo.json` para análise. `metricas.json` contém a evolução das métricas
por tempo e pode crescer bastante. Esses arquivos são ignorados pelo Git.
`execucao.log` guarda a saída do gerador, incluindo os diagnósticos de falhas.

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

## 5. Segunda etapa: reservas e F5

Esta etapa altera o banco: cria reservas sintéticas, recupera-as simulando F5,
verifica o prazo pelo SSE e desiste delas ao fim da visita. **Não cadastra pessoas,
não envia fotos, não emite ingresso e não envia e-mails.** Esses fluxos precisam
de um roteiro posterior com dados fictícios e destino de e-mail controlado.

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

## Limites deste roteiro

- Não executa 4.000 navegadores completos: carrega HTML e simula o protocolo/API.
  Não mede renderização Vue, câmera, CSS, fontes, imagens ou Web Analytics.
- Uma conexão SSE aberta não basta: confira se ela recebe estado/eventos no tempo
  esperado, quantos visitantes chegam ao patamar e o consumo do servidor.
- O resumo agregado pode esconder piora em um patamar; use as métricas por tempo.
- Não testa emissão de ingresso, entrega de e-mail, upload, expiração completa
  nem prova sozinho que a lotação jamais será excedida.
- Não lê ou altera configurações da Cloudflare. Um único IP não representa a
  distribuição de milhares de visitantes em diferentes redes.

Referências: [instalação do k6](https://grafana.com/docs/k6/latest/set-up/install-k6/),
[extensões](https://grafana.com/docs/k6/latest/extensions/explore/) e
[API da extensão SSE](https://github.com/phymbert/xk6-sse).
