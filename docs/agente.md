# Agente de inventário — desenho

Substitui o OCS Inventory. Roda em segundo plano nas estações Windows, coleta
hardware e software, e envia ao Nexus.

> **Este documento é o plano.** Nada foi implementado. Ele existe para ser
> revisado pelo time de TI antes da primeira linha de código — porque um mês
> de trabalho distribuído em milhares de máquinas merece revisão antes.

---

## 1. Decisões tomadas

| Decisão | Consequência |
|---|---|
| **Parque só Windows** | um alvo só. Sem coleta Linux, sem `dpkg`, sem systemd |
| **MDM instala por comando, silencioso** | o instalador recebe parâmetros na linha de comando |
| **Não roda em servidores** | sem exigência de hardening de servidor; é agente de estação |
| **Máquinas fora da rede, futuramente** | envio **de dentro para fora**, por HTTPS público |
| **Substitui o OCS** | o OCS é desligado ao final da transição; não fica em paralelo para sempre |

### Servidor e estação são ambientes diferentes

Esta distinção atravessa o documento inteiro e vale registrar:

| | Onde roda | Sistema |
|---|---|---|
| **Nexus (API)** | **Docker** | **Linux**, sempre |
| **Agente** | Estação de trabalho | **Windows**, sempre |

**O `run.bat` é ferramenta de teste**, não de produção. Ele existe para subir a
aplicação na máquina de quem desenvolve e conferir funcionalidade rápido.
**Produção é o container** — e o container é Linux mesmo quando o host é
Windows, porque Docker no Windows roda por WSL.

**O que isso implica para este projeto:**

- O lado **servidor** (endpoints, reconciliação, `agentes`, `tokens_enrollment`)
  é escrito para **Linux/Docker**. Nada de caminho Windows na API.
- O lado **agente** é escrito para **Windows**. Nada de `dpkg`, systemd, CUPS.
- Os dois se encontram **só no protocolo HTTP** — e é por isso que podem ter
  sistemas diferentes sem conflito.

> Consequência prática: um teste que só passa no Windows **não prova nada sobre
> produção**. O CI roda em Linux, e é o ambiente certo — é a primeira coisa que
> se parece com o container.

---

## 2. Arquitetura

```
┌─────────────────────┐         HTTPS 443          ┌──────────────────┐
│  Estação Windows    │  ───────────────────────►  │      Nexus       │
│                     │                            │                  │
│  Serviço "Nexus     │   POST /api/v1/agente/     │  reconcilia por  │
│  Inventário"        │        inventario          │  SERIAL          │
│                     │                            │                  │
│  coleta a cada N h  │  ◄───────────────────────  │  AtivoTI         │
│  fila local se off  │        200 / 401 / 409     │  SoftwareInstal. │
└─────────────────────┘                            └──────────────────┘
         ▲
         │ instalação silenciosa + token
         │
    ┌─────────┐
    │   MDM   │
    └─────────┘
```

**Só saída.** Nenhuma porta aberta na estação, nenhuma conexão de entrada.
É o que permite funcionar em home office sem VPN.

---

## 3. O agente

**Go**, binário único `windows/amd64`, ~8 MB.

| Por que Go | |
|---|---|
| Binário único | sem runtime, sem instalador de Python, sem dependência |
| Antivírus | um `.exe` assinado é tratado melhor que um script empacotado |
| Serviço nativo | `golang.org/x/sys/windows/svc` — sem wrapper de terceiro |
| Cross-compile | `GOOS=windows` numa máquina Linux, se preciso |

### O que coleta

| Campo | Fonte no Windows |
|---|---|
| **Número de série** | `Win32_BIOS.SerialNumber` + `Win32_BaseBoard.SerialNumber` |
| hostname | `Win32_ComputerSystem.Name` |
| MAC e IP | `Win32_NetworkAdapterConfiguration` (só os ativos) |
| CPU | `Win32_Processor.Name` |
| RAM | `Win32_ComputerSystem.TotalPhysicalMemory` |
| Discos | `Win32_DiskDrive` (modelo + tamanho) |
| SO | `Win32_OperatingSystem` (caption + build) |
| **Software** | registro: `HKLM\...\Uninstall` (32 e 64 bits) |

