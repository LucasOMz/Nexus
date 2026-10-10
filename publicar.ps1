<#
  publicar.ps1 — monta o pacote para levar ao servidor.

  Por que não zipar a pasta inteira:
    * .vendor (145 MB) guarda extensões COMPILADAS e só funciona na mesma versão
      de Python em que foi criado — copiar para o servidor costuma dar
      "ModuleNotFoundError: pydantic_core". No servidor use .\run.ps1 -Setup.
    * .venv tem caminhos absolutos da máquina de origem: NUNCA copie.
    * __pycache__, caches e logs só engordam o pacote.

  E o que NÃO pode ficar de fora (senão há perda de dados):
    * .env                 → segredos (JWT e assinatura do QR)
    * estoque.db           → os dados
    * media/               → fotos, termos e anexos
    * backups/             → backups já gerados

  Uso:
    .\publicar.ps1                      # pacote completo (migrar servidor)
    .\publicar.ps1 -SemDados            # instalação limpa (sem dados nem .env)
    .\publicar.ps1 -Destino D:\pacotes
#>
param(
    [string]$Destino = $PSScriptRoot,
    [switch]$SemDados,
    [switch]$ComTestes
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# Pastas que nunca entram no pacote.
$EXCLUIR_DIR = @(
    ".vendor", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".git", ".github", ".tmp", "node_modules", "logs", "dist"
)
# Arquivos soltos que não entram.
$EXCLUIR_ARQ = @("*.pyc", "get-pip.py", "_*", "*.log", "diag*.db", "*.zip")

# Itens de DADOS (fora quando -SemDados).
$DADOS = @(".env", "estoque.db", "media", "backups")

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$nome = "nexus_$stamp"
if (-not (Test-Path $Destino)) { New-Item -ItemType Directory -Path $Destino | Out-Null }
$zip = Join-Path $Destino "$nome.zip"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) $nome
if (Test-Path $temp) { Remove-Item -Recurse -Force $temp }
New-Item -ItemType Directory -Path $temp | Out-Null

Write-Host "[1/4] Copiando arquivos..." -ForegroundColor Cyan
$copiados = 0
Get-ChildItem -Force | ForEach-Object {
    $item = $_
    if ($EXCLUIR_DIR -contains $item.Name) { return }
    if ($SemDados -and ($DADOS -contains $item.Name)) { return }
    if (-not $ComTestes -and $item.Name -eq "tests") { return }
    foreach ($padrao in $EXCLUIR_ARQ) {
        if ($item.Name -like $padrao) { return }
    }

    if ($item.PSIsContainer) {
        # Copia a árvore pulando caches e arquivos temporários.
        Get-ChildItem -Path $item.FullName -Recurse -File -Force | ForEach-Object {
            $rel = $_.FullName.Substring($PWD.Path.Length + 1)
            $partes = $rel -split '[\\/]'
            if ($partes | Where-Object { $EXCLUIR_DIR -contains $_ }) { return }
            $pular = $false
            foreach ($padrao in $EXCLUIR_ARQ) { if ($_.Name -like $padrao) { $pular = $true } }
            if ($pular) { return }
            $dest = Join-Path $temp $rel
            New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
            Copy-Item $_.FullName $dest -Force
            $script:copiados++
        }
    } else {
        Copy-Item $item.FullName (Join-Path $temp $item.Name) -Force
        $script:copiados++
    }
}
Write-Host "      $copiados arquivo(s)"

Write-Host "[2/4] Conferindo o essencial..." -ForegroundColor Cyan
$faltando = @()
foreach ($essencial in @("app\main.py", "frontend\index.html", "requirements.txt", "run.ps1", "run-servidor.ps1")) {
    if (-not (Test-Path (Join-Path $temp $essencial))) { $faltando += $essencial }
}
if ($faltando.Count) {
    Write-Host "      ERRO: faltam arquivos essenciais: $($faltando -join ', ')" -ForegroundColor Red
    exit 1
}

if (-not $SemDados) {
    if (-not (Test-Path (Join-Path $temp ".env"))) {
        Write-Host "      ATENCAO: .env nao existe no projeto — o servidor subira com os SEGREDOS PADRAO (inseguros)." -ForegroundColor Yellow
    }
    if (-not (Test-Path (Join-Path $temp "estoque.db"))) {
        Write-Host "      ATENCAO: estoque.db nao entrou — o servidor comeca SEM os dados." -ForegroundColor Yellow
    }
}

Write-Host "[3/4] Compactando..." -ForegroundColor Cyan
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $zip -CompressionLevel Optimal

Write-Host "[4/4] Verificando o pacote..." -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$arquivo = [System.IO.Compression.ZipFile]::OpenRead($zip)
$entradas = $arquivo.Entries.Count
$temEnv = ($arquivo.Entries | Where-Object { $_.FullName -eq ".env" }).Count -gt 0
$temDb = ($arquivo.Entries | Where-Object { $_.FullName -eq "estoque.db" }).Count -gt 0
# O Compress-Archive grava com "\" no Windows e "/" em outros sistemas.
$temMedia = ($arquivo.Entries | Where-Object { $_.FullName -like "media*" -and $_.Name }).Count
$temVendor = ($arquivo.Entries | Where-Object { $_.FullName -like ".vendor*" }).Count
$temLixo = ($arquivo.Entries | Where-Object { $_.FullName -like "*__pycache__*" -or $_.FullName -like "*\.pytest_cache*" }).Count
$arquivo.Dispose()

Remove-Item -Recurse -Force $temp

$tamanho = [math]::Round((Get-Item $zip).Length / 1MB, 1)
$textoVendor = if ($temVendor -gt 0) { "INCLUIDO (nao deveria!)" } else { "fora (correto)" }
$textoLixo = if ($temLixo -gt 0) { "$temLixo item(ns) - verifique" } else { "nenhum (correto)" }
$textoEnv = if ($temEnv) { "incluido" } else { "NAO incluido" }
$textoDb = if ($temDb) { "incluido" } else { "NAO incluido" }

Write-Host ""
Write-Host "Pacote pronto: $zip" -ForegroundColor Green
Write-Host "  tamanho      : $tamanho MB ($entradas itens)"
Write-Host "  .env         : $textoEnv"
Write-Host "  estoque.db   : $textoDb"
Write-Host "  media/       : $temMedia arquivo(s)"
Write-Host "  .vendor      : $textoVendor"
Write-Host "  caches/lixo  : $textoLixo"
Write-Host ""
Write-Host "No servidor:" -ForegroundColor Cyan
Write-Host "  1. Instale o Python 3.11+ (marcando 'Add python.exe to PATH')"
Write-Host "  2. Descompacte o pacote (ex.: C:\estoque)"
Write-Host "  3. cd C:\estoque ; .\run.ps1 -Setup        # cria o .venv"
Write-Host "  4. .\run.ps1                               # teste rapido"
Write-Host "  5. Agende o run-servidor.ps1 (ver README secao 10)"
Write-Host "  6. Libere a porta no firewall"
