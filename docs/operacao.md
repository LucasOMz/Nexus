# Operação e implantação

Detalhe técnico do Nexus: instalação, Docker, impressão térmica, LDAP, backup,
implantação no servidor e solução de problemas.

> Este arquivo era o README.md antigo. Ele foi **movido inteiro** — nada foi
> resumido nem perdido. O README.md agora é a apresentação do sistema, para
> quem vai usá-lo ou avaliá-lo.

---

O **Nexus** é um sistema web de gestão patrimonial com **dois inventários** (TI e Impressoras),
**QR Code assinado HMAC-SHA256**, **impressão em impressora térmica** por
dispositivo cadastrado (Raspberry Pi / compartilhamento / CUPS), **leitura por
scanner físico**, **permissões granulares por usuário**, **banco de fotos** e
PWA offline-first — em Material Design 3 com tema vermelho.

---

## 1. Funcionalidades

### Navegação
- **Login → Seleção de inventário**: ao entrar, o usuário escolhe qual inventário abrir (cards grandes de TI ou Impressoras). Só aparecem os inventários que ele pode acessar.
- **Menu inicial do inventário**: tela com os módulos disponíveis e o botão **“Trocar inventário”** (volta para a seleção).
- **Botão de menu no topo** em todas as telas, voltando sempre ao menu inicial do inventário.
- Menu lateral (Navigation Rail no desktop / Bottom Nav no mobile) + botão de 3 barras com drawer.

### Inventários
- **Estoque/Ativos**: ativos patrimoniais (patrimônio, S/N, MAC) vs consumíveis (lote + mínimo). Status `estoque | reservado | em_uso | manutencao | descartado | emprestado`.
- **Foto do ativo**: cada ativo pode receber uma imagem do Banco de Fotos, exibida na lista e no cartão de detalhe.
- **Dashboard** por inventário: totais, alocados, manutenção, garantias 30/60/90d; extra TI (SO/RAM/departamento) e extra Impressoras (contador, custo/página, suprimentos baixos).
- **Movimentações** e **Manutenções** (entidade própria, com anexos e transições de status).
- **Atribuição** a colaboradores com **Termo de Responsabilidade em PDF** e **hash SHA-256**.

### QR Code, impressão e leitura
- **QR Code assinado**: payload `TIATIVO:{id}:{ts}:{hmac_b64}` validado no servidor; geração individual e em massa.
- **Dispositivos de impressão cadastráveis** (Administração → Impressão): informe o **hostname** (ex.: `RTAT0001`) e o **compartilhamento** (ex.: `\\RTAT0001\sip`), ou a URL do agente Raspberry, ou a fila do CUPS. Ao imprimir, o operador escolhe o dispositivo e o formato (ZPL/TSPL/PDF).
- **Leitura por scanner físico** (sem câmera): o leitor digita o código e pressiona Enter; também é possível digitar o **patrimônio / nº de série** manualmente. Há o botão “Pronto para leitura”.

### Administração (somente admin)
- **Usuários & permissões**: ao criar/editar um usuário, marque **quais inventários** ele acessa, **quais módulos** ficam liberados e se pode **criar/editar** e **excluir**. O backend aplica as mesmas regras (bloqueio real, não só visual).
- **Dispositivos de impressão**: cadastro e edição do destino de impressão.
- **Banco de Fotos** (estilo Zabbix): envie fotos, marque tags e reutilize nos ativos.

### Relatórios
- **Gráficos de inventário** (SVG puro, sem dependências): status (rosca), categoria, localização, departamento, valor patrimonial, garantias (30/60/90), movimentações por mês (entradas x saídas), manutenções, SO/RAM (TI) e contador/suprimentos (Impressoras).
- **Exportação CSV/PDF** de inventário, ativos por usuário, movimentações, manutenções, garantias e consumíveis abaixo do mínimo + **filtros salvos**.

### Segurança e plataforma
- **JWT** (access 15min + refresh 7d), **bcrypt**, papéis `admin|ti|leitor|auditor` e **permissões por usuário**, rate limit em `/login` e `/scan`, auditoria de mutações (diff + IP), headers de segurança, soft delete (LGPD).
- **PWA** instalável e offline-first (service worker cache-first + fila IndexedDB).

---

## 2. Estrutura