### Regra do serial — a mais importante

O serial **é o identificador do ativo**. Se o agente mandar um serial diferente
do que está na etiqueta, o ativo **duplica** em vez de atualizar.

O agente **não envia** quando:

- o serial vem vazio
- o serial é texto de fábrica: `To be filled by O.E.M.`, `Default string`,
  `System Serial Number`, `None`, `0`
- o serial tem menos de 4 caracteres

Nesses casos ele registra no log local e reporta ao servidor como
**"máquina sem serial confiável"** — que aparece numa tela de pendências, em
vez de virar um ativo fantasma.

> Essa é a mesma regra que o `ocs_service` já aplica com `_serial_provisorio`.
> O agente deve fazer melhor: **avisar**, em vez de inventar um serial.

### Ciclo de execução

```
1. Na subida do serviço       → coleta e envia
2. A cada N horas (padrão 6)  → coleta e envia
3. Falhou?                    → guarda em disco e retenta com espera
                                crescente (1 min, 5, 15, 60, 240…)
4. Voltou a rede              → envia a fila, da mais antiga para a mais nova
```

**Não se auto-atualiza.** Auto-update num binário privilegiado em milhares de
máquinas é vetor de ataque, e você já tem MDM. O agente **reporta a versão**; o
servidor marca quem está abaixo do mínimo, e o MDM atualiza.

---

## 4. Instalação pelo MDM

O MDM executa um comando. O instalador aceita parâmetros:

```bat
nexus-agente-setup.exe /S /token=ENROLL-a1b2c3 /servidor=https://nexus.empresa.com
```

| Parâmetro | Obrigatório | Para quê |
|---|---|---|
| `/S` | sim | silencioso |
| `/token` | sim | token de **enrollment** (ver seção 5) |
| `/servidor` | sim | URL base do Nexus |
| `/intervalo` | não | horas entre coletas (padrão 6) |

**O que o instalador faz:**

1. Copia o `.exe` para `%ProgramFiles%\Nexus\`
2. Cria o serviço (`sc create`), início automático, conta `LocalSystem`
3. Grava os parâmetros em `HKLM\SOFTWARE\Nexus\Agente`
4. Inicia o serviço

**Desinstalação:** `nexus-agente-setup.exe /S /uninstall` — remove serviço,
arquivos e a credencial local.

> **O comando do MDM é o mesmo para todas as máquinas do grupo.** É por isso
> que o token ali **não pode ser a credencial final** — ele é só a porta de
> entrada, e a seção seguinte explica.

---

## 5. A credencial — o ponto crítico

**Um token único em milhares de máquinas é um token vazado** no dia em que
alguém abrir o binário ou ler a chave do registro.

### O fluxo

```
1. MDM instala com o token de ENROLLMENT (compartilhado por grupo)
   ↓
2. Primeira execução: o agente envia
       POST /api/v1/agente/registrar
       { "token_enrollment": "...", "serial": "...", "hostname": "..." }
   ↓
3. O servidor:
       - valida o token (válido, não expirado, não excedeu o limite do grupo)
       - casa o SERIAL com o ativo já cadastrado
       - emite um SEGREDO PRÓPRIO da máquina
       - grava só o HASH do segredo
   ↓
4. O agente guarda o segredo com DPAPI (CryptProtectData) — atrelado à máquina
   ↓
