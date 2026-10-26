# WorkBuddy Auto Check-in

Windows API-based daily check-in and growth-center reward automation, adapted from [88lin/workbuddy-auto-signin](https://github.com/88lin/workbuddy-auto-signin). This replaces the previous screenshot/mouse workflow.

## Behavior

- Runs every day at **09:40 and 18:30**, using the computer's local timezone (set Windows to Asia/Shanghai for Beijing time).
- Queries today's check-in status first. Already checked in: skip the daily claim and continue with growth-center rewards.
- Includes travel gifts and Buddy dispatch, task acceptance and completed-task rewards, makeup cards (at most one per run), unlocked streak exchanges, available lottery chances and energy Buddy boxes. These operations may use existing cards, chances and energy. No purchase flow is included; it does not perform user work tasks to satisfy activity requirements.
- If WorkBuddy is open and all undeleted sessions have known terminal states, force-terminates matching installation processes before restarting and calling the API.
- If a user task is active or its state cannot be confirmed, calls the API directly while leaving the client running.
- Restores a pre-existing minimized, normal or maximized window state. If originally closed, closes the temporary instance and clears matching background processes afterward.
- Uses a mutex and Task Scheduler's IgnoreNew policy to avoid overlapping scheduled runs. Missed runs can catch up when Windows is available; the computer must be awake and signed in.

## Install

Install Python 3.11+ and sign in to WorkBuddy with your own account. Extract the complete folder to a permanent writable location, then double-click `install.cmd`.

For a custom interpreter or schedule, run PowerShell in this folder:

```powershell
.\install-windows.ps1 -PythonPath 'C:\path\to\python.exe' -Time @('09:40','18:30')
```

The installer performs an offline self-test, registers `WorkBuddy Daily Check-in`, and adds a current-user Startup repair launcher. It does not send a claim during installation. Keep the folder in place; reinstall after moving it. Repair preserves both trigger times from the local config.

## Commands and logs

```powershell
py -3.11 .\run_daily_claim.py --self-test  # offline
py -3.11 .\signin.py status              # online status only
py -3.11 .\run_daily_claim.py            # real check-in + growth + lifecycle
py -3.11 .\run_daily_claim.py --api-only # real check-in + growth without restarting
```

`signin.log` contains sanitized API results, including separate daily-check-in and growth-center results. `WorkBuddy.log` records lifecycle decisions; `schedule-repair.log` records repair attempts. A successful daily check-in does not imply all growth operations succeeded. Errors and unconfirmed results require attention.

Uninstall by removing the `WorkBuddy Daily Check-in` scheduled task and `WorkBuddy API Check-in Repair.vbs` from the current user's Startup folder.

## Scope and verification

All lifecycle helpers are bundled: no dependency on the author's AppData scripts or Windows username. WorkBuddy is expected at `%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe`. Unknown session schemas/states use the no-restart API path.

Only use your own authorized local login. Do not publish logs, `schedule.local.json`, client databases or credentials. Credentials are processed locally for API authentication and are not bundled. The upstream API and credential formats are reverse-engineered and can change. This is an unofficial project.

Offline growth/auth/runtime tests and runner routing checks are available in `tests/`. The complete restart/claim workflow has not been validated across other computers or client versions. Installation and offline tests do not prove live rewards were received.

## License

Project changes use the [MIT License](LICENSE). `signin.py` and upstream tests derive from 88lin's MIT project; its notice is preserved in [UPSTREAM-LICENSE](UPSTREAM-LICENSE).
