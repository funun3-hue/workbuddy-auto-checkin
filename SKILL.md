---
name: workbuddy-auto-checkin
description: Run the deterministic Windows WorkBuddy daily points check-in. Use when the user asks to check in, claim daily Buddy points, test the WorkBuddy check-in, or configure this packaged workflow.
---

# WorkBuddy automatic check-in

Use the packaged script for the actual operation. Do not recreate its mouse workflow, edit this skill during a run, use OCR, or ask how to handle an existing, foreground, background, or minimized WorkBuddy window.

## Run

Resolve paths relative to this `SKILL.md`, then execute:

```powershell
py -3.11 "<skill-directory>\workbuddy_checkin.py" --run --close-after-run
```

Once the user has requested a real check-in or a test run, run that command directly. The script owns the complete behavior: it waits for user input to be idle, records the initial WorkBuddy window state, checks WorkBuddy's local session database for an active task, preserves an existing instance whenever a task is active or task state cannot be read, brings the usable window forward, locates the supplied image templates, clicks the claim flow, waits for the supplied success-state image, and only then closes, keeps open, or minimizes the window according to its recorded initial state. If success is not confirmed within 10 seconds, it leaves the window open.

Do not use general computer-control tools for this workflow. Report the script result; if it fails, read `%LOCALAPPDATA%\WorkBuddyAutoCheckin\logs\checkin.log` and report the concrete cause.

After the claim click, the script waits 2 seconds, records any visible today-claimed image, then waits up to 10 seconds for the supplied panel header, preferring `checkin-close-light.png` and falling back to `checkin-close-dark.png`, and clicks the cross center within that header. Only after this panel close and claim confirmation may it close or minimize the main window under the original rules. A missing header does not trigger a guessed click and leaves the main window open. Closing the panel is not proof of a successful claim; the today-claimed image still confirms success.

## First run

The script creates or reuses `%LOCALAPPDATA%\CheckinRuntime\py311`. On first use it installs the packages pinned in `requirements.txt` using pip. Python 3.11, the Windows `py` launcher, and network access to the package index are required.

Generated `%LOCALAPPDATA%\CheckinRuntime` and `__pycache__` directories are machine-local runtime files and should not be included when transferring this skill to another computer.

## Daily schedule

When the user asks to enable automatic daily check-in, install the packaged 09:42 schedule once on that computer:

```powershell
py -3.11 "<skill-directory>\workbuddy_checkin.py" --install-daily-schedule
```

This creates or updates the `WorkBuddy Daily Check-in` Windows task. It runs only while that user is signed in, because the check-in must activate and click the WorkBuddy window. Moving the skill folder later requires running this command again so the task uses the new path.
