<#
  run-servidor.ps1 — roda o sistema como SERVIÇO (Agendador de Tarefas / NSSM).

  Diferenças em relação ao run.ps1 (que é para uso manual):

    * NÃO tem `pause` — o run.bat para e espera tecla, o que travaria a tarefa.
    * Escuta em 0.0.0.0 (aceita acesso de outras máquinas da rede).
    * Grava log em arquivo (logs\servidor-AAAA-MM-DD.log).
    * Reinicia sozinho se o processo cair (com espera crescente).

  Uso:
    .\run-servidor.ps1                      # porta 8000, todas as interfaces
    .\run-servidor.ps1 -Port 8080
    .\run-servidor.ps1 -Bind 127.0.0.1      # só esta máquina
    .\run-servidor.ps1 -SemReinicio         # não reinicia se cair (debug)

  Agendador de Tarefas (execute como Administrador):
    $acao  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\caminho\run-servidor.ps1"' `
             -WorkingDirectory "C:\caminho"
    $gatilho = New-ScheduledTaskTrigger -AtStartup
    $conf  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
             -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
             -ExecutionTimeLimit (New-TimeSpan -Days 0)
    Register-ScheduledTask -TaskName "GestaoPatrimonial" -Action $acao -Trigger $gatilho `
             -Settings $conf -User "SYSTEM" -RunLevel Highest
#>
param(
    [int]$Port = 8000,
    [string]$Bind = "0.0.0.0",
    [switch]$SemReinicio
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("servidor-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

function Escrever-Log($mensagem) {
    $linha = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $mensagem
    Write-Host $linha
    Add-Content -LiteralPath $logFile -Value $linha -Encoding UTF8
}

# --- Segredos: precisam existir, senão as etiquetas/tokens quebram -----------
# Vale tanto variável de ambiente quanto o arquivo .env (que a aplicação lê).
$temEnv = Test-Path (Join-Path $PSScriptRoot ".env")
if (-not $env:JWT_SECRET -and -not $temEnv) {
    Escrever-Log "AVISO: JWT_SECRET nao definido (nem em variavel de ambiente, nem no .env)."
    Escrever-Log "AVISO: o sistema vai usar o segredo PADRAO do codigo, que e publico. Gere um .env antes de expor na rede."
}
if (-not $env:QR_HMAC_SECRET -and -not $temEnv) {
    Escrever-Log "AVISO: QR_HMAC_SECRET nao definido. Sem ele, as etiquetas impressas podem deixar de ser lidas."
}
if ($temEnv) { Escrever-Log "[start] usando segredos do arquivo .env" }

# --- Ambiente Python (mesma ordem do run.ps1) --------------------------------
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$vendor = Join-Path $PSScriptRoot ".vendor"

function Get-CandidatosPython {
    $candidatos = @()
    foreach ($cmd in @("py", "python", "python3")) {
        $exe = (Get-Command $cmd -ErrorAction SilentlyContinue).Source
        if ($exe -and -not ($candidatos -contains $exe)) { $candidatos += $exe }
    }
    # Runtime do ambiente de desenvolvimento original (não existe no servidor).
    $dev = "C:\Users\Lucas\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $dev) { $candidatos += $dev }
    return $candidatos
}

<# O Python escreve o ModuleNotFoundError no stderr, e no Windows PowerShell 5.1
   isso vira erro TERMINANTE com ErrorActionPreference=Stop. Por isso aqui a
   preferência é relaxada e tudo é descartado com *>. #>
function Test-Dependencias($python) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        & $python -c "import pydantic_core" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $anterior
    }
}

<# Escolhe um Python que REALMENTE carregue as dependências do .vendor. #>
function Get-PythonCompativel {
    $testados = @()
    foreach ($c in (Get-CandidatosPython)) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        $versao = (& $c --version) 2>&1
        $testados += "$versao"
        if (Test-Dependencias $c) { return $c }
    }
    Escrever-Log "[erro] Pythons testados sem sucesso: $($testados -join ' | ')"
    return $null
}

if (Test-Path $venvPy) {
    $python = $venvPy
    Escrever-Log "[start] ambiente: .venv"
} elseif (Test-Path $vendor) {
    $env:PYTHONPATH = $vendor
    $python = Get-PythonCompativel
    if (-not $python) {
        Escrever-Log "[erro] .vendor incompativel com os Pythons desta maquina."
        Escrever-Log "[erro] Rode .\run.ps1 -Setup para criar o .venv desta maquina."
        exit 1
    }
    Escrever-Log "[start] ambiente: .vendor com $(& $python --version 2>&1)"
} else {
    Escrever-Log "[erro] Nenhum ambiente encontrado. Rode .\run.ps1 -Setup primeiro."
    exit 1
}

Escrever-Log "[start] versao do Python: $(& $python --version 2>&1)"
Escrever-Log "[start] servindo em http://${Bind}:${Port}  (log: $logFile)"

# O uvicorn escreve o log dele no stderr. No Windows PowerShell 5.1, com
# ErrorActionPreference=Stop, a primeira linha vira erro TERMINANTE e o script
# morre logo apos iniciar o servidor. Aqui a preferencia e relaxada de proposito.
$ErrorActionPreference = "Continue"

$tentativa = 0
while ($true) {
    $tentativa++
    Escrever-Log "[run] iniciando uvicorn (tentativa $tentativa)"

    & $python -m uvicorn app.main:app --host $Bind --port $Port 2>&1 |
        ForEach-Object { Add-Content -LiteralPath $logFile -Value $_ -Encoding UTF8 }

    $codigo = $LASTEXITCODE
    Escrever-Log "[run] uvicorn encerrou com codigo $codigo"

    if ($SemReinicio) { exit $codigo }

    # Espera crescente, limitada a 60s, para não martelar em caso de erro fixo.
    $espera = [Math]::Min(60, 5 * $tentativa)
    Escrever-Log "[run] reiniciando em $espera s"
    Start-Sleep -Seconds $espera
}
