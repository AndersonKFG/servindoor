# Relatório de riscos de composição do front-end

**Data:** 11/10/2026  
**Escopo:** auditoria estática dos templates Vue, estilos scoped, estilos inline e folhas CSS globais em `frontend/src`.  
**Alterações de produto:** nenhuma. Este documento registra achados e recomendações; não altera telas.

## Síntese

Há causas concretas para diferenças de espaçamento, cabeçalhos, filtros, textos e controles entre telas. A mais visível nos exemplos enviados é estrutural: as views de validações e cancelamentos juntam `admin-page` e `app-container` no mesmo elemento, enquanto outras telas usam containers aninhados. O shorthand `padding` de `.app-container`, declarado depois do módulo de tipografia, sobrescreve o padding vertical de `.admin-page` nesse formato combinado.

Também há regras canônicas duplicadas entre os módulos CSS e o legado que continua no final de `main.css`, valores de tokens usados sem definição, e estilos inline que vencem as regras responsivas. Isso torna o resultado dependente da ordem e do formato específico de cada view.

## Achados prioritários

### P1 — Containers administrativos combinam responsabilidades no mesmo elemento

- [AdminValidacoesView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminValidacoesView.vue:345) e [AdminCancelamentosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminCancelamentosView.vue:243) usam `<div class="admin-page app-container">`.
- As demais views administrativas principais, como [AdminParticipantesView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminParticipantesView.vue:554) e [AdminView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminView.vue:476), aninham `.app-container` dentro de `.admin-page`.
- `.admin-page` define padding vertical em [typography.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/typography.css:126). `.app-container` define `padding: 0 28px` em [main.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/main.css:144). No elemento combinado, o shorthand posterior do container zera o padding vertical. Isso explica o cabeçalho de Validações começar muito próximo da navegação, enquanto Participantes mantém mais respiro.

**Recomendação:** padronizar a hierarquia em todas as views: `.admin-page` como wrapper externo e `.app-container` como filho. Manter uma única regra para cada responsabilidade.

### P1 — Estilos inline anulam o comportamento responsivo dos filtros

- [AdminUsuariosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminUsuariosView.vue:449) fixa três colunas com `style="grid-template-columns: 2fr 1fr 1fr"`.
- [EntregaPremiosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/EntregaPremiosView.vue:480) e [AdminSorteiosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminSorteiosView.vue:1132) fixam duas colunas inline.
- [AdminValidacoesView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminValidacoesView.vue:428) também define o grid inline dinamicamente.
- O CSS de `.filter-grid` em [forms.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/forms.css:134) tenta reduzir as colunas em telas menores, mas a declaração inline tem prioridade sobre as regras de media query. Em celulares, filtros podem permanecer apertados lado a lado.

**Recomendação:** transformar as variações em modificadores de classe e media queries; reservar `:style` para valores realmente calculados, como progresso ou visibilidade dinâmica.

### P1 — Contratos do Design System competem com regras legadas

`main.css` importa os módulos CSS no início e mantém definições antigas depois deles. Alguns contratos ainda duplicados:

| Contrato | Definições concorrentes | Efeito observado no código |
| --- | --- | --- |
| Botões primário e secundário | `components/buttons.css` e `main.css:372–420` | Cores, fundos, bordas e hover dependem da última regra, e o visual declarado no módulo pode não ser o visual renderizado. |
| Inputs e selects | `components/forms.css` e `main.css:504–523` | O shorthand `background:` posterior em `.form-control, .form-select` limpa o `background-image` do chevron SVG definido no módulo. Altura 44px sobrevive hoje porque o legado não redefine `height`, mas padding, fonte e foco divergem. |
| Modais | `components/modals.css` e `main.css:540–590` | Há diferenças em `z-index`, `max-height`, `overflow`, raio e animação; o legado vence pela ordem. Isso pode mudar corte e rolagem de conteúdo entre versões do shell. |
| Filtros | `components/forms.css:119–129` e `components/cards.css:33–42` | Radius, alpha do fundo e margem inferior têm valores diferentes. A ordem dos imports escolhe o resultado. |
| Títulos de seção | `typography.css:92–99` e `forms.css:574–582` | O mesmo `.section-title` recebe tamanhos e decoração diferentes; o módulo de formulários adiciona borda inferior globalmente. |

**Recomendação:** definir um único proprietário CSS para cada contrato. Manter regras específicas de tela apenas para comportamento exclusivo, sem deixar definições antigas concorrentes depois dos módulos.

### P1 — Tokens inexistentes invalidam declarações inteiras

Usos sem definição nem fallback foram encontrados para:

- `--text-secondary`: [sorteios.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/sorteios.css:198), [modals.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/modals.css:378) e scoped de [AdminParticipantesView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminParticipantesView.vue:1672).
- `--text-light`: [sorteios.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/sorteios.css:96), [forms.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/forms.css:321) e [modals.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/modals.css:427).
- `--white`: [cards.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/cards.css:369).
- `--primary-color`: [pagination.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/components/pagination.css:59), no fundo do número de página ativo.

Quando `var()` não resolve, a declaração CSS que o contém é inválida. Assim, partes de textos, estados ou fundos podem cair para a cor herdada/fundo padrão sem erro de build.

**Recomendação:** validar tokens referenciados contra `tokens.css` e exigir fallback ou token semântico existente.

### P1 — Fontes de título têm especificidade equivalente e ordem conflitante