5. Toda coleta usa esse segredo; o token de enrollment não serve mais
```

### Por que enrollment e não token direto

| | Token direto | Enrollment |
|---|---|---|
| Vazou um | **todos comprometidos** | só aquela máquina |
| Revogar uma máquina | impossível | imediata |
| Máquina nova | nada a fazer | registra sozinha |

### Propriedades do token de enrollment

- **Escopo por grupo** (ex.: `MATRIZ-2026`), para revogar um lote inteiro
- **Expira** (padrão 90 dias)
- **Limite de registros** por token — se alguém vazar e tentar registrar
  10.000 máquinas falsas, o teto corta
- **Registro em auditoria** de cada enrollment: serial, IP, data

### A credencial no disco

`DPAPI` com escopo de máquina. Não é à prova de administrador local — nada é —
mas impede que copiar o arquivo para outra máquina funcione.

---

## 6. O protocolo

### Registro (uma vez por máquina)

```
POST /api/v1/agente/registrar
Content-Type: application/json

{ "token_enrollment": "ENROLL-a1b2c3", "serial": "...", "hostname": "..." }

→ 201 { "segredo": "...", "agente_id": 42 }
→ 401 token inválido/expirado
→ 409 serial não cadastrado (o ativo precisa existir antes)
```

> **409 no serial não cadastrado** é deliberado: o agente **não cria ativo**.
> Inventário que cria sozinho enche o banco de duplicata. Máquina desconhecida
> entra numa tela de **"novas máquinas"**, e alguém decide.

### Inventário

```
POST /api/v1/agente/inventario
Authorization: Bearer <segredo-da-máquina>

