# PROMPT DE CONTEXTO — Sistema de Gestão Patrimonial (Estoque + QR Code)

> Documento para retomar o projeto em outra sessão/IA sem perder contexto.
> Projeto em `C:\Users\Lucas\Desktop\DSH\estoque-qr`.

---

## 1. OBJETIVO DO SISTEMA

Sistema web de **gestão patrimonial** com dois inventários independentes
(**TI** e **Impressoras**), focado em:

- cadastro de ativos com **QR Code** impresso em impressora térmica;
- leitura por **leitor físico** de código (que digita como teclado);
- controle de estoque, movimentações, manutenções e consumíveis;
- relatórios com gráficos;
- **etiquetas QR em branco** (pré-impressas, cadastradas depois);
- backup/restauração e exportação CSV;
- autenticação **local ou via Active Directory (LDAP)** por grupo.

Requisito original: *"um sistema de estoque web completo, onde eu possa criar
qrcode e imprimir na impressora termica e colar no item"*.

---

## 2. STACK

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2 |
| Banco | SQLite (dev) / PostgreSQL 16 (produção, docker-compose) |
| Auth | JWT (PyJWT) + bcrypt + LDAP/AD (ldap3) |
| Impressão | ZPL (Zebra), TSPL (TSC/Elgin), PDF (reportlab), QR (qrcode) |
| Frontend | Vanilla ES6 modules, PWA (service worker), Material Design 3 |
| Infra | Docker + Nginx, Portainer, Windows Server |

**Sem frameworks de frontend, sem bibliotecas de gráfico** (SVG puro) e sem
biblioteca de câmera — a leitura é por leitor físico.

Tamanho: ~6.900 linhas de backend, ~4.600 de frontend, ~900 de testes.
**116 endpoints** em 17 módulos.

---

## 3. ESTRUTURA

```
estoque-qr/
├── app/
│   ├── main.py                 # FastAPI, CORS, CSP, headers, routers, static
│   ├── config.py               # Settings (pydantic-settings) + .env
│   ├── database.py             # engine/session + auto-upgrade de schema
│   ├── core/
│   │   ├── security.py         # bcrypt, JWT (com claim email), invalidar_tokens()
│   │   ├── deps.py             # get_current_user, require_admin/write/delete/module
│   │   ├── cripto.py           # Fernet (senha do LDAP cifrada)
│   │   ├── permissoes.py       # permissões efetivas por papel/usuário
│   │   ├── rate_limit.py       # janela deslizante (login e scan)
│   │   └── pagination.py
│   ├── models/                 # SQLAlchemy (22 tabelas)
│   ├── schemas/                # Pydantic v2 (mixin SemVazios)
│   ├── routers/                # 17 módulos de API
│   └── services/               # regras de negócio
├── frontend/                   # PWA (25 módulos ES)
├── tests/                      # 84 testes pytest + 4 verificadores Node
├── run.ps1 / run.bat           # uso manual (Windows)
├── run-servidor.ps1            # serviço (Agendador de Tarefas)
├── run.sh                      # Linux/macOS/Raspberry
├── reset.ps1 / reset.bat       # reset para começar do zero
├── publicar.ps1                # monta pacote para o servidor
├── docker-compose.yml / Dockerfile / nginx/
└── schema.sql                  # DDL de referência (PostgreSQL)
```

---

## 4. MODELO DE DADOS (22 tabelas)

**Núcleo:** `usuarios`, `ativos`, `departamentos`, `localizacoes`,
`fornecedores`, `categorias`, `imagens`, `logs_auditoria`, `filtros_salvos`

**Ativos:** `ativos_ti` e `ativos_impressora` (extensão **1:1** com `ativos` —
o inventário é definido na criação e **não pode ser trocado**)

**Operação:** `movimentacoes`, `manutencoes`, `anexos`, `termos`,
`produtos`, `leituras_contador`, `suprimentos_impressora`

**Configuração:** `dispositivos_impressao`, `templates_etiqueta`,
`configuracoes` (singleton id=1, guarda o LDAP), `qr_zerados`

### Decisões de modelagem

- Tipos **portáveis** (JSON em vez de JSONB, string para enums) para o mesmo
  código rodar em SQLite e PostgreSQL.
- `SoftDeleteModel` (deleted_at) + `CreatedAtModel`/`BaseModel` mixins.
- **Auto-upgrade de schema**: `create_all` cria tabelas novas e
  `_adicionar_colunas_faltantes` adiciona colunas novas — **evolui o sistema sem
  apagar o banco**.

