#!/usr/bin/env python3
"""Windows WorkBuddy check-in using fast image matching."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
SHARED_RUNTIME_DIR = LOCAL_APPDATA / "CheckinRuntime"
VENV_DIR = SHARED_RUNTIME_DIR / "py311"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
VENV_PYTHONW = VENV_DIR / "Scripts" / "pythonw.exe"
REQUIREMENTS_PATH = SKILL_DIR / "requirements.txt"


def ensure_skill_environment() -> None:
    """Create or reuse the local Python 3.11 check-in environment."""
    shared_interpreters = {VENV_PYTHON.resolve(), VENV_PYTHONW.resolve()}
    if VENV_PYTHON.exists() and Path(sys.executable).resolve() in shared_interpreters:
        return
    if not VENV_PYTHON.exists():
        try:
            subprocess.run(
                ["py", "-3.11", "-m", "venv", str(VENV_DIR)],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            subprocess.run(
                [
                    str(VENV_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-r",
                    str(REQUIREMENTS_PATH),
                ],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("WorkBuddy check-in needs Python 3.11 and access to the Python package index.") from exc
    # ``os.execv`` does not reliably preserve this script's arguments under
    # the Windows Python launcher.  A child process does, and its exit status
    # is returned unchanged to the scheduled task.
    completed = subprocess.run(
        [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    raise SystemExit(completed.returncode)


ensure_skill_environment()

import win32api
import win32con
import win32gui
import win32process

from image_checkin import ImageLocator, perform as perform_checkin


APP_EXE = LOCAL_APPDATA / "Programs" / "WorkBuddy" / "WorkBuddy.exe"
RUNTIME_DIR = LOCAL_APPDATA / "WorkBuddyAutoCheckin"
LOG_DIR = RUNTIME_DIR / "logs"
LOG_PATH = LOG_DIR / "checkin.log"
LOCK_PATH = RUNTIME_DIR / "checkin.lock"
USER_IDLE_SECONDS = 1.5
INPUT_IDLE_POLL_SECONDS = 0.1
# Always start a real check-in from a fresh WorkBuddy process so stale daily
# state, update overlays, and previously open popovers cannot be reused.
RESTART_BEFORE_RUN = True
NORMAL_CLOSE_GRACE_SECONDS = 0.4
PAGE_READY_TIMEOUT_SECONDS = 60.0
PAGE_READY_POLL_SECONDS = 0.1
# An Electron main window is created hidden and only shown on ready-to-show, and
# SetForegroundWindow cannot activate an invisible window. A freshly started
# instance therefore needs time to become visible before it can be focused.
WINDOW_VISIBLE_TIMEOUT_SECONDS = 20.0
FOCUS_TIMEOUT_SECONDS = 8.0
WORKBUDDY_DB = Path.home() / ".workbuddy" / "workbuddy.db"
DAILY_TASK_NAME = "WorkBuddy Daily Check-in"
DAILY_TASK_TIME = "09:42"


def detect_active_workbuddy_task(logger: logging.Logger) -> bool | None:
    """Return whether WorkBuddy has a non-terminal session, or None if unknown."""
    if not WORKBUDDY_DB.exists():
        logger.warning("WorkBuddy task database was not found; preserving any existing app")
        return None
    try:
        connection = sqlite3.connect(
            f"file:{WORKBUDDY_DB.as_posix()}?mode=ro", uri=True, timeout=1.0
        )
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT lower(coalesce(status, ''))
                FROM sessions
                WHERE deleted_at IS NULL
                """
            ).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        logger.warning(
            "could not read WorkBuddy task state; preserving any existing app: %s", exc
        )
        return None

    terminal = {"completed", "archived", "cancelled", "canceled", "failed"}
    active_statuses = sorted(
        status for (status,) in rows if status and status not in terminal
    )
    if active_statuses:
        logger.info("active WorkBuddy task state detected: %s", active_statuses)
        return True
    logger.info("no active WorkBuddy task state detected")
    return False


def configure_logging(console: bool) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("workbuddy-checkin")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