```
estoque-qr/
├── app/
│   ├── main.py            # FastAPI: CORS, headers, routers, static, health
│   ├── config.py          # pydantic-settings (.env)
│   ├── database.py        # engine/sessão SQLAlchemy 2.0
│   ├── core/              # security, deps (roles+permissões), permissoes, rate limit
│   ├── models/            # base, enums, core (usuario/imagem/dispositivo), ti, impressora
│   ├── schemas/           # Pydantic v2 (estrito)
│   ├── services/          # qr_service (HMAC), print_service, audit, pdf, counter
│   └── routers/           # auth, cadastros, dashboard, produtos, ativos,
│                          # movimentacoes, manutencoes, qrcode, print, scanner,
│                          # relatorios, graficos, admin
├── frontend/
│   ├── index.html, styles.css, manifest.json, sw.js, app.js
│   ├── js/                # api, state, router, ui, offline, lookups, charts, views/*
│   └── icons/             # ícones PWA
├── alembic/               # migrações (env.py ligado aos modelos)
├── tests/                 # pytest
├── schema.sql             # DDL PostgreSQL 16 (ENUM nativo, MACADDR, triggers)
├── raspberry_print_agent.py
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## 3. Rodando do zero (diagnóstico, sem Docker)

> Pré-requisitos: Python 3.11+.

### 3.1 Opção rápida — **removida**

Os scripts `run.bat`, `run.ps1`, `run.sh` e `run-servidor.ps1` **não existem
mais**. Eles subiam a aplicação direto no sistema operacional, sem container.

**Por que saíram:**

- Instalavam dependências que a imagem **não** instalava (foi assim que o
  `pysnmp` do monitor de impressoras funcionava fora do container e falhava
  dentro)
- Duas formas de subir o sistema divergem na primeira semana, e a divergência
  só aparece em produção
- O caminho suportado é o **Docker** — seção 2 deste documento

**Se precisar rodar sem container** (depuração de um problema específico do
host), o equivalente manual é:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 4545
```

Sem promessa de paridade com o container: é ferramenta de diagnóstico, não
caminho de instalação.

Depois abra **http://127.0.0.1:8000** e entre com:

- **E-mail:** `admin@empresa.com`
- **Senha:** `admin123`

### Acessar de outra máquina (pelo IP)

O servidor sobe escutando em `0.0.0.0` — ou seja, aceita acesso da rede. O
próprio script mostra os endereços:

```
Neste computador :  http://127.0.0.1:8000
Na rede local    :  http://192.168.7.12:8000
```

No celular ou em outra máquina, use o endereço **"Na rede local"**.

Para restringir a este computador apenas (mais seguro): `--host 127.0.0.1`.

**Se outra máquina (ou o celular) não abrir**, verifique nesta ordem:

1. **O firewall do Windows.** O script avisa quando não encontra regra. Libere
   como Administrador:

   ```powershell
   New-NetFirewallRule -DisplayName "Nexus" -Direction Inbound `
       -Protocol TCP -LocalPort 8000 -Action Allow
   ```

2. **Estão na mesma rede?** Compare o IP do computador (acima) com o do celular
   (Configurações → Wi-Fi → detalhes). Precisam começar igual: `192.168.7.x`.

3. **O celular está no Wi-Fi**, e não nos dados móveis?

4. **Wi-Fi de visitantes / isolamento de clientes.** Redes de convidados e
   algumas redes corporativas isolam os dispositivos: o celular não alcança o
   PC. Teste com outro computador na rede com fio.

5. **Teste rápido de conectividade** (no celular, pelo navegador):
   `http://SEU-IP:8000/health` deve responder algo como
   `{"status":"ok","database":true}`. Se não responder nada, é rede/firewall —
   não é o sistema.

### 3.2 Passo a passo manual

```bash
cd estoque-qr

# 1. Ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 2. Dependências
pip install -r requirements.txt

# 3. Configuração (opcional — já há padrões seguros para dev)
copy .env.example .env        # Windows
# cp .env.example .env         # Linux/macOS

# 4. Sobe a API (cria as tabelas e o usuário admin automaticamente)
uvicorn app.main:app --reload
```

> Não é preciso baixar nenhuma biblioteca de frontend: o scanner usa **leitor
> físico** (teclado) ou digitação manual, e os gráficos são SVG puro — sem
> dependências externas.

