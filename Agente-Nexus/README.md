# Agente Nexus

Agente Windows que coleta o inventário da máquina e envia ao Nexus.

**Estado atual**: coletor, registro e envio funcionando.

---

## Compilar

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Gera `bin\agente.exe` (~13 KB).

**Sem SDK, sem NuGet, sem Runtime extra.** Usa o `csc.exe` do .NET Framework
4.0, que existe em qualquer Windows 10. A limitação é **C# 5** — sem
interpolação de string, sem membros de expressão.

```powershell
.\build.ps1 -Rodar      # compila e já roda "coletar"
```

## Rodar

```powershell
# 1. diagnostico: imprime o JSON, sem servidor
.\bin\agente.exe coletar

# 2. registro: uma vez, com o codigo gerado no painel
.\bin\agente.exe registrar --servidor http://10.0.0.5:4545 --codigo AAAA-BBBB-CCCC

# 3. envio: a partir daqui, e o que o servico vai rodar
.\bin\agente.exe enviar
`

**Onde ficam os dados**: %ProgramData%\Nexus\agente.json.
O servidor em texto claro; o **token cifrado com DPAPI de maquina**. Copiar o
arquivo para outro PC nao funciona — e o ponto.``

---

## Modos

| Modo | O que faz | Precisa de servidor |
|---|---|---|
| `coletar` | lê o hardware e imprime o JSON | não |
| `registrar` | troca o código de instalação pelo token | **sim** — a construir |
| `enviar` | envia o inventário com o token | **sim** — a construir |

---

## O que é coletado

| Campo | Origem |
|---|---|
| serial | `Win32_BIOS.SerialNumber` — **filtrado** |
| hostname | `Environment.MachineName` |
| usuario | `Win32_ComputerSystem.UserName` |
| fabricante, modelo | `Win32_ComputerSystem` |
| cpu | `Win32_Processor` |
| ram_gb | soma de `Win32_PhysicalMemory` |
| armazenamento_gb | soma de `Win32_DiskDrive` |
| so | `Win32_OperatingSystem` |
| dominio | `Win32_ComputerSystem.Domain` |
| bios_versao | `Win32_BIOS.SMBIOSBIOSVersion` |
| placa_mae | `Win32_BaseBoard` |
| discos[] | `Win32_DiskDrive` — modelo, série, GB, tipo |
| rede[] | `Win32_NetworkAdapterConfiguration` — MAC, IPs |
| monitores[] | `WmiMonitorID` (`root\wmi`) — fabricante, modelo, série |
| gpu | `Win32_VideoController` |
| uptime_horas | `LastBootUpTime` |

**1,2 KB** numa estação típica. Sem lista de software — decisão consciente:
quadruplica o payload e envelhece rápido.

---

## O serial é filtrado de propósito

Estes valores são tratados como **ausência de serial**:

```
"", "0", "00000000", "To be filled by O.E.M.", "To Be Filled By O.E.M.",
"Default string", "None", "System Serial Number", "Not Specified", "N/A",
"VMware-*", "0000-0000-*"
```

**Placa-mãe de montagem própria devolve `To Be Filled By O.E.M.`** — foi o
que apareceu na primeira máquina de teste (ASRock B450M). Máquina que cair
nisso **não tem identificador** e precisa entrar na **fila de cadastro** do
painel, onde alguém escolhe MAC, hostname ou patrimônio.

> **Sem esse filtro**, quarenta máquinas brancas casariam todas com o mesmo
> serial e virariam uma só no inventário.

---

## Segurança

**O agente nunca abre porta.** Só faz `POST` para fora.

**Ele não aceita comando do servidor** — não há canal de entrada. Um impostor
na rede não tem o que mandar esta máquina fazer.

**Não acessa dado do usuário.** WMI e registro apenas.

### ⚠️ Dívida técnica conhecida: HTTP

Hoje a comunicação é **HTTP** — para teste em rede controlada. O token viaja
em texto claro.

**Mitigações em vigor**:

- token de 32 bytes aleatórios, válido para **um** ativo
- o token **só escreve**; não lê inventário, não lista ativos
- o agente só envia — não há superfície de comando

**Plano de migração**: quando o nginx subir, `SERVER` vira `https://` e o
agente passa a validar o certificado. **A regra de validação será: aceita se
(certificado válido no repositório do Windows) OU (impressão digital
guardada na instalação)** — assim a troca não exige reinstalar a frota.

---

## Fluxo de instalação (a construir)

```
1. Painel gera código de instalação (ex.: A7K2-9F3M-QX81, validade 48 h)
2. Instalador recebe: SERVER=... CODIGO=...
3. agente.exe registrar  →  POST /agente/registrar { codigo, serial }
4. Servidor valida e devolve o token único da máquina
5. Agente guarda o token com DPAPI (escopo de máquina)
6. agente.exe enviar     →  POST /agente/inventario (a cada 12 h)
```

**O código de instalação nunca é guardado** — é portão de entrada, não
credencial de operação.

**DPAPI** e não arquivo de config: uma chave em texto pode ser copiada para
outra máquina e funcionar; a protegida por DPAPI só é decifrável **naquela
máquina**.

---

## Escala alvo

**3.000 máquinas**, Windows 10+. Três ajustes que isso exige:

| Ajuste | Por quê |
|---|---|
| **Jitter de ±30 min** no intervalo | senão 3.000 máquinas coletam às 8h em ponto |
| **Código de frota** (1 código, N usos) | gerar 3.000 códigos é inviável |
| **Backoff com jitter** no retry | servidor fora + 3.000 agentes batendo = negação de serviço |

---

## Instalar

`powershell
powershell -ExecutionPolicy Bypass -File .\instalar.ps1 
    -Servidor http://10.0.0.5:4545 -Codigo AAAA-BBBB-CCCC
`

**O instalador faz quatro coisas:**

1. gente.exe registrar — troca o codigo pelo token (o codigo nao fica)
2. Tarefa **Coleta** — SYSTEM, a cada 12 h, inicio em hora aleatoria
3. Tarefa **Logon** — no logon do usuario, para capturar *quem* usa
4. Primeiro envio, para falhar na hora se algo estiver errado

### Por que tarefas agendadas, e nao um servico

| | Servico Windows | **Tarefa agendada** |
|---|---|---|
| Codigo | ServiceBase + start/stop + recuperacao | um comando |
| Processo residente | sim, 24 h | nao |
| Maquina desligada na hora | voce trata | Windows reexecuta |

**Duas tarefas** porque um processo SYSTEM **nao enxerga a sessao do
usuario** — nao ha como responder "quem esta logado" sem rodar no contexto
dele.

### Silencioso (GPO / SCCM)

`powershell
instalar.ps1 -Servidor ... -Codigo ... -Silencioso
`

### Desinstalar

`powershell
powershell -ExecutionPolicy Bypass -File .\desinstalar.ps1
`

Remove as tarefas e o token. **Nao remove o ativo no servidor** — apagar o
historico de um equipamento por causa de uma desinstalacao seria errado.
Para impedir novos envios, revogue o token em Administracao -> Agente Nexus.

## Pendente

- [ ] `registrar` e `enviar` (dependem do endpoint no servidor)
- [ ] DPAPI para guardar o token
- [ ] Serviço Windows (`LocalSystem`) para coletar no boot
- [ ] Tarefa agendada no logon (usuário da sessão)
- [ ] Instalador MSI com modo silencioso
- [ ] Assinatura de código (SmartScreen bloqueia sem ela)
