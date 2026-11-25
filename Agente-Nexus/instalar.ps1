[CmdletBinding()]
param(
    [string]$Servidor,
    [string]$Codigo,
    [int]$IntervaloHoras = 12, # Compatibilidade com implantações existentes.
    [switch]$Silencioso,
    [switch]$SemTarefaDeLogon,
    [switch]$Atualizar
)

$ErrorActionPreference = 'Stop'
$nomeServico = 'NexusAgente'
$destino = Join-Path $env:ProgramData 'Nexus'
$executavel = Join-Path $destino 'agente.exe'
$chaveServico = "HKLM:\SYSTEM\CurrentControlSet\Services\$nomeServico"
$chaveUninstall = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$nomeServico"

function Invocar-Agente {
    param([string[]]$Argumentos)
    $ErrorActionPreference = 'Continue'
    $null = & $executavel @Argumentos 2>&1
    return $LASTEXITCODE
}

function Parar-ProcessosAgente {
    Get-Process -Name 'agente' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $executavel } | Stop-Process -Force
}

$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Execute o instalador como Administrador ou SYSTEM.'
}

if (-not $Servidor) { $Servidor = $env:NEXUS_SETUP_SERVIDOR }
if (-not $Codigo) { $Codigo = $env:NEXUS_SETUP_CODIGO }
$origemExe = Join-Path $PSScriptRoot 'bin\agente.exe'
if (-not (Test-Path -LiteralPath $origemExe -PathType Leaf)) { $origemExe = Join-Path $PSScriptRoot 'agente.exe' }
$origemDesinstalador = Join-Path $PSScriptRoot 'desinstalar.ps1'
foreach ($arquivo in @($origemExe, $origemDesinstalador)) {
    if (-not (Test-Path -LiteralPath $arquivo -PathType Leaf)) {
        throw "Pacote incompleto. Arquivo ausente: $(Split-Path -Leaf $arquivo)."
    }
}

$imagem = '"{0}" --servico' -f $executavel
$existente = Get-Service -Name $nomeServico -ErrorAction SilentlyContinue
if ($existente) {
    $imagemExistente = Get-ItemPropertyValue -LiteralPath $chaveServico -Name ImagePath
    if ($imagemExistente -notin @($imagem, "$executavel --servico")) {
        throw 'O serviço pertence a outra instalação do Nexus. Use o tipo de pacote da instalação original.'
    }
}
if ($Atualizar -and -not $existente) {
    throw 'Nenhuma instalação do pacote EXE foi encontrada. Para instalar, informe o servidor e o código.'
}

$config = Join-Path $destino 'agente.json'
$configExistia = Test-Path -LiteralPath $config -PathType Leaf
if ($configExistia) {
    $configAtual = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    if (-not $configAtual.Servidor) { throw 'A configuração atual está incompleta. Verifique agente.json.' }
    if ($Servidor -and $Servidor.TrimEnd('/') -ne ([string]$configAtual.Servidor).TrimEnd('/')) {
        throw 'O servidor informado difere do cadastro atual. Use o endereço já cadastrado para atualizar.'
    }
} else {
    $url = $null
    if (-not [Uri]::TryCreate($Servidor, [UriKind]::Absolute, [ref]$url) -or
        $url.Scheme -notin @('http', 'https') -or -not $url.Host -or $url.UserInfo -or $url.Query -or $url.Fragment -or
        [string]::IsNullOrWhiteSpace($Codigo)) {
        throw 'A primeira vinculação exige o endereço HTTP(S) do Nexus e um código de instalação.'
    }
}