> **O `python -m venv` falhou / o venv ficou sem `pip`?** Acontece com o Python
> da Microsoft Store (o `ensurepip` dele falha). Instale o Python do python.org, que instala o
> `pip` via `get-pip.py` automaticamente, ou instale o Python em
> https://www.python.org/downloads/.

> O padrão do `.env.example` usa SQLite (`sqlite:///./estoque.db`) para o dev
> rodar com **zero infraestrutura**. Em produção use PostgreSQL (seção 4).

### Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 4. Produção com Docker Compose (PostgreSQL 16 + Nginx)

```bash
cd estoque-qr
# Ajuste .env com segredos fortes (JWT_SECRET, QR_HMAC_SECRET, senha admin)
docker compose up -d --build
```

Sobe `api` + `postgres:16` + `nginx`. A API roda em `:8000` e o Nginx em `:80`
(reverso para a API). Para HTTPS Let's Encrypt, descomente os blocos em
`nginx/nginx.conf` e emita o certificado com certbot.

> Migrações: o `AUTO_CREATE_TABLES=true` cria o schema no boot (prático para o
> 1º deploy). Para fluxo versionado, gere a migração inicial e aplique:
> ```bash
> alembic revision --autogenerate -m "initial"
> alembic upgrade head
> ```
> O `schema.sql` documenta o DDL otimizado de produção (ENUMs nativos, MACADDR,
> JSONB e triggers de manutenção).

---

## 5. Impressão térmica (Windows, Raspberry Pi / CUPS)

Há **três formas** de imprimir. Você escolhe em **Administração → Impressão**,
cadastrando um *Dispositivo de Impressão*.

### 5.1 Fila compartilhada — Windows e Linux (sem Raspberry)

Se a impressora já está **compartilhada** em uma máquina Windows, não precisa de
agente nem de CUPS. O **mesmo cadastro** vale nos dois sistemas:

| Campo | Valor |
|---|---|
| Tipo | **Windows — fila compartilhada** |
| Compartilhamento | `\\DTAT7777\SATO` |
| Formato | `zpl` (Zebra) ou `tspl` (TSC/Elgin) |

O envio é feito com os **bytes crus** (ZPL/TSPL), que é o que uma impressora de
etiquetas entende:

| Sistema | Como o sistema envia |
|---|---|
| **Windows** | Grava os bytes no caminho UNC; o **spooler** entrega à impressora — igual ao clássico `copy /b etiqueta.zpl \\DTAT7777\SATO` |
| **Linux** | Envia pelo **`smbclient`** (protocolo de impressão SPOOLSS), já que no Linux não existe caminho UNC de impressora |

**No Linux**, instale o cliente Samba:

```bash
apt install smbclient        # Debian/Ubuntu
dnf install samba-client     # RHEL/Fedora
```

Se a fila exigir credenciais (o padrão tenta acesso anônimo):

```env
PRINT_SMB_USUARIO=DOMINIO\svc_impressao
PRINT_SMB_SENHA=senha
```

**Requisitos nos dois sistemas:**

1. A impressora precisa estar **compartilhada** na máquina de origem.
2. A conta que executa o sistema precisa ter **permissão de impressão** na fila.
3. Formato **ZPL ou TSPL** — fila crua não entende PDF (o sistema avisa).
4. Não use em container Linux para uma fila Windows **sem** o `smbclient`
   instalado na imagem.

Depois de cadastrar, use **Imprimir teste** para validar.

> **Alternativa no Linux (mais robusta):** criar uma fila no CUPS com a URI
> `smb://usuario:senha@DTAT7777/SATO` e cadastrar o dispositivo com tipo
> **CUPS**. Assim o próprio CUPS cuida das credenciais e do spool.
> A opção "fila compartilhada" no Linux é um atalho que dispensa configurar o CUPS.

### 5.2 Raspberry Pi (ou qualquer Linux) com CUPS

No Raspberry Pi (ou qualquer Linux com CUPS):

```bash
# Instala dependências e o agente
pip install fastapi uvicorn pydantic
# Configure sua impressora térmica no CUPS (lpadmin -p zebra -E -v ... -m raw)
python raspberry_print_agent.py          # escuta em 0.0.0.0:9100
```

Aponte `PRINT_AGENT_URL` no `.env` da API para `http://<IP-do-Pi>:9100`.

O agente recebe `POST /print` com o conteúdo da etiqueta em base64 e o formato
(`zpl`/`tspl`/`pdf`) e:

