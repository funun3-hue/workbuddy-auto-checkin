"""Run daily check-in plus growth-center rewards with sanitized silent logging."""
import sys
from pathlib import Path
from datetime import datetime

SKILL_DIR = Path(__file__).resolve().parent
# Embedded Python's _pth isolation can omit the script's directory.
sys.path.insert(0, str(SKILL_DIR))


def main():
    if '--api-only' not in sys.argv and '--self-test' not in sys.argv:
        import os
        import subprocess
        lifecycle = SKILL_DIR / 'lifecycle.ps1'
        return subprocess.call([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-WindowStyle', 'Hidden', '-File', str(lifecycle), '-App', 'WorkBuddy', '-PythonPath', sys.executable
        ], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        import signin
    except Exception as exc:
        with (SKILL_DIR / 'signin.log').open('a', encoding='utf-8') as log:
            log.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] STARTUP_ERROR {type(exc).__name__}\n')
        return 2
    if '--self-test' in sys.argv:
        # No login-file reads, decryption or HTTP requests.
        assert Path(signin.__file__).resolve().parent == SKILL_DIR
        assert signin.classify_daily_claim(200, {'code': 9004})[0] is False
        return 0
    sys.argv = [str(signin.__file__), "silent"]
    return signin.main()


if __name__ == "__main__":
    raise SystemExit(main())