class SingleRunLock:
    def __enter__(self) -> "SingleRunLock":
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime > 600:
            LOCK_PATH.unlink(missing_ok=True)
        try:
            descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("another WorkBuddy check-in run is still active") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        LOCK_PATH.unlink(missing_ok=True)


def is_desktop_unlocked() -> bool:
    user32 = ctypes.windll.user32
    desktop = user32.OpenInputDesktop(0, False, 0x0100)
    if not desktop:
        return False
    try:
        return bool(user32.SwitchDesktop(desktop))
    finally:
        user32.CloseDesktop(desktop)


def user_idle_seconds() -> float:
    """Read session input timing only; do not capture keys or mouse contents."""
    last_input_tick = win32api.GetLastInputInfo()
    current_tick = win32api.GetTickCount()
    elapsed_ms = (current_tick - last_input_tick) & 0xFFFFFFFF
    # Handle tick-counter rollover, but never treat a future input tick as idle.
    return elapsed_ms / 1000.0 if elapsed_ms <= 0x7FFFFFFF else 0.0


def any_input_held() -> bool:
    """A held key or mouse button is not an idle input session."""
    return any(win32api.GetAsyncKeyState(key) & 0x8000 for key in range(1, 256))


def wait_for_user_idle(logger: logging.Logger) -> None:
    logger.info("waiting for %.1f seconds without keyboard or mouse input", USER_IDLE_SECONDS)
    while True:
        if (
            is_desktop_unlocked()
            and user_idle_seconds() >= USER_IDLE_SECONDS
            and not any_input_held()
        ):
            logger.info("keyboard and mouse idle requirement met")
            return
        time.sleep(INPUT_IDLE_POLL_SECONDS)