---

## 5. FORMATO DO QR CODE

### Etiqueta de ativo (normal)
```
TIATIVO:{id}:{timestamp}:{hmac_base64url}
```
HMAC-SHA256 sobre `TIATIVO:{id}:{ts}`.

### Etiqueta em branco (sem dono)
```
TIZERADO:{codigo}:{timestamp}:{hmac_base64url}
```
`codigo` = 10 caracteres do alfabeto `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`
(**sem I, O, 0, 1** — para digitação manual).

### Regras de leitura (importantes)

1. O **ID dentro do payload sempre resolve** o ativo — etiquetas já impressas
   continuam válidas mesmo trocando o segredo.
2. A assinatura é conferida contra o segredo atual **e** contra
   `QR_HMAC_SECRETS_ANTERIORES` → trocar o segredo **não invalida etiquetas**.
3. `QR_EXIGIR_ASSINATURA=false` faz a assinatura divergente apenas ser
   **auditada**, sem bloquear.
4. Código em branco livre → `tipo="zerado"` (a tela abre o cadastro);
   já vinculado → resolve o ativo normalmente.

---

## 6. IMPRESSÃO — 3 MODOS (importante)

Cadastrados em **Administração → Impressão** (`dispositivos_impressao`):

| Tipo | Campos | Quando usar |
|---|---|---|
| **`compartilhamento`** | `compartilhamento = "\\\\DTAT7777\\SATO"` | **Fila compartilhada — funciona no Windows E no Linux** |
| `agente` | `agente_url` / `hostname` | Agente HTTP no Raspberry Pi (porta 9100) |
| `cups` | `fila_cups` | Servidor Linux com CUPS (`lp`) |

### Comportamento por sistema operacional (mesmo cadastro)

O **mesmo endereço** `\\DTAT7777\SATO` funciona nos dois:

| Sistema | Como envia |
|---|---|
| **Windows** | Grava os bytes crus no caminho UNC; o **spooler** entrega (datatype RAW) — igual a `copy /b etiqueta.zpl \\DTAT7777\SATO` |
| **Linux** | Envia pelo **`smbclient`** (protocolo de impressão SPOOLSS), porque no Linux **não existe** caminho UNC de impressora |

**Requisitos:**
1. Impressora **compartilhada** na máquina de origem, com permissão para a conta
   que roda o serviço.
2. **Linux:** pacote `smbclient` instalado (`apt install smbclient`).
   Credenciais opcionais via `PRINT_SMB_USUARIO` / `PRINT_SMB_SENHA`
   (em branco = tenta anônimo `-N`).
3. Formato **ZPL ou TSPL** — PDF é recusado com mensagem clara.

**Robustez implementada:** 3 tentativas, fallback `copy /b` no Windows, `copies`
repetindo o fluxo (era ignorado), mensagens que orientam a conferência, e erro
específico quando falta o `smbclient`.

**Alternativa Linux mais robusta:** fila do CUPS com URI
`smb://usuario:senha@DTAT7777/SATO` e tipo `cups`.

> Não testado contra impressora física nem contra um SMB real: o roteamento
> depende do spooler (Windows) ou do smbclient (Linux). O botão **Imprimir
> teste** valida no ambiente real. Os testes automatizados cobrem a montagem da
> linha de comando, o conteúdo enviado, cópias, credenciais e os erros.

---

## 7. FUNCIONALIDADES IMPLEMENTADAS

### Núcleo
- Auth JWT com refresh, rate limit, permissões por módulo/inventário
- CRUD de ativos (TI e Impressoras) com extensões por domínio
- Movimentações, manutenções com anexos, consumíveis com estoque mínimo
- Cadastros auxiliares (departamentos, locais, fornecedores, categorias)
- Dashboard com KPIs, gráficos SVG e relatórios (CSV/PDF)
- Termo de responsabilidade em PDF, leituras de contador
- PWA offline-first com fila no IndexedDB
- Banco de fotos, impressão térmica (3 modos acima)

### Recursos avançados

**a) Assinatura de QR configurável** — `QR_EXIGIR_ASSINATURA`,
`QR_HMAC_SECRETS_ANTERIORES`, auditoria de leitura sem assinatura.

