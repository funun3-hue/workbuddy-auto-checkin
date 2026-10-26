param([string[]]$Time=@('09:40','18:30'), [string]$PythonPath='', [switch]$Repair)
$ErrorActionPreference='Stop'
$configPath=Join-Path $PSScriptRoot 'schedule.local.json'
if ($Repair) {
    $config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $Time=$config.time; $PythonPath=$config.python
}
$Time=@($Time | Sort-Object -Unique)
if (-not $Time.Count -or @($Time | Where-Object { $_ -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$' }).Count) { throw 'Times must be HH:mm.' }
if (-not $PythonPath) {
    $PythonPath = & py -3.11 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw 'Specify -PythonPath with a working Python executable, or install Python 3.11 with the py launcher.' }
    $PythonPath=$PythonPath.Trim()
}
$PythonPath=(Resolve-Path -LiteralPath $PythonPath).Path
if ([IO.Path]::GetFileName($PythonPath) -eq 'pythonw.exe') { $PythonPath=Join-Path (Split-Path $PythonPath) 'python.exe' }
$pythonwPath=Join-Path (Split-Path $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'pythonw.exe is required for console-free execution.' }
$runnerPath=Join-Path $PSScriptRoot 'run_daily_claim.py'
# Explicitly test isolated imports without sending requests or reading credentials.
& $PythonPath -I $runnerPath --self-test
if ($LASTEXITCODE -ne 0) { throw 'Offline runtime self-test failed; task was not installed.' }
$taskName='WorkBuddy Daily Check-in'
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$expectedArgs='"'+$runnerPath+'"'
$matches=$task -and $task.Actions.Count -eq 1 -and $task.Actions[0].Execute -eq $pythonwPath -and $task.Actions[0].Arguments -eq $expectedArgs -and $task.State -ne 'Disabled' -and @($task.Triggers).Count -eq $Time.Count -and @($task.Triggers | Where-Object { $_.DaysInterval -eq 1 -and $_.Enabled -and ([datetime]$_.StartBoundary).ToString('HH:mm') -in $Time }).Count -eq $Time.Count
if (-not $Repair -or -not $matches) {
    $action=New-ScheduledTaskAction -Execute $pythonwPath -Argument $expectedArgs -WorkingDirectory $PSScriptRoot
    $trigger=@($Time | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
    $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Daily WorkBuddy API check-in and growth-center rewards; silent.' -Force | Out-Null
}
if (-not $Repair) {
    @{time=$Time;python=$PythonPath} | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
    $startup=[Environment]::GetFolderPath('Startup')
    $psScript=(Join-Path $PSScriptRoot 'repair-task.ps1').Replace('"','""')
    $vbs='CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""'+$psScript+'""", 0, False'
    [IO.File]::WriteAllText((Join-Path $startup 'WorkBuddy API Check-in Repair.vbs'),$vbs,[Text.Encoding]::Unicode)
}
$installed=Get-ScheduledTask -TaskName $taskName
if ($installed.Actions[0].Arguments -ne $expectedArgs) { throw 'Installed task verification failed.' }
$installedTimes=@($installed.Triggers | ForEach-Object { ([datetime]$_.StartBoundary).ToString('HH:mm') } | Sort-Object)
if (@(Compare-Object $Time $installedTimes).Count) { throw 'Installed trigger verification failed.' }
Write-Output "Verified daily check-in and growth-center task at $($Time -join ', ')."