def process_image_path(process_id: int) -> Path | None:
    """Return a process executable path without adding a psutil dependency."""
    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information, False, process_id
    )
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buffer))
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return None
        return Path(buffer.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def is_workbuddy_process(process_id: int) -> bool:
    image_path = process_image_path(process_id)
    if image_path is None:
        return False
    return os.path.normcase(str(image_path)) == os.path.normcase(str(APP_EXE))


def enumerate_workbuddy_processes() -> list[int]:
    return [
        process_id
        for process_id in win32process.EnumProcesses()
        if process_id and is_workbuddy_process(process_id)
    ]


def enumerate_workbuddy_windows() -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []

    def callback(hwnd: int, _: Any) -> None:
        if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
            return
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        process_matches = is_workbuddy_process(process_id)
        if not process_matches:
            return
        rect = win32gui.GetWindowRect(hwnd)
        width = max(0, rect[2] - rect[0])
        height = max(0, rect[3] - rect[1])
        windows.append(
            {
                "hwnd": hwnd,
                "pid": process_id,
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
                "iconic": bool(win32gui.IsIconic(hwnd)),
                "area": width * height,
            }
        )

    win32gui.EnumWindows(callback, None)
    return windows


def force_stop_workbuddy_processes(logger: logging.Logger) -> None:
    """Stop every verified WorkBuddy process and confirm that it exited."""
    if not enumerate_workbuddy_processes():
        return
    logger.warning(
        "WorkBuddy did not close after WM_CLOSE; force-stopping its verified process tree"
    )
    subprocess.run(
        ["taskkill", "/IM", APP_EXE.name, "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and enumerate_workbuddy_processes():
        time.sleep(0.1)
    remaining = enumerate_workbuddy_processes()
    if remaining:
        raise RuntimeError(f"WorkBuddy processes did not exit: {remaining}")


def close_existing_workbuddy_instances(logger: logging.Logger) -> bool:
    """Fully close existing WorkBuddy and report whether one was closed."""
    windows = enumerate_workbuddy_windows()
    processes = enumerate_workbuddy_processes()
    if not windows and not processes:
        return False
    logger.info(
        "closing existing WorkBuddy instance(s) before today's check-in windows=%s pids=%s",
        len(windows),
        processes,
    )
    for item in windows:
        hwnd = int(item["hwnd"])
        if win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    deadline = time.monotonic() + NORMAL_CLOSE_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not enumerate_workbuddy_windows() and not enumerate_workbuddy_processes():
            logger.info("existing WorkBuddy instance closed normally")
            return True
        time.sleep(0.05)
    force_stop_workbuddy_processes(logger)
    return True


def ensure_windows(
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], bool]:
    windows = enumerate_workbuddy_windows()
    if windows:
        return windows, False
    if not APP_EXE.exists():
        raise RuntimeError(f"WorkBuddy executable not found: {APP_EXE}")

    processes = enumerate_workbuddy_processes()
    launched = not processes
    if processes:
        logger.info(
            "WorkBuddy process is already running without a recognized window; "
            "waiting instead of launching a duplicate (pids=%s)",
            processes,
        )
    else:
        logger.info("WorkBuddy is not running; launching one instance")
        subprocess.Popen(
            [str(APP_EXE)],
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            ),
        )

    deadline = time.monotonic() + 60
    last_windows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        last_windows = enumerate_workbuddy_windows()
        if any(
            item["visible"] and item["enabled"] and item["area"] > 0
            for item in last_windows
        ):
            return last_windows, launched
    if last_windows:
        return last_windows, launched
    if enumerate_workbuddy_processes():
        raise RuntimeError(
            "WorkBuddy is running but did not expose a usable window before the timeout; "
            "a second instance was not launched"
        )
    raise RuntimeError("WorkBuddy exited before exposing a usable window")


def choose_window(windows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        item
        for item in windows
        if item["enabled"] and item["area"] > 0 and item["visible"]
    ]
    if not usable:
        raise RuntimeError("no visible WorkBuddy window was found")
    return sorted(
        usable,
        key=lambda item: (
            item["visible"],
            not item["iconic"],
            item["area"],
            -item["hwnd"],
        ),
        reverse=True,
    )[0]


def activate_window(hwnd: int) -> None:
    """Run the full foreground-activation combo once; failures are non-fatal."""
    try:
        foreground = win32gui.GetForegroundWindow()
        foreground_thread = (
            win32process.GetWindowThreadProcessId(foreground)[0]
            if foreground
            else 0
        )
        current_thread = win32api.GetCurrentThreadId()
        if foreground_thread and foreground_thread != current_thread:
            ctypes.windll.user32.AttachThreadInput(
                current_thread, foreground_thread, True
            )
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if foreground_thread and foreground_thread != current_thread:
                ctypes.windll.user32.AttachThreadInput(
                    current_thread, foreground_thread, False
                )
    except Exception:
        pass
    if win32gui.GetForegroundWindow() != hwnd:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            try:
                ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
        finally:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


def restore_and_focus(hwnd: int) -> None:
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    deadline = time.time() + 5
    while time.time() < deadline:
        _, _, width, height = win32gui.GetClientRect(hwnd)
        if width >= 850 and height >= 600 and not win32gui.IsIconic(hwnd):
            break
        time.sleep(0.25)
    else:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        time.sleep(1.5)
    # A hidden Electron window cannot take the foreground: wait until the app has
    # actually shown it (ready-to-show) before spending the activation budget.
    visible_deadline = time.monotonic() + WINDOW_VISIBLE_TIMEOUT_SECONDS
    while not win32gui.IsWindowVisible(hwnd):
        if time.monotonic() >= visible_deadline:
            break
        time.sleep(0.1)
    # Retry the activation combo until the deadline instead of giving up after a
    # single attempt: Windows can refuse SetForegroundWindow while a window is
    # still settling, and the app may re-show its window after we touched it.
    focus_deadline = time.monotonic() + FOCUS_TIMEOUT_SECONDS
    while True:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_TOP,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
        activate_window(hwnd)
        if win32gui.GetForegroundWindow() == hwnd:
            return
        if time.monotonic() >= focus_deadline:
            raise RuntimeError("WorkBuddy could not be brought to the foreground")
        time.sleep(0.25)


def is_workbuddy_foreground(hwnd: int) -> bool:
    """Accept the main window or another top-level window from WorkBuddy."""
    foreground = win32gui.GetForegroundWindow()
    if foreground == hwnd:
        return True
    if not foreground or not win32gui.IsWindow(foreground):
        return False
    _, process_id = win32process.GetWindowThreadProcessId(foreground)
    return is_workbuddy_process(process_id)


def wait_for_loaded_page(hwnd: int, logger: logging.Logger) -> None:
    """Wait for the sidebar avatar, recovering focus only after user idle."""
    locator = ImageLocator(hwnd, logger)
    deadline = time.monotonic() + PAGE_READY_TIMEOUT_SECONDS
    avatar_templates = ("avatar-anchor-light.png", "avatar-anchor.png")
    while time.monotonic() < deadline:
        if not win32gui.IsWindow(hwnd):
            raise RuntimeError("WorkBuddy window closed while its page was loading")
        if not is_workbuddy_foreground(hwnd):
            logger.info(
                "WorkBuddy is still loading outside the foreground; waiting for idle before refocusing"
            )
            wait_for_user_idle(logger)
            restore_and_focus(hwnd)
            continue
        try:
            avatar = locator.find_any(avatar_templates, timeout=0)
        except RuntimeError as exc:
            if "lost foreground" not in str(exc):
                raise
            # The user acted during the capture.  Wait for a new idle window
            # before bringing WorkBuddy forward again.
            continue
        if avatar is not None:
            logger.info("WorkBuddy page is loaded; avatar anchor is ready at %s", avatar)
            return
        time.sleep(PAGE_READY_POLL_SECONDS)
    raise RuntimeError(
        f"WorkBuddy page did not finish loading within {PAGE_READY_TIMEOUT_SECONDS:.0f}s"
    )


def click_screen(x: int, y: int) -> None:
    """Move to an absolute screen point and emit one reliable left click."""
    win32api.SetCursorPos((x, y))
    # Do not press until the pointer is actually at the computed target.  This
    # matters on multi-monitor/DPI-scaled desktops where SetCursorPos can take
    # a scheduling turn before the cursor position is updated.
    deadline = time.monotonic() + 0.2
    while hasattr(win32api, "GetCursorPos") and win32api.GetCursorPos() != (x, y):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"cursor did not reach WorkBuddy target {(x, y)}")
        time.sleep(0.01)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def close_app_window(hwnd: int, logger: logging.Logger) -> bool:
    """At the three-second deadline, close the window and end remaining processes."""
    if win32gui.IsWindow(hwnd):
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        logger.info("posted WM_CLOSE to the WorkBuddy window after claim click")
    force_stop_workbuddy_processes(logger)
    return True