- `.font-quattrocento` é definido antes de `.section-title` em [typography.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/typography.css:28) e [typography.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/typography.css:92).
- O título de seção da página de entregas usa `class="section-title font-quattrocento"` em [EntregaPremiosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/EntregaPremiosView.vue:471). Como as classes têm especificidade igual e `.section-title` vem depois, a fonte Outfit prevalece sobre Quattrocento.
- `AdminView.vue` também declara localmente `.admin-header-row` e `.admin-subtitle` em [AdminView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminView.vue:1170), com gap, margem e tamanho de texto distintos dos contratos globais. Entregas cria `.page-header-row` local com estrutura similar em [EntregaPremiosView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/EntregaPremiosView.vue:708).

**Recomendação:** reservar Quattrocento para os títulos previstos no contrato, aumentar a prioridade das classes de tipografia semântica ou evitar combinar classes com declarações conflitantes; consolidar cabeçalho/subtítulo global.

### P2 — Os exemplos de cabeçalho usam marcadores diferentes

Validações e Cancelamentos usam `.badge-cyber`; Participantes usa `.badge-subtle-primary`; Entregas usa `.vip-badge.bg-warning`; AdminView não tem marcador equivalente. Os títulos principais usam `.page-title`, mas a faixa que antecede o título tem sistemas visuais diferentes. Isso explica a diferença entre as duas imagens sem indicar falha de carregamento de fonte.

**Recomendação:** se a intenção é que páginas administrativas tenham o mesmo cabeçalho, criar um componente ou contrato único para etiqueta, título, subtítulo e ações. Se a variação for deliberada, documentar modificadores semânticos e manter o mesmo espaçamento-base.

### P2 — Regras locais e utilitários de margem disputam espaçamento

- `.admin-header-row` global usa `margin-bottom: 24px`, mas AdminView declara 28px localmente; outras views adicionam `mb-4`.
- As margens utilitárias em [utilities.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/utilities.css:36) usam `!important`, podendo vencer regras de componentes mesmo quando o seletor local é mais específico.
- `.table-card + .table-card` só cria margem quando dois cards são irmãos adjacentes. Quando há texto, alerta ou wrapper entre eles, a regra não se aplica; algumas telas dependem de classes como `mt-5` para corrigir isso.

**Recomendação:** usar tokens de espaçamento e contratos de seção/container em vez de somar margem no template com estilos locais e seletores de adjacência.

### P2 — Cores inline e `text-white` prejudicam consistência e tema claro

- [SucessoView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/SucessoView.vue:152) define cor, fundo e borda do badge diretamente no atributo `style`.
- [MeuIngressoView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/MeuIngressoView.vue:750) ainda tem hexadecimal no scoped.
- O utilitário `.text-white` em [utilities.css](/home/anderson/Projetos/festa_servidor/frontend/src/assets/css/utilities.css:88) força branco com `!important`; usos em títulos e componentes continuam brancos no tema claro, mesmo quando os tokens semânticos deveriam trocar a cor.

**Recomendação:** substituir cores de estado por variantes globais semânticas e revisar usos de `text-white` em superfícies que suportam tema claro.

### P2 — Há texto corrompido no painel de lotes

[AdminView.vue](/home/anderson/Projetos/festa_servidor/frontend/src/views/AdminView.vue:516) contém `Taxa de Ocupa??o`. O texto também aparece assim na captura de tela; isso é conteúdo literal incorreto, não falha de fonte.

## Inventário de escopo e riscos menores

- Os blocos `<style scoped>` das views estão hoje curtos; a auditoria contou poucos seletores por view e não encontrou `!important` nesses blocos. Isso é positivo em relação ao orçamento local do projeto.
- Há estilos inline usados corretamente para valores dinâmicos (`width` de progresso, duração de toast, `z-index`, visibilidade), misturados com estilos estruturais fixos. Os fixos devem migrar para classes para preservar responsividade e facilitar revisão.
- `AdminValidacoesView` e `AdminCancelamentosView` compartilham o mesmo problema de container; `AdminUsuariosView`, `AdminSorteiosView`, `AdminParticipantesView` e `AdminView` usam wrappers aninhados.
- Os controles de câmera, tabela, cards, filtros e modais usam várias famílias de classes legadas e novas. Mesmo quando não há erro atual, essa coexistência faz pequenas alterações de ordem/import mudar o resultado visual.

## Ordem recomendada de correção

1. Corrigir a estrutura dos wrappers `admin-page`/`app-container` nas views de Validações e Cancelamentos.
2. Remover grids estruturais inline que anulam media queries.
3. Resolver tokens sem definição e o chevron dos selects afetado pelo shorthand de background.
4. Definir uma única fonte de verdade para botões, inputs, filtros, tabelas e modais; eliminar duplicatas do legado após validação visual.
5. Unificar o contrato dos cabeçalhos administrativos e resolver a precedência de `.font-quattrocento`/`.section-title`.
6. Revisar cores hardcoded, tema claro, textos corrompidos e espaçamentos utilitários.

## Limites desta auditoria

Esta é uma análise estática dos arquivos e da cascata; não fiz inspeção visual automatizada em todos os tamanhos de viewport nem alterei código de produto. Os achados apontam causas verificáveis e riscos prováveis, mas cada correção visual deve ser conferida nas rotas afetadas em desktop e celular.