{
  "versao_agente": "1.0.3",
  "coletado_em": "2026-10-17T13:00:00Z",
  "maquina": {
    "serial": "...", "hostname": "...", "so": "Windows 11 Pro",
    "build": "22631", "cpu": "...", "ram_gb": 16,
    "discos": [{"modelo": "...", "gb": 512}],
    "macs": ["..."], "ips": ["..."]
  },
  "software": [
    {"nome": "Microsoft 365 Apps", "versao": "16.0.17126", "fabricante": "Microsoft"}
  ]
}
```

**Idempotente.** Enviar duas vezes o mesmo inventário não muda nada. Isso
importa porque a fila offline reenvia.

### Resposta

```
200 { "ok": true, "versao_minima": "1.0.0", "proxima_coleta_em_horas": 6 }
```

`versao_minima` permite ao agente **avisar no log** que está defasado. Quem
atualiza é o MDM.

---

## 7. Modelo de dados no Nexus

### Tabela nova: `agentes`

```sql
CREATE TABLE agentes (
    id              SERIAL PRIMARY KEY,
    ativo_id        INTEGER NOT NULL UNIQUE REFERENCES ativos(id),
    grupo           VARCHAR(60) NOT NULL,      -- escopo do enrollment
    segredo_hash    VARCHAR(128) NOT NULL,     -- SHA-256 do segredo
    versao_agente   VARCHAR(20),
    ultimo_contato_em TIMESTAMPTZ,
    ultimo_ip       VARCHAR(45),
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    revogado_em     TIMESTAMPTZ
);
```

### Tabela nova: `tokens_enrollment`

```sql
CREATE TABLE tokens_enrollment (
    id          SERIAL PRIMARY KEY,
    token_hash  VARCHAR(128) NOT NULL UNIQUE,
    grupo       VARCHAR(60) NOT NULL,
    expira_em   TIMESTAMPTZ NOT NULL,
    limite      INTEGER NOT NULL DEFAULT 100,   -- quantas máquinas
    usados      INTEGER NOT NULL DEFAULT 0,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### O que muda

| Hoje | Depois |
|---|---|
| `AtivoTI.ocs_id` | **removido** — o serial identifica |
| `SoftwareInstalado` | **reaproveitada**, sem mudança |
| `ocs_service`, `ocs_sync`, `ocs_agendador` | **desligados** ao fim |
| Reconciliação por `ocs_id` | reconciliação **por serial** |

---

## 8. Máquinas fora da rede

Vão enviar de fora. Isso exige do lado do servidor:

| Requisito | |
|---|---|
| **HTTPS público com certificado válido** | o agente verifica o certificado; nada de `InsecureSkipVerify` |
| **DNS público** | ex.: `inventario.empresa.com` |
| **Rate limiting por IP e por agente** | milhares de estações, algumas atrás do mesmo NAT |
| **Sem sessão** — só token | não há usuário logado; é autenticação de máquina |
| **Fila offline robusta** | notebook pode ficar semanas fora |

**E o dado que trafega** é um mapa do parque: nome de máquina, serial, lista de
softwares. Não é segredo, mas é reconhecimento. **TLS obrigatório**, e o
payload **não** deve incluir nome de usuário, arquivos ou conteúdo.

---

## 9. Segurança — o que não é negociável

| # | Exigência | Por quê |
|---|---|---|
| 1 | **Binário assinado** | não assinado é bloqueado pelo GPO/antivírus, ou aceito com alerta que ninguém lê |
| 2 | **Somente leitura** | nada de execução remota. É o que separa inventário de backdoor |
| 3 | **TLS verificado** | o payload atravessa a internet |
| 4 | **Segredo por máquina, revogável** | máquina roubada = credencial morta no mesmo dia |
| 5 | **Enrollment com teto e expiração** | token vazado não registra milhares de máquinas falsas |
| 6 | **O agente não cria ativo** | inventário que cria sozinho enche o banco de duplicata |

---

## 10. Transição do OCS

**Não desligue no primeiro dia.**

```
Fase 1  Agente entra em um grupo piloto (50–100 máquinas)
        OCS continua, e as duas fontes alimentam as MESMAS tabelas

Fase 2  Relatório de divergência, por grupo:
          "OCS vê 8.412 · agente vê 8.397 · 15 de diferença"
        Cada uma das 15 é investigada — é onde aparecem os bugs

Fase 3  Agente em todo o parque, OCS ainda ligado

Fase 4  Divergência zero por 30 dias → OCS desligado
```

> **O relatório de divergência é o produto mais valioso desta fase.** Sem ele,
> os erros do agente só apareceriam meses depois, com o OCS já apagado e sem
> referência para comparar.

---

## 11. Ordem de implementação

| # | Etapa | Depende de | Tempo |
|---|---|---|---|
| 1 | Endpoint `/agente/registrar` + `tokens_enrollment` | — | 3 dias |
| 2 | Endpoint `/agente/inventario` + `agentes` | 1 | 3 dias |
| 3 | Reconciliação por serial | 2 | 2 dias |
| 4 | Tela de credenciais e novas máquinas | 1, 2 | 3 dias |
| 5 | Agente: coleta + envio + fila | 2 | 1 semana |
| 6 | Agente: serviço + instalador + assinatura | 5 | 4 dias |
| 7 | Relatório de divergência OCS × agente | 2 | 2 dias |
| 8 | Piloto e ajuste | todos | 2 semanas |

**~6 semanas de desenvolvimento**, mais o piloto.

**A ordem importa**: o servidor vem antes do agente. Assim o agente nasce
contra um contrato que já existe e é testável — em vez de os dois mudarem
juntos.

---

## 12. O que ainda precisa de decisão

| # | Pergunta | Efeito |
|---|---|---|
| 1 | O token de enrollment será **por grupo** ou o MDM consegue **por máquina**? | por máquina elimina o enrollment e simplifica tudo |
| 2 | Qual o **intervalo** de coleta? | 6 h é razoável; 1 h multiplica a carga |
| 3 | Aceita que **máquina sem serial confiável** fique pendente em vez de entrar? | é o que evita ativo fantasma |
| 4 | O Nexus terá **domínio público** com certificado? | sem isso, máquina fora da rede não envia |
| 5 | O **piloto** pode ser um grupo do MDM? | 50–100 máquinas, 2 semanas |
