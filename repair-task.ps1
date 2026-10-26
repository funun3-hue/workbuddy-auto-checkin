$ErrorActionPreference = 'Stop'
$repairLog = Join-Path $PSScriptRoot 'schedule-repair.log'
try {
    $result = & (Join-Path $PSScriptRoot 'install-windows.ps1') -Repair
    Add-Content -LiteralPath $repairLog -Value ((Get-Date -Format s) + ' OK ' + ($result -join ' '))
} catch {
    Add-Content -LiteralPath $repairLog -Value ((Get-Date -Format s) + ' FAILED: Could not verify or restore the task. Run install-windows.ps1 manually to see the setup error.')
    exit 1
}
