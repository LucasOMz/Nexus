# Desinstala o pacote EXE local. O ativo fica no inventário do servidor.
[CmdletBinding()]
param([switch]$ManterToken, [switch]$Silencioso)

$ErrorActionPreference = 'Stop'
$nomeServico = 'NexusAgente'
$destino = Join-Path $env:ProgramData 'Nexus'
$executavel = Join-Path $destino 'agente.exe'
$chaveServico = "HKLM:\SYSTEM\CurrentControlSet\Services\$nomeServico"
$chaveUninstall = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$nomeServico"

$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute o desinstalador como Administrador ou SYSTEM.'
}

$servico = Get-Service -Name $nomeServico -ErrorAction SilentlyContinue
if ($servico) {
    try {
        $imagem = Get-ItemPropertyValue -LiteralPath $chaveServico -Name ImagePath
        if ($imagem -notin @(('"{0}" --servico' -f $executavel), "$executavel --servico")) {
            throw 'O serviço pertence a outra instalação do Nexus. Remova-o pelo instalador original.'
        }
        if ($servico.Status -ne 'Stopped') {
            Stop-Service -InputObject $servico
            $servico.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
        }
    } finally { $servico.Dispose() }

    & sc.exe delete $nomeServico | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao remover o serviço NexusAgente.' }
}

$legado = Join-Path $destino 'nexus-agente-bandeja.exe'
Get-Process -Name 'agente', 'nexus-agente-bandeja' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -in @($executavel, $legado) } | Stop-Process -Force

foreach ($nome in @('Nexus Agente - Logon', 'Nexus Agente')) {
    if (Get-ScheduledTask -TaskPath '\' -TaskName $nome -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskPath '\' -TaskName $nome -Confirm:$false
    }
}

$chaveRun = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
if (Get-ItemProperty -LiteralPath $chaveRun -Name $nomeServico -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -LiteralPath $chaveRun -Name $nomeServico
}

$arquivos = @('agente.exe', 'nexus-agente-bandeja.exe', 'desinstalar.ps1', 'software.json', 'estado.json', 'servico.log', 'servico.log.1')
if (-not $ManterToken) { $arquivos += 'agente.json' }
foreach ($nome in $arquivos) {
    $arquivo = Join-Path $destino $nome
    if (Test-Path -LiteralPath $arquivo -PathType Leaf) { Remove-Item -LiteralPath $arquivo -Force }
}
if (Test-Path -LiteralPath $chaveUninstall) { Remove-Item -LiteralPath $chaveUninstall -Force }

if (-not $Silencioso) {
    Write-Host 'Agente Nexus desinstalado. O ativo continua no inventário do servidor.'
    if ($ManterToken) { Write-Host 'O vínculo local foi mantido para reinstalação.' }
}
