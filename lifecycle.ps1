param([ValidateSet('WorkBuddy')][string]$App='WorkBuddy', [string]$PythonPath, [switch]$InspectOnly)
$ErrorActionPreference='Stop'
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { throw 'Pass -PythonPath with the current Python interpreter.' }
$python=$PythonPath
if ([IO.Path]::GetFileName($python) -eq 'pythonw.exe') { $python=Join-Path (Split-Path $python) 'python.exe' }
$root=$PSScriptRoot
$log=Join-Path $root ($App+'.log')
function Write-Log([string]$message) { Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss')+' '+$message) }
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class CheckinWindow {
 public delegate bool Callback(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback cb, IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h,int n);
 public static IntPtr[] Windows(int[] ids) {
  var list=new List<IntPtr>();
  EnumWindows((h,l)=>{uint p;GetWindowThreadProcessId(h,out p);if(Array.IndexOf(ids,(int)p)>=0 && IsWindowVisible(h))list.Add(h);return true;},IntPtr.Zero);
  return list.ToArray();
 }
}
'@
$exe=Join-Path $env:LOCALAPPDATA 'Programs\WorkBuddy\WorkBuddy.exe'
function Get-AppProcesses {
    @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -eq $exe -or $_.ExecutablePath.StartsWith((Split-Path $exe)+'\',[StringComparison]::OrdinalIgnoreCase)) })
}
function Get-Windows { $ids=[int[]]@(Get-AppProcesses | ForEach-Object {$_.ProcessId}); [CheckinWindow]::Windows($ids) }
function Test-Idle {
    & $python (Join-Path $root 'busy.py') $App
    return ($LASTEXITCODE -eq 0)
}
function Test-RestartAllowed {
    return (Test-Idle)
}
function Close-App([switch]$OwnedLaunch) {
    if (-not $OwnedLaunch -and -not (Test-RestartAllowed)) { throw 'Termination deferred: active or unconfirmed task state.' }
    # Terminate matching installed executables, including background helpers.
    # Repeat boundedly to catch helpers respawned while the main process exits.
    for ($pass=0; $pass -lt 5; $pass++) {
        $remaining=@(Get-AppProcesses)
        if (-not $remaining.Count) { break }
        foreach ($proc in $remaining) {
            $live=Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
            if ($live -and $live.Path -eq $proc.ExecutablePath) {
                try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop }
                catch { if (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue) { throw } }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    Start-Sleep -Seconds 1
    if (@(Get-AppProcesses).Count) { throw 'App processes remain; restart aborted.' }
}
$mutex=New-Object Threading.Mutex($false,('Local\AgentDailyCheckin-'+$App))
if (-not $mutex.WaitOne(0)) { $mutex.Dispose(); exit 0 }
$started=$false
$wasOpen=$false
$state='closed'
$result=1
try {
    if (-not (Test-Path $exe)) { throw 'Client executable missing.' }
    $wasOpen=@(Get-AppProcesses).Count -gt 0
    $windows=@(Get-Windows)
    if ($wasOpen) {
        $state='minimized'
        if (@($windows | Where-Object {-not [CheckinWindow]::IsIconic($_)}).Count) { $state='normal' }
        if (@($windows | Where-Object {[CheckinWindow]::IsZoomed($_)}).Count) { $state='maximized' }
    }
    $allowed=if ($wasOpen) { Test-RestartAllowed } else { $true }
    if ($InspectOnly) { Write-Output "app=$App original=$state restartAllowed=$allowed"; $result=0 }
    elseif (-not $allowed) {
        # Running user tasks must survive; still perform API check-in and growth.
        & $python (Join-Path $root 'run_daily_claim.py') --api-only >> $log 2>&1
        $result=$LASTEXITCODE
        Write-Log "API without restart (active or unknown task state), exit=$result"
    }
    else {
        if ($wasOpen) { Close-App; Write-Log 'Existing client and background processes terminated before restart.' }
        $started=$true
        Start-Process -FilePath $exe -WindowStyle Hidden | Out-Null
        $ready=$false
        for ($i=0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 1
            $newWindows=@(Get-Windows)
            if ($state -in @('closed','minimized')) { foreach ($h in $newWindows) { [void][CheckinWindow]::ShowWindowAsync($h,6) } }
            if ($newWindows.Count -and $i -ge 14) { $ready=$true; break }
        }
        if (-not $ready) { throw 'Client startup readiness timeout.' }
        & $python (Join-Path $root 'run_daily_claim.py') --api-only >> $log 2>&1
        $result=$LASTEXITCODE
        Write-Log "API exit=$result original=$state"
    }
} catch { Write-Log ('ERROR: '+$_.Exception.Message); $result=1 }
finally {
    if ($started) {
        try {
            if (-not $wasOpen) { Close-App -OwnedLaunch; Write-Log 'Restored closed state; matching client processes cleared.' }
            else {
                $show=1
                if ($state -eq 'minimized') { $show=6 }
                if ($state -eq 'maximized') { $show=3 }
                foreach ($h in @(Get-Windows)) { [void][CheckinWindow]::ShowWindowAsync($h,$show) }
                Write-Log ('Restored '+$state)
            }
        } catch { Write-Log ('RESTORE_ERROR: '+$_.Exception.Message); $result=1 }
    }
    $mutex.ReleaseMutex(); $mutex.Dispose()
}
exit $result