$origens = [ordered]@{'agente.exe' = $origemExe; 'desinstalar.ps1' = $origemDesinstalador}
$arquivosAlterados = @{}
$servicoCriado = $false
$servicoParado = $false
$estavaRodando = $existente -and $existente.Status -ne 'Stopped'
$entradaExistia = Test-Path -LiteralPath $chaveUninstall
$pendente = $false
New-Item -ItemType Directory -Path $destino -Force | Out-Null
try {
    if ($estavaRodando) {
        $servicoParado = $true
        Stop-Service -InputObject $existente
        $existente.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    }
    Parar-ProcessosAgente

    foreach ($nome in $origens.Keys) {
        $arquivo = Join-Path $destino $nome
        $backup = $null
        if (Test-Path -LiteralPath $arquivo -PathType Leaf) {
            $backup = "$arquivo.$([Guid]::NewGuid().ToString('N')).bak"
            Copy-Item -LiteralPath $arquivo -Destination $backup
        }
        $arquivosAlterados[$arquivo] = $backup
        Copy-Item -LiteralPath $origens[$nome] -Destination $arquivo -Force
    }

    if (-not $configExistia) {
        $codigoRegistro = Invocar-Agente @('registrar', '--servidor', $Servidor, '--codigo', $Codigo)
        if ($codigoRegistro -notin @(0, 3) -or -not (Test-Path -LiteralPath $config -PathType Leaf)) {
            throw "Falha ao gravar o vínculo do agente (código de saída $codigoRegistro)."
        }
        $pendente = $codigoRegistro -eq 3
    }

    if (-not $existente) {
        $parametrosServico = @{
            Name = $nomeServico; BinaryPathName = $imagem; StartupType = 'Automatic'
            DisplayName = 'Nexus Agente'; Description = 'Coleta o inventário desta máquina e envia ao Nexus.'
        }
        New-Service @parametrosServico | Out-Null
        $servicoCriado = $true
        $resultadoSc = & sc.exe failure $nomeServico reset= 86400 actions= restart/60000/restart/60000/restart/60000
        if ($LASTEXITCODE -ne 0) { throw "Falha ao configurar a recuperação do serviço: $resultadoSc" }
    }

    Start-Service -Name $nomeServico
    $servico = Get-Service -Name $nomeServico
    try { $servico.WaitForStatus('Running', [TimeSpan]::FromSeconds(45)) }
    finally { $servico.Dispose() }

    if (-not $entradaExistia) { New-Item -Path $chaveUninstall -Force | Out-Null }
    $comando = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f (Join-Path $destino 'desinstalar.ps1')
    $propriedades = @{
        DisplayName = 'Nexus Agente'; DisplayVersion = '1.0.1'; Publisher = 'Nexus'
        InstallLocation = $destino; DisplayIcon = $executavel
        UninstallString = $comando; QuietUninstallString = "$comando -Silencioso"
    }
    foreach ($nome in $propriedades.Keys) {
        New-ItemProperty -LiteralPath $chaveUninstall -Name $nome -Value $propriedades[$nome] -PropertyType String -Force | Out-Null
    }
    foreach ($nome in @('NoModify', 'NoRepair')) {
        New-ItemProperty -LiteralPath $chaveUninstall -Name $nome -Value 1 -PropertyType DWord -Force | Out-Null
    }
} catch {
    $falha = $_
    try {
        if ($servicoCriado -or ($existente -and $arquivosAlterados.Count -gt 0)) {
            $servico = Get-Service -Name $nomeServico -ErrorAction SilentlyContinue
            if ($servico) {
                try {
                    if ($servico.Status -ne 'Stopped') {
                        Stop-Service -InputObject $servico
                        $servico.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
                    }
                } finally { $servico.Dispose() }
            }
        }
        if ($servicoCriado) {
            & sc.exe delete $nomeServico | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao remover o serviço recém-criado.' }
        }
        if ($arquivosAlterados.Count -gt 0) { Parar-ProcessosAgente }
        foreach ($arquivo in $arquivosAlterados.Keys) {
            if ($arquivosAlterados[$arquivo]) {
                Move-Item -LiteralPath $arquivosAlterados[$arquivo] -Destination $arquivo -Force
            } elseif (Test-Path -LiteralPath $arquivo) {
                Remove-Item -LiteralPath $arquivo -Force
            }
        }
        if (-not $configExistia -and (Test-Path -LiteralPath $config)) { Remove-Item -LiteralPath $config -Force }
        if (-not $entradaExistia -and (Test-Path -LiteralPath $chaveUninstall)) { Remove-Item -LiteralPath $chaveUninstall -Force }
        if ($servicoParado) { Start-Service -Name $nomeServico }
    } catch {
        throw "Falha na instalação: $falha. Falha ao restaurar a instalação anterior: $_"
    }
    throw $falha
} finally {
    if ($existente) { $existente.Dispose() }
}

foreach ($backup in $arquivosAlterados.Values) {
    if ($backup) { Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue }
}

if (-not $existente -and -not $SemTarefaDeLogon) {
    try {
        $acao = New-ScheduledTaskAction -Execute $executavel -Argument 'enviar'
        $gatilho = New-ScheduledTaskTrigger -AtLogOn
        $conta = New-ScheduledTaskPrincipal -GroupId 'S-1-5-32-545' -RunLevel Limited
        Register-ScheduledTask -TaskName 'Nexus Agente - Logon' -Action $acao -Trigger $gatilho -Principal $conta -Force | Out-Null
    } catch {
        Write-Warning 'Tarefa de logon não criada. O serviço continua coletando normalmente.'
    }
}
if (-not $configExistia -and -not $pendente -and (Invocar-Agente @('enviar')) -ne 0) {
    Write-Warning 'O primeiro envio falhou. O serviço tentará novamente.'
}
if (-not $Silencioso) {
    if ($pendente) { Write-Host 'Agente instalado. A vinculação com o Nexus ainda está pendente.' }
    else { Write-Host 'Agente Nexus instalado e com o serviço em execução.' }
}