def minimize_app_window(hwnd: int, logger: logging.Logger) -> bool:
    """Minimize the refreshed app when it had been in the background."""
    if not win32gui.IsWindow(hwnd):
        return False
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    logger.info("minimized WorkBuddy because it was already open in the background")
    return True


def install_daily_schedule(logger: logging.Logger) -> dict[str, str]:
    """Create the per-user interactive Windows task for the daily check-in."""
    if not VENV_PYTHON.is_file():
        raise RuntimeError("shared check-in Python environment was not created")
    task_command = subprocess.list2cmdline(
        [
            str(VENV_PYTHONW),
            str(Path(__file__).resolve()),
            "--run",
            "--close-after-run",
        ]
    )
    completed = subprocess.run(
        [
            "schtasks.exe",
            "/Create",
            "/TN",
            DAILY_TASK_NAME,
            "/TR",
            task_command,
            "/SC",
            "DAILY",
            "/ST",
            DAILY_TASK_TIME,
            "/RL",
            "LIMITED",
            "/IT",
            "/F",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"could not create the daily WorkBuddy task: {details}")
    logger.info("installed Windows task %r for daily %s check-in", DAILY_TASK_NAME, DAILY_TASK_TIME)
    return {"task_name": DAILY_TASK_NAME, "time": DAILY_TASK_TIME}


def run(
    actual_click: bool,
    logger: logging.Logger,
    close_after_run: bool = False,
) -> dict[str, Any]:
    initial_windows = enumerate_workbuddy_windows()
    initial_processes = enumerate_workbuddy_processes()
    initial_instance_existed = bool(initial_windows or initial_processes)
    initial_foreground = win32gui.GetForegroundWindow()
    existing_window_was_background = bool(initial_windows) and all(
        int(item["hwnd"]) != initial_foreground for item in initial_windows
    )
    wait_for_user_idle(logger)
    existing_instance_closed = False
    active_task_detected: bool | None = None
    existing_instance_preserved = False
    if actual_click and RESTART_BEFORE_RUN and initial_instance_existed:
        active_task_detected = detect_active_workbuddy_task(logger)
        if active_task_detected is False:
            existing_instance_closed = close_existing_workbuddy_instances(logger)
        else:
            existing_instance_preserved = True
            logger.info(
                "preserving the existing WorkBuddy instance before check-in "
                "because task state is active or unavailable"
            )
    windows, newly_launched = ensure_windows(logger)
    selected = choose_window(windows)
    hwnd = int(selected["hwnd"])
    logger.info("selected WorkBuddy window hwnd=%s from %s candidates", hwnd, len(windows))
    # App startup can take time; the user may have resumed input in the meantime.
    wait_for_user_idle(logger)
    if is_workbuddy_foreground(hwnd):
        logger.info("WorkBuddy is already in the foreground; starting check-in directly")
    else:
        logger.info("WorkBuddy is not in the foreground; activating it for check-in")
        restore_and_focus(hwnd)
    if not actual_click:
        logger.info("diagnostic mode found the app window; no click performed")
        return {
            "ok": True,
            "status": "window_ready",
            "hwnd": hwnd,
            "newly_launched": newly_launched,
            "window_count": len(windows),
        }

    if not is_workbuddy_foreground(hwnd):
        raise RuntimeError("WorkBuddy lost the foreground before the first click")
    wait_for_loaded_page(hwnd, logger)
    result = perform_checkin(hwnd, logger, click_screen)
    close_requested = False
    minimized_after_checkin = False
    if not result["checkin_verified"] or not result["checkin_panel_closed"]:
        logger.warning("leaving WorkBuddy open because claim success or panel close was not confirmed")
    else:
        if close_after_run and not initial_instance_existed:
            close_requested = close_app_window(hwnd, logger)
        elif close_after_run:
            logger.info("keeping WorkBuddy open because an instance existed at startup")
        if initial_instance_existed and existing_window_was_background:
            minimized_after_checkin = minimize_app_window(hwnd, logger)
    return {
        "ok": True,
        **result,
        "close_requested": close_requested,
        "existing_instance_closed": existing_instance_closed,
        "existing_instance_preserved": existing_instance_preserved,
        "active_task_detected": active_task_detected,
        "initial_instance_existed": initial_instance_existed,
        "existing_window_was_background": existing_window_was_background,
        "minimized_after_checkin": minimized_after_checkin,
        "newly_launched": newly_launched,
        "window_count": len(windows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Restart and click the supplied image targets")
    mode.add_argument("--diagnose", action="store_true", help="Check app window availability without clicking")
    mode.add_argument(
        "--install-daily-schedule",
        action="store_true",
        help="Create or update this user's daily 09:42 interactive Windows task",
    )
    parser.add_argument(
        "--close-after-run",
        action="store_true",
        help="Exit after claim confirmation only when WorkBuddy was not already open",
    )
    parser.add_argument("--json", action="store_true", help="Print a compact JSON result")
    args = parser.parse_args()
    logger = configure_logging(
        console=bool(args.json or args.diagnose or args.install_daily_schedule)
    )
    try:
        with SingleRunLock():
            if args.install_daily_schedule:
                result = {"ok": True, **install_daily_schedule(logger)}
            else:
                result = run(
                    actual_click=bool(args.run),
                    logger=logger,
                    close_after_run=bool(args.close_after_run),
                )
        if args.json or args.diagnose or args.install_daily_schedule:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        logger.exception("WorkBuddy points check-in failed: %s", exc)
        if args.json or args.diagnose:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