1. Se `printer` for um host/IP e o formato for `zpl`/`tspl`, envia **bytes crus via socket** (impressora térmica em rede);
2. Caso contrário, usa **CUPS** (`lp -d printer -n copies [-o raw]`).

`GET /health` retorna o heartbeat e as impressoras CUPS disponíveis.

### systemd (exemplo)

```ini
# /etc/systemd/system/raspberry-print.service
[Unit]
Description=Raspberry Print Agent
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/estoque/raspberry_print_agent.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

---

## 6. Segurança

- **JWT** access (15 min) + refresh (7 dias) com rotação e blacklist em memória (Redis opcional em multi-réplica).
- **bcrypt** para senhas; **HMAC-SHA256** para o QR.
- **Permissões por usuário** (`inventarios`, `modulos`, `pode_escrever`, `pode_excluir`) aplicadas no backend por `require_module` / `require_escrita` / `require_exclusao` — não é só ocultação visual.
- **Papéis** (`admin | ti | leitor | auditor`) definem o padrão; o admin pode ajustar caso a caso.
- **Rate limit** em `/auth/login` e `/scanner/buscar` (janela deslizante em memória).
- **Auditoria append-only** (`logs_auditoria`) com diff JSON e IP em toda mutação.
- **Headers** HSTS/CSP/X-Frame-Options/X-Content-Type-Options.
- **LGPD**: soft delete em tudo + exportação de dados via relatórios.

---

## 7. Critérios de aceite (checklist)

- [x] Login com seleção de inventário e retorno ao menu inicial em todas as telas
- [x] CRUD completo nos dois inventários
- [x] QR com HMAC + validação server-side
- [x] Dispositivo de impressão cadastrável (hostname + compartilhamento) e editável no admin
- [x] Impressão individual e em massa
- [x] Leitura por scanner físico (sem câmera) + digitação manual do identificador
- [x] Dashboard com KPIs distintos por inventário
- [x] Manutenção como entidade + histórico + anexos
- [x] Termo PDF com hash de integridade
- [x] Auth JWT + papéis + permissões granulares + auditoria de mutações
- [x] Área de administração: usuários & permissões, impressão e banco de fotos
- [x] Banco de fotos reutilizável e foto vinculada ao ativo
- [x] Relatórios com gráficos de inventário + exportação CSV/PDF
- [x] Assinatura de QR configurável, sem exigir reimpressão de etiquetas
- [x] Login via AD/LDAP por grupo (ex.: `YM_ESTOQUE_TI`) configurável na tela
- [x] Administrador local como exceção (não depende do AD)
- [x] Etiquetas configuráveis com pré-visualização ao vivo, PDF e teste de impressão
- [x] Backup com validação em banco temporário e restauração com travas
- [x] Exportação/importação CSV total com remoção de duplicados
- [x] PWA instalável, offline-first
- [x] Navigation Rail (desktop) / Bottom Nav (mobile)
- [x] Tema vermelho com fundo branco no claro e escuro avermelhado no dark
- [x] Docker Compose sobe tudo com 1 comando

---

## 8. Resetar o sistema (começar do zero)

> Os scripts `reset.bat` e `reset.ps1` **foram removidos** junto com o caminho
> de execução no host. Eles apagavam `estoque.db` e `media/` — arquivos que
> só existem na instalação sem container.

**Em Docker, começar do zero é apagar os volumes:**

```bash
docker compose down -v      # para os containers e remove os volumes
docker compose up -d        # sobe com banco vazio e admin padrão
```

O `-v` é o que importa: sem ele o `down` apenas para os containers, e o
volume do PostgreSQL continua com os dados.

**O que isso apaga:** o banco (ativos, usuários, movimentações, manutenções,
notificações) e o volume de `media/` (fotos, termos em PDF, anexos).

**O que não apaga:** a imagem, o código e as variáveis de ambiente da stack.

> **Para apagar só os dados, mantendo a configuração**, pare a stack e remova
> apenas o volume do banco no Portainer — os segredos ficam nas variáveis de
> ambiente, não no volume.

O script avisa se o servidor ainda estiver rodando (o banco fica em uso) e
tenta novamente algumas vezes, porque o Windows demora alguns segundos para
liberar o arquivo depois de fechar o servidor.

Depois do reset, o próximo start recria tudo sozinho, incluindo:

- **E-mail:** `admin@empresa.com`
- **Senha:** `admin123`

### Resetar também o cache do NAVEGADOR

O reset do servidor **não** limpa o cache do navegador. Depois de resetar, faça
uma destas opções para garantir que ele carregue a versão mais recente:

1. **Mais fácil:** abra o sistema numa **janela anônima / InPrivate** — ela não
   tem service worker nem cache antigos.
2. **Automático:** acesse `http://127.0.0.1:8000/?reset=1` — essa URL limpa o
   service worker, os caches e a sessão local, e recarrega sozinha.
