<#
  build.ps1 — compila o aplicativo Nexus para Windows.

  ## Por que csc.exe, e não `dotnet build`

  Esta máquina tem o compilador do .NET Framework (parte do Windows) e **não
  tem o SDK do .NET**. O `csc.exe` compila sem instalar nada, e o .NET
  Framework 4.8 já está em qualquer Windows 10/11.

  ## O que é preciso ter na máquina de destino

  Só o **WebView2 Runtime**, que vem com o Microsoft Edge. As DLLs do
  WebView2 são copiadas para a pasta do executável, então não há instalação.

  Uso:
    .\build.ps1              # compila
    .\build.ps1 -Executar    # compila e abre
#>
param([switch]$Executar)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path $csc)) {
    throw "Compilador C# nao encontrado em $csc"
}

$lib = Join-Path $raiz "lib"
$bin = Join-Path $raiz "bin"
$src = Join-Path $raiz "src"

foreach ($dll in @("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll")) {
    if (-not (Test-Path (Join-Path $lib $dll))) {
        throw "Falta $dll em lib\. Rode o download do pacote NuGet Microsoft.Web.WebView2."
    }
}

New-Item -ItemType Directory -Force -Path $bin | Out-Null

$fontes = Get-ChildItem (Join-Path $src "*.cs") | ForEach-Object { $_.FullName }

$argumentos = @(
    "/nologo",
    "/platform:x64",          # WebView2Loader.dll desta pasta e x64
    "/target:winexe",
    "/optimize+",
    "/out:$bin\Nexus.exe",
    "/r:$lib\Microsoft.Web.WebView2.Core.dll",
    "/r:$lib\Microsoft.Web.WebView2.WinForms.dll",
    "/r:System.Windows.Forms.dll",
    "/r:System.Drawing.dll"
) + $fontes

Write-Host "Compilando $($fontes.Count) arquivo(s)..." -ForegroundColor Cyan
$saida = & $csc $argumentos 2>&1
$codigo = $LASTEXITCODE

if ($saida) { $saida | ForEach-Object { "  $_" } }

if ($codigo -ne 0) {
    Write-Host "FALHOU (exit $codigo)" -ForegroundColor Red
    exit $codigo
}

# As DLLs precisam estar ao lado do .exe: o carregador do .NET as procura
# no diretório do executável, e o WebView2Loader tambem.
Copy-Item "$lib\Microsoft.Web.WebView2.Core.dll" $bin -Force
Copy-Item "$lib\Microsoft.Web.WebView2.WinForms.dll" $bin -Force
Copy-Item "$lib\WebView2Loader.dll" $bin -Force

$exe = Join-Path $bin "Nexus.exe"
$kb = [math]::Round((Get-Item $exe).Length / 1KB)
Write-Host "OK -> $exe ($kb KB)" -ForegroundColor Green
Write-Host "     com 3 DLLs ao lado" -ForegroundColor DarkGray

if ($Executar) {
    Write-Host "Abrindo..." -ForegroundColor Cyan
    Start-Process $exe
}