**b) Login por AD/LDAP** — servidor, TLS, Base DN, conta de serviço (senha
**cifrada**), filtro, **grupo de acesso** (`YM_ESTOQUE_TI`), grupo de
administradores, provisão automática, grupos aninhados, testes de conexão e de
login. O **administrador local é a exceção** (não depende do AD).

**c) Etiquetas configuráveis** — templates em banco (mm, DPI, campos,
alinhamento, fonte, QR). **Uma única geometria** (`label_layout.py`) alimenta
ZPL, TSPL, PDF e a pré-visualização. Avisa quando o texto não cabe. Template
**por dispositivo**, teste de impressão e PDF.

**d) Backups** — listar/status/criar/baixar, **validar em banco temporário** e
**restaurar com travas** (senha + `RESTAURAR` + backup do estado atual +
invalidação de sessões + auditoria).

**e) CSV total** — ZIP por tabela usando nomes; importação **em simulação
primeiro**, com **remoção de duplicados** por chave natural.

**f) Etiquetas em branco** — gerar N sem dono, imprimir, colar e cadastrar na
leitura; lote em **um único trabalho**; reuso bloqueado.

---

## 8. BUGS ENCONTRADOS E CORRIGIDOS

| # | Sintoma | Causa raiz | Correção |
|---|---|---|---|
| 1 | `[object Object]` nos erros | Validação do FastAPI vem como **lista de objetos** | `erros.js` formata campo + motivo |
| 2 | Fornecedor com e-mail vazio recusado | `""` rejeitado por `EmailStr` | Mixin `SemVazios` em 19 schemas |
| 3 | **Editar ativo sempre falhava** | `AtivoUpdate` com `extra="forbid"` não aceitava `dominio`/`tipo_item` reenviados pelo form | Campos aceitos e ignorados |
| 4 | **Data de garantia dava 500** | `date`/`Decimal`/enum não são JSON; falha só no `commit`, fora do `try` | `json_safe()` recursivo |
| 5 | Nome duplicado dava 500 | Violação de unicidade | Handler: 409 com mensagem; 500 com log |
| 6 | **Texto preto no modo escuro** | `<button>` usa cor nativa `buttontext` | `color:inherit`, `color-scheme`, títulos em negrito |
| 7 | **Relatórios travando infinito** | SW: `skipWaiting`+`clients.claim` na 1ª instalação → reload → aborta instalação → **laço** | Só recarrega se já era controlada |
| 8 | Esqueleto eterno | `renderGraficos()` sem `.catch()` | try/catch + botão tentar novamente |
| 9 | API devolvendo dado velho | SW cacheava `/api/` | API nunca é cacheada |
| 10 | `python3.exe : Traceback` no `run.bat` | PS 5.1 trata stderr nativo como **erro fatal**; e escolhia Python 3.13 | Checagem relaxada + escolhe o Python que **importa** as deps |
| 11 | `run-servidor.ps1` subia e morria | **uvicorn loga no stderr** | `ErrorActionPreference="Continue"` |
| 12 | `.env` quebrava o sistema | `pydantic-settings` tentava JSON na lista de CORS | `Annotated[list[str], NoDecode]` |
| 13 | Acesso pelo IP não funcionava | `run.ps1` em `127.0.0.1` | Padrão `0.0.0.0`; `-Local` restringe |
| 14 | Verificação de firewall travava o boot | Consulta WMI por regra | Consultas em lote (~1 s) |
| 15 | Senha do LDAP em texto puro | Sem cifra | Fernet (chave do `JWT_SECRET`) |
| 16 | `copies` ignorado em fila compartilhada | Não repetia o fluxo | Repete os bytes N vezes |

**Bugs meus, assumidos:** `erros.js` escrito com sintaxe TypeScript (invalidaria
o app) — pego pelos testes; e arquivos corrompidos por scripts PowerShell sem
`-Encoding UTF8` (reparados; **nenhum arquivo da aplicação** afetado).

---

## 9. SEGURANÇA

- JWT com claim `email` — token recusado se o banco for restaurado e o ID mudar.
- `invalidar_tokens()` derruba todas as sessões.
- CSP `script-src 'self'` — **bloqueia script inline**.
- Senha da conta de serviço LDAP cifrada; nunca devolvida pela API.
- Rate limit em login e leitura; auditoria append-only com diff sanitizado.

⚠️ O sistema rodou com **segredos padrão públicos** até esta sessão. Foi criado
um `.env` com segredos fortes e o antigo em `QR_HMAC_SECRETS_ANTERIORES`,
preservando as etiquetas impressas.

