# Compila o Agente Nexus e o instalador — sem SDK.
#
# ## Por que não MSBuild / dotnet
#
# O alvo é Windows 10 e 11 de parque corporativo. O compilador que **já
# existe** em qualquer instalação é o `csc.exe` do Framework 4.0 — em
# `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319`. Sem SDK, sem NuGet, sem
# Runtime adicional para distribuir.
#
# A limitação: é **C# 5**. Sem interpolação de string, sem membros de
# expressão, sem `nameof`.
#
# ## Dois arquivos, um público
#
#   bin\agente.exe              UM binário para todos os modos:
#                                 (sem argumento) bandeja
#                                 --servico       serviço
#                                 coletar / registrar / enviar
#
#   dist\nexus-agente-setup.exe O ÚNICO que o técnico abre.
#                               Embute o agente e o instalar.ps1.
#
# Antes existiam três binários e nenhum era obviamente "o de instalar".
# Agora é um só, e o resto é matéria-prima.
#
# ## Se o Windows bloquear o script
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1

param(
    [switch]$Rodar
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $raiz "src"

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path $csc)) {
    throw "csc.exe nao encontrado. Este script exige o .NET Framework 4.0 ou superior."
}

$bin = Join-Path $raiz "bin"
$dist = Join-Path $raiz "dist"
foreach ($pasta in @($bin, $dist)) {
    if (-not (Test-Path $pasta)) { New-Item -ItemType Directory -Path $pasta | Out-Null }
}

$fontes = @(
    (Join-Path $src "Program.cs"),
    (Join-Path $src "Configuracao.cs"),
    (Join-Path $src "Servico.cs"),
    (Join-Path $src "Bandeja.cs"),
    (Join-Path $src "ConsoleSobDemanda.cs"),
    (Join-Path $src "Tema.cs"),
    (Join-Path $src "BandejaNaSessao.cs"),
    (Join-Path $src "Privilegio.cs"),
    (Join-Path $src "ColetorSoftware.cs")
)
foreach ($f in $fontes) {
    if (-not (Test-Path $f)) { throw "Fonte ausente: $f" }
}

# =====================================================================
# 1. Agente — um binário, todos os modos
# =====================================================================
$exeAgente = Join-Path $bin "agente.exe"
# Icone embutido no .exe: e o que o Windows mostra ao procurar o arquivo, e
# o que aparece na barra de tarefas.
$icone = Join-Path $raiz "installer\nexus.ico"
# Exige elevacao: a configuracao vive em %ProgramData% e o token usa DPAPI de
# maquina — gravar sem elevacao e depois nao conseguir decifrar seria pior.
$manifesto = Join-Path $src "agente.manifest"

& $csc /nologo /target:winexe /main:AgenteNexus.Programa "/win32icon:$icone" "/win32manifest:$manifesto" "/out:$exeAgente" /platform:anycpu /optimize+ `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Management.dll `
    /reference:System.Web.Extensions.dll `
    /reference:System.Security.dll `
    /reference:System.ServiceProcess.dll `
    /reference:System.Windows.Forms.dll `
    /reference:System.Drawing.dll `
    $fontes
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o agente (codigo $LASTEXITCODE)." }
Write-Host "[ok] $exeAgente  ($([math]::Round((Get-Item $exeAgente).Length / 1KB, 1)) KB)"

# =====================================================================
# 2. Instalador (embute o agente e o script)
# =====================================================================
$exeSetup = Join-Path $dist "nexus-agente-setup.exe"
$scriptInstalar = Join-Path $raiz "instalar.ps1"
$scriptDesinstalar = Join-Path $raiz "desinstalar.ps1"
$manifesto = Join-Path $src "setup.manifest"

if (-not (Test-Path $scriptInstalar)) { throw "instalar.ps1 ausente." }
if (-not (Test-Path $scriptDesinstalar)) { throw "desinstalar.ps1 ausente." }

& $csc /nologo /target:winexe "/out:$exeSetup" /platform:anycpu /optimize+ `
    "/win32manifest:$manifesto" `
    "/resource:$exeAgente,agente.exe" `
    "/resource:$scriptInstalar,instalar.ps1" `
    "/resource:$scriptDesinstalar,desinstalar.ps1" `
    /reference:System.dll /reference:System.Core.dll `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    (Join-Path $src "Instalador.cs")
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar o instalador (codigo $LASTEXITCODE)." }
Write-Host "[ok] $exeSetup  ($([math]::Round((Get-Item $exeSetup).Length / 1KB, 1)) KB)"

Write-Host ""
Write-Host "Distribua apenas: dist\nexus-agente-setup.exe"
Write-Host ""
Write-Host "Instalacao silenciosa:"
Write-Host "  nexus-agente-setup.exe /S SERVER=http://ip:4545 CODIGO=AAAA-BBBB-CCCC"
Write-Host "Atualizacao silenciosa:"
Write-Host "  nexus-agente-setup.exe /S /ATUALIZAR"

if ($Rodar) {
    Write-Host ""
    & $exeAgente coletar
}
