<#
  run.ps1 — Sobe o sistema de Gestão Patrimonial (API + frontend PWA).

  Uso:
    .\run.ps1                # porta 8000
    .\run.ps1 -Port 9000     # outra porta
    .\run.ps1 -Setup         # apenas prepara o ambiente, sem subir

  O script escolhe automaticamente o ambiente, nesta ordem:
    1) .venv        — ambiente virtual já pronto (recomendado)
    2) .vendor      — dependências pré-instaladas neste projeto
    3) cria o .venv e instala as dependências
#>
param(
    [int]$Port = 8000,
    # 0.0.0.0 = aceita acesso da rede (igual ao run.sh e ao run-servidor.ps1).
    # Use -Local para restringir a este computador.
    [string]$Bind = "0.0.0.0",
    [switch]$Local,
    [switch]$Setup
)

if ($Local) { $Bind = "127.0.0.1" }

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvPy  = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvPip = Join-Path $PSScriptRoot ".venv\Scripts\pip.exe"
$vendor  = Join-Path $PSScriptRoot ".vendor"

function New-Venv {
    $sys = Get-Python
    if (-not $sys) {
        throw @"
Python nao encontrado.

Instale o Python 3.11 ou superior em https://www.python.org/downloads/
e MARQUE a opcao "Add python.exe to PATH" durante a instalacao.
Depois rode:  .\run.ps1 -Setup
"@
    }
    Write-Host "[setup] Criando ambiente virtual .venv ..." -ForegroundColor Cyan
    & $sys -m venv .venv

    # Alguns Pythons (Microsoft Store) vem sem ensurepip: o venv fica sem pip.
    if (-not (Test-Path $venvPip)) {
        Write-Host "[setup] pip ausente no venv; instalando via get-pip.py ..." -ForegroundColor Yellow
        $tmp = Join-Path $PSScriptRoot "get-pip.py"
        Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $tmp -UseBasicParsing
        & $venvPy $tmp
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }

    Write-Host "[setup] Instalando dependencias (requirements.txt) ..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

    # Drivers OPCIONAIS de banco (MySQL ja vem no principal; aqui e o SQL Server).
    # A falha NAO interrompe: sao opcionais e o pyodbc precisa compilar no Linux.
    # Sem esta tolerancia, quem nao usa SQL Server ficaria sem sistema nenhum.
    $drivers = Join-Path $PSScriptRoot "requirements-drivers.txt"
    if (Test-Path $drivers) {
        Write-Host "[setup] Instalando drivers opcionais de banco ..." -ForegroundColor DarkGray
        try {
            & $venvPy -m pip install -r $drivers --quiet
            if ($LASTEXITCODE -ne 0) { throw "pip retornou $LASTEXITCODE" }
            Write-Host "        ok" -ForegroundColor DarkGray
        } catch {
            Write-Host "        nao instalados (opcional). O MySQL ja funciona;" -ForegroundColor DarkGray
            Write-Host "        para SQL Server:  $venvPy -m pip install -r requirements-drivers.txt" -ForegroundColor DarkGray
        }
    }
}

<#
  Descobre um Python utilizavel. A ordem importa:

    1) .venv do projeto (criado por -Setup) — o mais confiavel
    2) Python do PATH (py / python3 / python)

  O runtime que acompanha o DSH entra no fim, apenas para o ambiente de
  desenvolvimento original; em qualquer outro servidor ele simplesmente não
  existe e a lista segue em frente.
#>
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

<# As dependencias portateis (.vendor) so carregam se a versao do Python for
   compativel — elas trazem extensoes compiladas (ex.: pydantic_core).

   IMPORTANTE: o Python escreve o ModuleNotFoundError no stderr, e no Windows
   PowerShell 5.1 isso vira erro TERMINANTE quando ErrorActionPreference=Stop.
   Por isso aqui a preferencia e relaxada e tudo e descartado com *>. #>
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

<# Qualquer Python utilizavel (para criar o .venv). #>
function Get-Python {
    foreach ($c in (Get-CandidatosPython)) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

<# Python COMPATIVEL com o .vendor: testa de verdade se as dependencias importam.
   E isso que faz o script escolher a versao certa quando ha mais de uma
   instalada (ex.: 3.13 do PATH e 3.12 que gerou o .vendor). #>
function Get-PythonCompativel {
    $testados = @()
    foreach ($c in (Get-CandidatosPython)) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        $versao = (& $c --version) 2>&1
        $testados += "$versao ($c)"
        if (Test-Dependencias $c) { return $c }
    }
    Write-Host "[run] Pythons testados:" -ForegroundColor DarkGray
    foreach ($t in $testados) { Write-Host "        $t" -ForegroundColor DarkGray }
    return $null
}

