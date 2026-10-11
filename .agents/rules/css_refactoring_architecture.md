# Diretrizes e Invariantes de Refatoração de CSS e Design System

## 1. Proibição de Automações Cegas
- É estritamente proibido o uso de scripts de busca e substituição cega (`sed`, scripts python de regex semântico ou replaces massivos) para alterar templates e blocos de estilo em componentes `.vue`.
- Toda refatoração deve ser estruturada, consciente e manual, garantindo compreensão integral da hierarquia do componente.

## 2. Princípio da Separação Sistêmica (Global vs. Local)
Para cada elemento da tela, aplicar rigorosamente a cadeia de decisão:
1. *O elemento é de natureza estritamente única desta tela (regra de negócio ou animação exclusiva)?*
   - **Se SIM:** Pode residir no `<style scoped>` local.
   - **Se NÃO:** É **obrigatório** utilizar ou enriquecer o contrato canônico no Design System global (`frontend/src/assets/css/components/*`), com nomenclatura agnóstica BEM projetada para atender qualquer tela do sistema.

## 3. Orçamento e Limites de `<style scoped>`
- Views e componentes refatorados devem ter um orçamento de `<style scoped>` estritamente mínimo (idealmente 0, com teto de até ~50 linhas apenas para peculiaridades inevitáveis).
- É **proibido** o uso de `!important` em arquivos `.vue` refatorados.
- É **proibido** o uso de cores `#hex` hardcoded no `<style scoped>`. Todas as cores, espaçamentos e raios devem utilizar variáveis semânticas do design system (`var(--bg-card)`, `var(--primary-accent)`, `var(--border-glass)`, etc.).

## 4. Contratos Globais Mandatórios
- **Tabelas:** Utilizar a família `.table-card`, `.table-header-box`, `.custom-table`, `.table-avatar`, `.table-user-cell`, `.table-code-pill`, `.table-tag`, `.table-status-cell`, `.table-actions-cell`.
- **Botões de Ação:** Botões operacionais em tabelas e listas devem utilizar `.btn-action-icon` com variantes semânticas (`--cyan`, `--blue`, `--emerald`, `--amber`, `--danger`).
- **Paginação:** Utilizar exclusivamente `.pagination-footer`, `.pagination-info`, `.btn-page-nav`, `.btn-page-number` (de `pagination.css`).
- **Formulários e Filtros:** Inputs e selects devem manter 44px de altura, chevron SVG ciano padronizado e containers `.filter-card`, `.filter-grid`, `.search-box`.
- **Modais:** Conteúdos de modais devem estruturar-se com `.modal-hero-card`, `.modal-section`, `.modal-info-grid`, `.modal-field-card` e `.modal-footer-grid`.
- **Tipografia:** Títulos principais de páginas administrativas devem utilizar a fonte Quattrocento (`font-family: var(--font-serif); font-weight: 700;` ou classes `.page-title.font-quattrocento`, `.admin-title`).

## 5. Invariante de Preservação Funcional
- É terminantemente proibido remover, renomear ou quebrar elementos HTML existentes, diretivas (`v-if`, `v-for`, `v-model`), manipuladores de evento (`@click`, `@submit`), campos de formulário, modais, refs, computeds ou chamadas de API.
- Todo arquivo refatorado deve passar por `npm run build` com zero erros antes da entrega.
