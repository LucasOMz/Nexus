# PLANO — Multi-planta (multi-tenant por linha)

Decisões confirmadas pelo usuário:

| Ponto | Decisão |
|---|---|
| Arquitetura | **Um banco, com `planta_id` nas tabelas** (isolamento por linha) |
| Acesso do usuário | **Uma planta principal + outras liberadas** (N:N) |
| Visão consolidada | **Sim** — o admin precisa ver o total da empresa |

---

## 1. MODELO DE DADOS

### Tabelas novas

**`plantas`** — cadastro das unidades

| Campo | Tipo | Observação |
|---|---|---|
| id | PK | |
| nome | String(160) | "Planta Matriz", "Unidade Campinas" |
| sigla | String(20) único | aparece na coluna da tela de Ativos (ex.: `MAT`, `CPS`) |
| cnpj | String(18) | opcional |
| endereco, cidade, uf | String | opcional |
| ativa | Boolean | inativa sai dos seletores, mas mantém o histórico |
| padrao | Boolean | planta usada quando o usuário não escolheu nenhuma |

**`usuario_plantas`** — quais plantas cada usuário acessa (N:N)

| Campo | Tipo |
|---|---|
| usuario_id | FK usuarios |
| planta_id | FK plantas |
| principal | Boolean (a planta que abre por padrão) |

> Regra: **administrador acessa todas** as plantas ativas, sempre
> (`isAdmin` já ignora a lista de módulos; a mesma lógica vale aqui).

### Colunas novas

**`usuarios`**: `planta_principal_id` FK plantas (nulo = definida por `usuario_plantas`).

**`planta_id`** (FK plantas, indexado) nas tabelas de **inventário**:

```
ativos, produtos, movimentacoes, manutencoes,
departamentos, localizacoes, fornecedores, categorias,
imagens, qr_zerados, dispositivos_impressao
```

**Ficam GLOBAIS** (não têm planta):
`usuarios`, `plantas`, `usuario_plantas`, `configuracoes`, `logs_auditoria`
(recebe `planta_id` só para relatório), `filtros_salvos`, `templates_etiqueta`.

**Herdam a planta do pai** (não precisam de coluna própria):
`ativos_ti`, `ativos_impressora`, `leituras_contador`, `suprimentos_impressora`,
`termos`, `anexos` — todos chegam pelo ativo/manutenção.

### Migração dos dados existentes

1. Criar a planta **"Matriz"** (`sigla = MAT`, `padrao = true`).
2. Preencher `planta_id` de **todo registro existente** com ela.
3. Vincular o admin atual à Matriz como principal.
4. Tornar `planta_id` obrigatório (`NOT NULL`) só depois do preenchimento.

O `database.py` já adiciona colunas novas sozinho; o preenchimento e o
`NOT NULL` entram num passo de migração explícito.

---

## 2. COMO A PLANTA ATIVA É RESOLVIDA

**Cabeçalho `X-Planta-Id`** nas requisições (o frontend manda o que o usuário
escolheu). Regras, em `app/core/deps.py`:

```
1. Admin            → qualquer planta (ou "todas", para o consolidado)
2. Usuário comum    → apenas as plantas de `usuario_plantas`
3. Sem cabeçalho    → usa a planta principal do usuário
4. Planta inválida  → 403 com mensagem clara
```

Uma dependência `planta_ativa` devolve a planta resolvida; **todo router de
inventário** a usa como filtro obrigatório. Centralizar aqui é o que evita
vazamento entre plantas — nenhuma consulta monta o filtro na mão.

Para o **consolidado**, `X-Planta-Id: todas` (só admin): as consultas somam
todas as plantas permitidas.

---

## 3. IMPACTO POR ARQUIVO

| Arquivo | Mudança |
|---|---|
| `app/models/core.py` | `Planta`, `UsuarioPlanta`; `planta_id` nas 11 tabelas; `Usuario.planta_principal_id` |
| `app/models/__init__.py` | exportar os novos modelos |
| `app/core/deps.py` | `planta_ativa`, `plantas_do_usuario`, `require_planta` |
| `app/routers/plantas.py` | **novo** — CRUD de plantas (admin) |
| `app/routers/*.py` (11) | aplicar o filtro de planta em listar/criar/editar/excluir |
| `app/routers/scanner.py` | resolver o QR **dentro da planta ativa** |
| `app/services/backup_service.py` | backup/restauração por planta |
| `app/services/csv_service.py` | exportação por planta |
| `frontend/app.js` | seletor de planta no topo (só quando há mais de uma) |
| `frontend/js/state.js` | guardar a planta ativa + enviar `X-Planta-Id` |
| `frontend/js/api.js` | injetar o cabeçalho em toda requisição |
| `frontend/js/views/admin.js` | aba **Plantas** |
| `frontend/js/views/admin_usuarios` | planta principal + plantas liberadas |
| `frontend/js/views/ativos.js` | coluna **Planta** entre Patrimônio e Modelo |
| `frontend/js/views/relatorios.js` | opção "Todas as plantas" (admin) |

### Cuidados que valem ouro

- **QR Code**: o payload continua `TIATIVO:{id}`. Como o ID é único no banco
  inteiro, a etiqueta funciona em qualquer planta — mas a **leitura valida se o
  ativo pertence a uma planta que o usuário acessa**. Etiqueta de outra planta
  devolve mensagem explicando, em vez de "não encontrado".
- **Etiquetas em branco**: `qr_zerados` ganha `planta_id`; a leitura só aceita
  código gerado na planta ativa.
- **Patrimônio**: hoje é único global. Com multi-planta passa a ser único
  **por planta** (duas unidades podem ter `TI-001`). Isso muda o índice único.
- **Backup**: continua sendo do banco inteiro; o *export* por planta passa a
  existir para levar/entregar os dados de uma unidade.

---

## 4. FASES (cada uma termina com a suíte passando)

| Fase | Entrega | Verificação |
|---|---|---|
| **1** | Modelos `Planta`/`UsuarioPlanta`, `planta_id` nas tabelas, migração da Matriz | pytest + dados antigos preservados |
| **2** | `planta_ativa` em `deps.py`, CRUD de plantas, vínculo usuário↔planta | testes de permissão entre plantas |
| **3** | Filtro de planta nos 11 routers + scanner + patrimônio único por planta | teste que **prova o não-vazamento** entre plantas |
| **4** | Frontend: seletor no topo, coluna Planta, aba Plantas, plantas no usuário | 26 módulos + renderização real |
| **5** | Relatório consolidado "Todas as plantas" (admin) | teste do total somado |
| **6** | Exportação/backup por planta, README e `PROMPT.md` | verificação final |

---

## 5. ESTADO ATUAL

**Concluído nesta rodada:** remoção da tela **Dashboard** (conteúdo incorporado
a Relatórios, que virou a tela inicial do inventário). Suíte: **111 testes**,
26 módulos de frontend, lint limpo.

**Não iniciado:** as fases 1 a 6 acima.

**Por que não comecei:** é uma mudança que toca 12 tabelas, 11 routers e todo o
frontend. Começar e parar no meio deixaria o sistema pior do que está —
com plantas cadastradas mas dados não particionados, ou patrimônio duplicado
entre unidades. Cada fase acima termina com a suíte verde, então dá para parar
em qualquer ponto com segurança.
