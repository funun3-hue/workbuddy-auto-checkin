---
name: workbuddy-auto-signin
description: WorkBuddy API check-in and growth-center reward collection on Windows, with scheduled runs, task-aware restart and window-state restoration. Use for WorkBuddy rewards, check-in or schedule setup.
---

# WorkBuddy check-in and growth rewards

Resolve scripts relative to this file. Follow README.md for installation and troubleshooting. Python 3.11+ and the user's signed-in WorkBuddy installation are required. Keep lifecycle.ps1, busy.py and the runner together.

- Install scheduling only when requested: install-windows.ps1, default local times 09:40 and 18:30. Installation runs offline checks, not claims. Startup repair preserves the saved times.
- Actual check-in and rewards: run_daily_claim.py. It invokes lifecycle.ps1 with the current interpreter, then signin.py silent. Already-signed daily claims are skipped; growth still runs.
- Active or unknown task state: API directly without restart. Confirmed idle: force-stop matching installation processes, restart, run API and restore original window state. Originally closed: clear the temporary client's processes afterward.
- Status only: signin.py status. Offline check: run_daily_claim.py --self-test. API without lifecycle: run_daily_claim.py --api-only.
- Growth uses existing makeup cards, draw opportunities and energy; includes travel dispatch, task acceptance/rewards and streak exchanges. Do not claim that it performs work tasks, purchases benefits or guarantees rewards. Report the actual daily and growth results separately from signin.log.
- Never display or share credentials, logs, schedule.local.json or client databases. Auth failures stop the authenticated operation; do not alter credential ACLs.

Source: https://github.com/88lin/workbuddy-auto-signin (MIT, see UPSTREAM-LICENSE). APIs and client formats can change. No mouse input is used.