---

## 10. COMO RODAR

```powershell
run.bat                     # Windows: já escuta na rede (0.0.0.0)
.\run.ps1 -Local            # restringe a este computador
.\run.ps1 -Port 9000
.\run.ps1 -Setup            # só prepara o .venv
./run.sh                    # Linux / macOS / Raspberry
```

Login inicial: `admin@empresa.com` / `admin123`

**Ordem de resolução do ambiente:** `.venv` → `.vendor` (escolhendo o Python que
**realmente importa** as dependências) → cria `.venv`.

### Servidor (Windows Server)

```powershell
.\run.ps1 -Setup
# agendar o run-servidor.ps1 (0.0.0.0, log em logs/, reinício automático)
New-NetFirewallRule -DisplayName "Gestao Patrimonial" -Direction Inbound `
    -Protocol TCP -LocalPort 8000 -Action Allow
```

### Portainer / Docker

`docker-compose.yml` com api + PostgreSQL 16 + nginx. **Exige** `JWT_SECRET` e
`QR_HMAC_SECRET`. Volumes `media` e `backups` obrigatórios. A imagem não traz
`pg_restore` — restaurar pela tela exige `postgresql-client`.
**Atenção:** em container Linux a impressão por fila compartilhada Windows **não
funciona** — use o agente.

### Levar para o servidor

```powershell
.\publicar.ps1              # completo (migrar: .env, banco, media)
.\publicar.ps1 -SemDados    # instalação limpa
```

**NÃO copiar** `.vendor` (145 MB, extensões compiladas presas à versão do Python)
nem `.venv`. **Copiar** `.env`, `estoque.db`, `media/`.

---

## 11. TESTES

```powershell
$env:PYTHONPATH = ".vendor"
python -m pytest                          # 84 testes
python -m ruff check app tests
node tests/check_frontend_modules.mjs     # 25 módulos
node tests/check_tema.mjs                 # 13 contraste
node tests/check_erros.mjs                # 15 mensagens
node tests/check_pwa.mjs                  # 7  service worker
```

Maiores: `test_qr_zerado.py` (14), `test_formularios_regressao.py` (13),
`test_auditoria.py` (11), `test_impressao_compartilhada.py` (8).

---

## 12. CONVENÇÕES

- **Comentários e mensagens em português**, explicando o *porquê*.
- Erro para o usuário deve dizer **o campo e o motivo**.
- Formulários enviam `""` — o backend normaliza com `SemVazios`.
- Nunca usar cor fixa no frontend: variável de tema.
- Ao mudar o frontend: aumentar `APP_VERSION` **e** `VERSION` do `sw.js` juntos
  (há teste que verifica sincronia).
- Dado de usuário nunca vai para o cache do service worker.
- Rate limit/blacklist são **em memória** — manter **1 worker** ou usar Redis.

---

## 13. LIMITAÇÕES / PENDÊNCIAS

1. **LDAP nunca testado contra AD real** — validados armazenamento, fluxo e erro.
2. **Restauração de backup** — validação testada; troca real não executada.
3. **Impressão física** — depende do ambiente; validar com "Imprimir teste".
4. **Não há tela para consultar a auditoria** (grava tudo, visível só no banco).
5. **Acesso pelo celular** não confirmado — o PC está correto (`0.0.0.0` +
   firewall); falta verificar mesma faixa (`192.168.7.x`) e isolamento de clientes.
6. **Criar compartilhamento SMB exigiu Administrador** nesta sessão, então o
   roteamento UNC até a impressora não foi testado ponta a ponta.

---

## 14. CONTEXTO DE QUEM USA

- Instituição pública; TI e Impressoras no mesmo sistema.
- Impressora: **Zebra ZQ521** (portátil), etiquetas 100×50 mm a 203 dpi.
- Vai rodar em **Windows Server**, com Agendador de Tarefas, e avalia
  **Portainer**; acesso pelo **IP do servidor**.
- Quer usar **fila compartilhada Windows** (ex.: `\\DTAT7777\SATO`) em vez de
  Raspberry.
- Login do AD planejado pelo grupo **`YM_ESTOQUE_TI`**.
- Administrador local guardado no **syspass** — deve **permanecer ativo**.
- Comunicação em **português do Brasil**, direta, focada em sintoma e causa.