3. **Manual:** `F12` → **Application** → **Service Workers** → *Unregister*;
   e em **Storage** → *Clear site data* → recarregue.

> No menu lateral (botão de 3 barras) existe o item **“Atualizar aplicativo”**,
> que faz a mesma limpeza sem precisar do DevTools.

### Atualizando de uma versão anterior (schema do banco)

O schema ganhou tabelas e colunas novas (`imagens`, `dispositivos_impressao`,
`ativos.foto_id`, `usuarios.permissoes`). Em desenvolvimento, o caminho mais
simples é `docker compose down -v`, que apaga o banco e o volume de mídia e deixa o
sistema recriar.

Em produção com PostgreSQL, use `alembic revision --autogenerate` /
`alembic upgrade head`, ou rode o `schema.sql` atualizado.

---

## 9. Recursos avançados

### 9.1 Assinatura do QR Code (sem reimprimir etiquetas)

O payload é `TIATIVO:{id}:{timestamp}:{hmac}`. A leitura **sempre resolve o
ativo pelo ID que está dentro do payload** — então etiquetas já impressas
continuam funcionando mesmo que o segredo mude.

| Variável | Para que serve |
|---|---|
| `QR_EXIGIR_ASSINATURA` | `true` (padrão) exige assinatura válida. `false` aceita a etiqueta pelo ID mesmo com assinatura divergente |
| `QR_HMAC_SECRETS_ANTERIORES` | Lista de segredos antigos aceitos na validação (separados por vírgula) — permite **trocar o segredo sem reimprimir nada** |

Toda leitura passa pela auditoria com o campo `assinatura_valida`, então é
possível saber quando alguém usou uma etiqueta sem assinatura conferida.

> **Importante:** guarde o `QR_HMAC_SECRET` junto com o backup. Ele faz parte do
> backup, não só o banco.

### 9.2 Login pelo Active Directory (LDAP)

Configurável em **Administração → Autenticação (AD)**, sem mexer em arquivo:

- Servidor, porta, TLS/LDAPS e validação de certificado
- Base DN e conta de serviço (a senha é gravada **cifrada** no banco)
- Filtro de usuário (ex.: `(sAMAccountName={usuario})`)
- **Grupo de acesso** (ex.: `YM_ESTOQUE_TI`) — quem estiver nele entra no sistema
- Grupo de administradores (opcional)
- Provisão automática no primeiro login

Dois botões antes de ativar: **Testar conexão** e **Testar login de um usuário**
(que informa se a pessoa autenticou *e* se pertence ao grupo).

**O administrador local é a exceção:** `SEED_ADMIN_EMAIL` autentica pela senha do
sistema e **não depende do grupo do AD** — é a rota de emergência se o AD cair.

> A chave de cifragem é derivada do `JWT_SECRET`. Se você trocar o `JWT_SECRET`,
> a senha da conta de serviço fica ilegível — basta recadastrá-la na tela.

### 9.3 Etiquetas configuráveis

Em **Administração → Etiquetas** você define, com **pré-visualização ao vivo**:

- **Tamanho** (mm) com presets (100×50, 80×40, 60×40, 50×30, 40×25, 30×20)
- **DPI da impressora** — 203/300/600. É o ajuste que mais causa etiqueta saindo
  no tamanho errado: a 203 dpi são 8 dots/mm, a 300 dpi são 11,8
- **QR**: exibir, posição (esquerda/direita), tamanho e correção de erro (L/M/Q/H)
- **Texto**: título, rodapé, prefixo do patrimônio, fonte, alinhamento, margens
- **Campos exibidos**: 17 opções (patrimônio, modelo, série, setor, IP, contador…)

A geometria é calculada **uma única vez** e alimenta ZPL, TSPL, PDF e a
pré-visualização — por isso o que aparece na tela corresponde à impressão.
A tela ainda **avisa quando o texto não cabe** na largura.

Três formas de saída:

