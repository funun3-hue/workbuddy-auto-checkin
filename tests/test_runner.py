import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_daily_claim as runner
import busy
import signin


class RunnerTests(unittest.TestCase):
    def test_api_runs_daily_and_growth(self):
        with patch.object(sys, 'argv', ['runner', '--api-only']), patch.object(signin, 'main', return_value=0) as run:
            self.assertEqual(runner.main(), 0)
            self.assertEqual(sys.argv[1], 'silent')
            run.assert_called_once()

    def test_launch_uses_bundled_lifecycle_and_current_python(self):
        with patch.object(sys, 'argv', ['runner']), patch('subprocess.call', return_value=0) as launch:
            self.assertEqual(runner.main(), 0)
            args = launch.call_args.args[0]
            self.assertIn(str(ROOT / 'lifecycle.ps1'), args)
            self.assertEqual(args[-2:], ['-PythonPath', sys.executable])

    def test_unknown_and_running_states_do_not_allow_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.workbuddy').mkdir()
            conn = sqlite3.connect(home / '.workbuddy/workbuddy.db')
            try:
                conn.execute('CREATE TABLE sessions(status TEXT, deleted_at INTEGER)')
                with patch.object(busy.Path, 'home', return_value=home):
                    for status, idle in [('completed', True), ('archived', True), ('running', False), ('Pending', False), ('unknown', False)]:
                        conn.execute('DELETE FROM sessions')
                        conn.execute('INSERT INTO sessions VALUES (?, NULL)', (status,))
                        conn.commit()
                        self.assertEqual(busy.idle('WorkBuddy'), idle)
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main()