# --- 1) ambiente virtual pronto -------------------------------------------
if (Test-Path $venvPy) {
    Write-Host "[run] Usando ambiente virtual .venv" -ForegroundColor Green
    $python = $venvPy
}
# --- 2) dependencias locais .vendor ---------------------------------------
elseif (Test-Path $vendor) {
    $env:PYTHONPATH = $vendor
    $python = Get-PythonCompativel
    if (-not $python) {
        throw @"
As dependencias em .vendor nao carregam em nenhum Python desta maquina.

O .vendor guarda extensoes compiladas e so funciona na MESMA versao de Python
em que foi criado (normalmente acontece ao copiar a pasta para outro servidor).

Solucao:
    .\run.ps1 -Setup

Isso cria um ambiente .venv proprio desta maquina, com as dependencias certas.
(precisa de Python 3.11+ instalado e conexao com a internet)
"@
    }
    Write-Host "[run] Usando dependencias locais .vendor com $(& $python --version 2>&1)" -ForegroundColor Green
}
# --- 3) cria o ambiente ----------------------------------------------------
else {
    $python = Get-Python
    if (-not $python) {
        throw "Nenhum Python encontrado. Instale o Python 3.11+ (marcando 'Add python.exe to PATH') e rode: .\run.ps1 -Setup"
    }
    New-Venv
    $python = $venvPy
}

if ($Setup) {
    Write-Host "[ok] Ambiente pronto. Rode:  .\run.ps1" -ForegroundColor Green
    exit 0
}

# Endereços IP desta máquina na rede local (para mostrar a URL correta).
$ipsLocais = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
)

<#
  Verificação de firewall (melhor esforço, precisa ser RÁPIDA).

  O Windows bloqueia conexões de OUTRAS máquinas por padrão. Aqui procuramos
  alguma regra de entrada habilitada que libere o programa (python.exe) ou a
  porta — foi exatamente o que faltou quando o acesso pelo IP não funcionou.

  IMPORTANTE: consultar as regras em LOTE. Fazer Get-NetFirewallApplicationFilter
  dentro de um laço sobre todas as regras gera centenas de consultas WMI e
  TRAVA a inicialização (leva minutos). #>
function Test-FirewallLiberado($porta, $exe) {
    try {
        $filtrosApp = Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue |
            Where-Object { $_.Program -and $exe -and ($_.Program -ieq $exe) }
        foreach ($filtro in $filtrosApp) {
            foreach ($regra in (Get-NetFirewallRule -AssociatedNetFirewallApplicationFilter $filtro -ErrorAction SilentlyContinue)) {
                if ($regra.Enabled -eq 'True' -and $regra.Direction -eq 'Inbound' -and $regra.Action -eq 'Allow') { return $true }
            }
        }

        $filtrosPorta = Get-NetFirewallPortFilter -ErrorAction SilentlyContinue |
            Where-Object { @($_.LocalPort) -contains "$porta" }
        foreach ($filtro in $filtrosPorta) {
            foreach ($regra in (Get-NetFirewallRule -AssociatedNetFirewallPortFilter $filtro -ErrorAction SilentlyContinue)) {
                if ($regra.Enabled -eq 'True' -and $regra.Direction -eq 'Inbound' -and $regra.Action -eq 'Allow') { return $true }
            }
        }
    } catch { }
    return $false
}

Write-Host ""
Write-Host "  Gestao Patrimonial" -ForegroundColor Cyan
Write-Host "    Neste computador :  http://127.0.0.1:$Port"

if ($Bind -eq "0.0.0.0" -or $Bind -eq "*" -or $Bind -eq "+") {
    foreach ($ip in $ipsLocais) { Write-Host "    Na rede local    :  http://${ip}:$Port" -ForegroundColor Green }
    if (-not $ipsLocais) { Write-Host "    (nenhum IP de rede local encontrado)" -ForegroundColor DarkGray }

    if (-not (Test-FirewallLiberado $Port $python)) {
        Write-Host ""
        Write-Host "  ATENCAO: nao encontrei regra de firewall liberando esta porta." -ForegroundColor Yellow
        Write-Host "  Se outra maquina (ou o celular) nao conseguir abrir, rode como" -ForegroundColor Yellow
        Write-Host "  Administrador:" -ForegroundColor Yellow
        Write-Host "      New-NetFirewallRule -DisplayName 'Gestao Patrimonial' ``" -ForegroundColor White
        Write-Host "          -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow" -ForegroundColor White
    } else {
        Write-Host "    Firewall         :  regra de entrada encontrada (ok)" -ForegroundColor DarkGray
    }
} else {
    Write-Host ""
    Write-Host "  Modo restrito: escutando apenas em $Bind." -ForegroundColor Yellow
    Write-Host "  Outras maquinas NAO acessam. Para liberar, rode sem -Local:" -ForegroundColor Yellow
    Write-Host "      .\run.ps1" -ForegroundColor White
}

Write-Host ""
# A mensagem de login depende do estado da instalacao. Prometer
# "admin@empresa.com / admin123" depois do setup mandaria a pessoa tentar um
# login que nao existe mais -- o assistente cria o administrador dela.
if (Test-Path (Join-Path $PSScriptRoot ".instalado")) {
    Write-Host "  Login: use o usuario administrador que voce cadastrou" -ForegroundColor DarkGray
} else {
    Write-Host "  PRIMEIRA EXECUCAO -- o sistema precisa ser configurado." -ForegroundColor Yellow
    Write-Host "  Abra o assistente em:" -ForegroundColor Yellow
    Write-Host "      http://127.0.0.1:$Port/instalacao" -ForegroundColor Green
}
Write-Host "  Encerrar: CTRL + C" -ForegroundColor DarkGray
Write-Host ""

& $python -m uvicorn app.main:app --host $Bind --port $Port