- **Imprimir teste** — manda uma etiqueta de exemplo (TIAT0001) no dispositivo escolhido
- **Baixar PDF** — o PDF sai no tamanho exato e pode ser impresso em qualquer
  impressora, inclusive de escritório
- **Impressão normal** — pelo inventário, usando o template do dispositivo

Cada **Dispositivo de Impressão** pode ter o seu template (a portátil e a de
mesa costumam usar etiquetas diferentes).

### 9.4 Backup e restauração

Em **Administração → Backups**:

- Lista dos backups com data, tamanho, versão da app e resumo das tabelas
- Status: último backup e há quantas horas (alerta acima de 72 h)
- **Criar backup agora**, **baixar** e **validar**
- **Restaurar** com as travas: valida num banco temporário → exige a senha do
  admin → exige digitar `RESTAURAR` → **gera um backup do estado atual antes**
- A pasta é definida por `BACKUP_DIR` — aponte para o compartilhamento de rede
  montado no host (ex.: `/mnt/backups`)

A validação restaura o arquivo num **banco temporário**, confere as tabelas
obrigatórias e mostra o que tem dentro ("1523 ativos, 42 usuários") **sem tocar
no banco em uso**. Só depois de você aprovar a troca acontece.

> As **fotos, termos e anexos** ficam na pasta `media/` — o backup do banco não
> os inclui. O sistema avisa isso na tela de restauração.

**Agendando (produção):** um `pg_dump` diário com rotação resolve melhor que
"a cada 3 dias" (o cron não expressa 72 h de forma limpa, e reinicia na virada
do mês). O `pg_dump -Fc` é o formato correto — **copiar o volume do PostgreSQL
cru pode gerar backup inconsistente**.

### 9.5 Exportar / importar CSV

- **Exportar CSV total** baixa um `.zip` com um CSV por tabela + manifesto.
  Usa nomes (patrimônio, SKU, e-mail, nome do departamento) em vez de IDs, para
  o arquivo ser legível e reimportável.
- **Importar CSV** sempre roda primeiro em **simulação**, mostrando o que seria
  feito — novos, duplicados e ignorados por entidade.
- Os **duplicados são removidos** pela chave natural de cada entidade:
  patrimônio (ativos), SKU (produtos), e-mail (usuários), nome (departamentos,
  localizações, fornecedores, categorias), e combinações para movimentações e
  manutenções.
- Opcionalmente, **atualizar** os registros existentes em vez de apenas ignorar.

Esse é o caminho para recuperar dados do dia a dia **sem** restaurar o banco
inteiro — o restore completo fica reservado para recuperação de desastre.

---

### 9.6 Etiquetas em branco (cadastrar depois)

Em **Leitura → Etiquetas em branco** você gera QR Codes **sem dono**: etiquetas
"zeradas", para imprimir, colar no equipamento e cadastrar depois.

1. Informe a **quantidade** e clique em *Gerar etiquetas em branco*.
2. Escolha o destino: **impressora cadastrada** ou **PDF** (tamanho exato, para
   imprimir em qualquer impressora).
3. Cole a etiqueta no equipamento.
4. Na janela de leitura, leia o código: o sistema abre o **cadastro do
   equipamento já vinculado àquela etiqueta** — basta preencher e salvar.
5. Da próxima vez, o mesmo código abre o ativo normalmente.

Detalhes que valem saber:

- O código impresso é curto e legível (ex.: `JXPM7P5FC8`), **sem caracteres
  ambíguos** (`I`, `O`, `0`, `1`), para permitir digitação manual se o leitor
  falhar.
- Cada etiqueta só pode ser vinculada a **um** ativo. Tentar reutilizar devolve
  uma mensagem dizendo qual equipamento já está com ela.
- A tela mostra quantas etiquetas estão **livres** por lote, e o botão de
  imprimir fica desabilitado quando o lote todo já foi usado.
- O payload das etiquetas em branco é assinado com o **mesmo segredo** do QR
  normal (`QR_HMAC_SECRET`), então as regras de assinatura valem igual.
- O QR Code em branco **continua válido** mesmo se o `QR_HMAC_SECRET` mudar, desde
  que o segredo antigo esteja em `QR_HMAC_SECRETS_ANTERIORES`.

> Dica: gere os lotes em blocos pequenos (10 a 30). Se um lote inteiro for
> perdido ou impresso errado, dá para excluir as etiquetas ainda **livres**.

