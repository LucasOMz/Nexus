<#
  reset.ps1 — Volta o sistema ao estado inicial (zera os dados).

  O que apaga:
    * estoque.db      -> banco de dados (ativos, usuários, movimentações, fotos…)
    * media/          -> imagens do banco de fotos, termos em PDF e anexos
    * instance/       -> arquivos auxiliares, se existirem

  O que NÃO apaga (a menos que use -Dependencias):
    * o código do sistema
    * as dependências instaladas (.venv / .vendor)

  Depois do reset o sistema recria tudo sozinho no próximo start, incluindo o
  usuário admin padrão: admin@empresa.com / admin123

  Uso:
    .\reset.ps1              # pergunta antes de apagar
    .\reset.ps1 -Forcar      # não pergunta
    .\reset.ps1 -Dependencias # também apaga .venv e .vendor (reinstala depois)
#>
param(
    [switch]$Forcar,
    [switch]$Dependencias
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host ""
Write-Host "=== RESET DO SISTEMA DE GESTAO PATRIMONIAL ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Serao APAGADOS:" -ForegroundColor Yellow
Write-Host "  - o banco de dados (estoque.db): ativos, usuarios, movimentacoes, manutencoes"
Write-Host "  - a pasta media/: fotos, termos em PDF e anexos"
if ($Dependencias) {
    Write-Host "  - .venv/ e .vendor/: dependencias instaladas (serao baixadas de novo)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Depois do reset, o sistema volta com o admin padrao:" -ForegroundColor Green
Write-Host "  usuario: admin@empresa.com    senha: admin123"
Write-Host ""

if (-not $Forcar) {
    $resposta = Read-Host 'Digite SIM para confirmar o reset'
    if ($resposta -ne "SIM") {
        Write-Host "Cancelado. Nada foi apagado." -ForegroundColor DarkGray
        exit 0
    }
}

# 1) O banco nao pode estar em uso: se o servidor estiver rodando, o reset falha.
$emUso = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq 8000 }
if ($emUso) {
    Write-Host ""
    Write-Host "ATENCAO: parece haver um servidor rodando na porta 8000." -ForegroundColor Red
    Write-Host "Feche o outro terminal (pressione CTRL+C nele) e rode o reset de novo." -ForegroundColor Red
    exit 1
}

$removidos = @()
$travados = @()

# 2) Bancos de dados.
#    O arquivo pode continuar preso por alguns segundos depois de fechar o
#    servidor (o Windows demora a liberar o handle), por isso tentamos de novo.
Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.db" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $arquivo = $_
    $apagou = $false
    for ($tentativa = 1; $tentativa -le 4 -and -not $apagou; $tentativa++) {
        try {
            Remove-Item -LiteralPath $arquivo.FullName -Force -ErrorAction Stop
            $apagou = $true
        } catch {
            if ($tentativa -lt 4) {
                Write-Host "  $($arquivo.Name) em uso, tentando novamente em 2s..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds 2
            }
        }
    }
    if ($apagou) { $removidos += $arquivo.Name } else { $travados += $arquivo.Name }
}

# 3) Arquivos gerados (fotos, termos, anexos).
foreach ($pasta in @("media", "instance")) {
    $caminho = Join-Path $PSScriptRoot $pasta
    if (Test-Path -LiteralPath $caminho) {
        try {
            Remove-Item -LiteralPath $caminho -Recurse -Force
            $removidos += "$pasta/"
        } catch {
            Write-Host "Nao foi possivel apagar $pasta/: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# 4) Dependencias (opcional).
if ($Dependencias) {
    foreach ($pasta in @(".venv", ".vendor", ".tmp")) {
        $caminho = Join-Path $PSScriptRoot $pasta
        if (Test-Path -LiteralPath $caminho) {
            try {
                Remove-Item -LiteralPath $caminho -Recurse -Force
                $removidos += "$pasta/"
            } catch {
                Write-Host "Nao foi possivel apagar $pasta/: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

Write-Host ""
if ($removidos.Count -gt 0) {
    Write-Host "Reset concluido. Removido:" -ForegroundColor Green
    $removidos | ForEach-Object { Write-Host "  - $_" }
} else {
    Write-Host "Nada para remover: o sistema ja estava zerado." -ForegroundColor Green
}

if ($travados.Count -gt 0) {
    Write-Host ""
    Write-Host "ATENCAO: nao foi possivel apagar:" -ForegroundColor Red
    $travados | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "Isso normalmente significa que o servidor ainda esta aberto." -ForegroundColor Yellow
    Write-Host "Feche o terminal onde o sistema esta rodando (CTRL+C), espere 10 segundos" -ForegroundColor Yellow
    Write-Host "e rode o reset de novo:  .\reset.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== PROXIMOS PASSOS ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1) Suba o sistema:" -ForegroundColor White
Write-Host "     .\run.ps1        (ou run.bat)" -ForegroundColor Gray
Write-Host ""
Write-Host "2) Limpe o cache do navegador (UMA vez) para ele nao usar o site antigo:" -ForegroundColor White
Write-Host "     - Jeito mais facil: abra o sistema numa JANELA ANONIMA/InPrivate" -ForegroundColor Gray
Write-Host "       (a janela anonima nao tem cache nem service worker antigos)" -ForegroundColor DarkGray
Write-Host "     - Ou, no navegador normal: abra a URL abaixo e ele se limpa sozinho:" -ForegroundColor Gray
Write-Host "         http://127.0.0.1:8000/?reset=1" -ForegroundColor Yellow
Write-Host "     - Ou, se ainda insistir: F12 -> Application -> Service Workers -> Unregister" -ForegroundColor Gray
Write-Host "                              F12 -> Application -> Storage -> Clear site data" -ForegroundColor Gray
Write-Host ""
Write-Host "3) Entre com: admin@empresa.com / admin123" -ForegroundColor White
Write-Host "   Confirme que aparece 'Versao 2.0.0' no rodape da tela de selecao." -ForegroundColor DarkGray
Write-Host ""
