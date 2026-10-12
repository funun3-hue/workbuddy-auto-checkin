# WorkBuddy Auto Check-in

Automate WorkBuddy's daily points check-in on Windows using OpenCV template matching and mouse input. Includes a ready-to-use AI skill, Python scripts, and image templates for light and dark themes.

## Features

- Launches or activates WorkBuddy and locates the check-in controls.
- Waits two seconds after claiming points, then clicks the dialog's close button. Light-theme templates take priority, with dark-theme templates as a fallback.
- Confirms the claim using the "claimed today" image. Leaves the main window open if the claim cannot be confirmed or the dialog's close button cannot be found.
- Preserves an existing instance when a task is active or its status cannot be determined.
- With `--close-after-run`, closes an instance started by the script after a successful check-in. Minimizes an existing instance if it was originally in the background.
- Can register a daily Windows scheduled task for 09:42, using the computer's local time.

## Requirements

- Windows
- Python 3.11 with the Windows `py` launcher
- WorkBuddy installed and signed in
- An unlocked desktop

The default executable path is `%LOCALAPPDATA%\Programs\WorkBuddy\WorkBuddy.exe`.

The bundled image templates were captured from WorkBuddy's Chinese interface. They are theme variants, not English UI templates. Other UI languages, display scaling, or layout changes may require new templates.

## Quick start

Clone this repository or download and extract the ZIP, then run the following command from the project directory:

```powershell
py -3.11 .\workbuddy_checkin.py --run --close-after-run --json
```

On first run, the script creates a virtual environment at `%LOCALAPPDATA%\CheckinRuntime\py311` and installs the pinned dependencies from `requirements.txt` with pip. Initial setup requires internet access.

The script waits for keyboard and mouse activity to stop before starting. Avoid using the mouse or switching windows while it is clicking through the check-in flow.

## Schedule a daily check-in

```powershell
py -3.11 .\workbuddy_checkin.py --install-daily-schedule
```

This registers the `WorkBuddy Daily Check-in` task for 09:42. It runs only while you are signed in to Windows, and the desktop must be unlocked for the clicks to work.

To change the time, edit `DAILY_TASK_TIME` in `workbuddy_checkin.py` and run the installation command again. Re-register the task if you move the project folder.

## Check window availability

```powershell
py -3.11 .\workbuddy_checkin.py --diagnose
```

Diagnostic mode opens or activates WorkBuddy and checks for a usable window. It does not click the check-in controls.

## Use as an AI skill

Place the complete repository folder in a skill directory supported by your AI tool. Keep `SKILL.md`, both Python scripts, `requirements.txt`, and `assets/` together. The skill instructs the AI tool to run the packaged script.

## How it works

The script captures the WorkBuddy window and matches its contents against the bundled templates in memory. Click coordinates are calculated from the matched region; the dialog's close button uses an offset within its header template.

To avoid interrupting an active task, the script reads session status fields from the local `~/.workbuddy/workbuddy.db` database in read-only mode. It does not read login tokens, call the check-in API, or upload the database.

## Limitations and troubleshooting

Template matching does not automatically adjust for display scaling, font changes, or a redesigned interface. Update the templates if the controls can no longer be recognized.

The light-theme dialog close button has been tested on the author's machine. The complete workflow has not been validated across other computers or WorkBuddy versions.

Logs are stored at `%LOCALAPPDATA%\WorkBuddyAutoCheckin\logs\checkin.log`. They may contain window coordinates, process IDs, and error details; review them before sharing. Runtime logs, session databases, virtual environments, and account credentials are excluded from this repository.

This is an unofficial project and is not affiliated with WorkBuddy.

## License

The project code is licensed under the [MIT License](LICENSE). WorkBuddy branding and UI elements shown in the image templates remain the property of their respective owners.