---

## 10. Levar para o servidor — **apenas por container**

As seções que existiam aqui descreviam a instalação **Windows nativa**:
`publicar.ps1` montava um `.zip`, o servidor instalava Python 3.11 e o
`run-servidor.ps1` registrava a aplicação como serviço do Windows
(`New-Service`, firewall, recuperação automática).

**Tudo isso foi removido**, junto com os scripts de execução e de reset.

**Por que:** eram dois caminhos de instalação, com dependências diferentes.
O `run.ps1` instalava o `pysnmp` do monitor de impressoras; a imagem Docker
não instalava. O resultado é conhecido — funcionava na máquina de quem testou
e falhava no servidor, sem nada no código a apontar.

**O caminho de implantação é um só:** container, publicado pela stack do
Portainer. Veja a **seção 12**.

> `wheels/` (31 MB de pacotes Python, resquício de uma tentativa de build
> offline) também foi removida: o `Dockerfile` voltou a instalar pelo
> `requirements.txt`, e a pasta não era usada por nada.

---

## 12. Implantar no Portainer (Docker)

No Portainer: **Stacks → Add stack → Web editor**, cole o `docker-compose.yml`.

**Requisitos:**

- Um host Docker **Linux** (ou uma VM Linux). A imagem é `python:3.12-slim`;
  Docker Desktop não roda em Windows Server — nesse caso use uma VM Linux ou o
  recurso de containers Linux do próprio Windows Server.
- **Variáveis obrigatórias** no stack: `JWT_SECRET` e `QR_HMAC_SECRET`
  (o compose falha de propósito se não forem informadas).
- **Volumes persistentes** — `media` e `backups` já estão declarados. Sem eles,
  fotos, termos, anexos e backups vivem dentro do container e **são perdidos**
  ao recriar a stack.
- Para backup em pasta de rede: monte o compartilhamento **no host** e troque o
  volume `backups` por um bind mount (`- /mnt/backups/estoque:/app/backups`).
  Não monte SMB dentro do container (exigiria `SYS_ADMIN`).
- Portas `80`/`443` (nginx) e `8000` (API) livres, ou ajuste `API_PORT`.
- O arquivo `nginx/nginx.conf` precisa existir no repositório clonado.

> O banco é o serviço `db` (PostgreSQL 16). Para **restaurar** um backup no
> container, o `pg_restore` precisa estar disponível — a imagem `python:3.12-slim`
> não traz os utilitários do PostgreSQL. Se você for usar a restauração pela
> tela, instale `postgresql-client` na imagem (ou rode o `pg_restore` pelo host).

---

## 13. Solução de problemas

### "Mudei/atualizei o sistema e o navegador continua mostrando a versão antiga"

O PWA usa **service worker** para funcionar offline. Ele guarda os arquivos em
cache — e uma versão antiga pode ficar presa no navegador.

**Como resolver (1x):**
1. Feche todas as abas do sistema.
2. Abra `http://127.0.0.1:8000` e pressione **Ctrl + Shift + R** (recarga
   forçada, sem cache).
3. Se ainda aparecer a versão antiga: `F12` → aba **Application** →
   **Service Workers** → **Unregister** → **Storage** → **Clear site data** →
   recarregue.

**Como saber em qual versão você está:** a tela de seleção de inventário (e o
menu lateral) mostram **“Versão 2.0.0”** no rodapé. Se não aparecer essa linha,
você ainda está na versão antiga em cache.

### Para quem for alterar o frontend

Sempre que mexer no frontend, **aumente a versão** em dois lugares para forçar
a atualização nos navegadores:

- `frontend/js/version.js` → `APP_VERSION`
- `frontend/sw.js` → `const VERSION = "v3"` (o cache é nomeado `patrimonio-vN`)

Ao mudar a versão do `sw.js`, o service worker novo assume, **apaga os caches
antigos** e a página se recarrega sozinha.

### Erro de banco ("no such column" / "relation does not exist")

O schema mudou e o banco é antigo. Apague o `estoque.db` (seção 8).

### "Address already in use" (porta 8000 ocupada)

Já existe uma instância rodando. Feche o outro terminal (`CTRL + C`) ou verifique:

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 8000
```

### Verificar se o frontend está íntegro

Ferramenta que importa todos os módulos JS e aponta import/export quebrado:

```bash
node tests/check_frontend_modules.mjs
```
