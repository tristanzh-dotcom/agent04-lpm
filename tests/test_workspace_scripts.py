import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceScriptTests(unittest.TestCase):
    def test_start_and_stop_scripts_are_syntax_valid(self):
        for script_name in ("start_workspace.sh", "stop_workspace.sh"):
            script = ROOT / script_name
            self.assertTrue(script.exists(), f"{script_name} should exist")
            subprocess.run(["bash", "-n", str(script)], check=True)

    def test_start_script_delegates_to_web_publishing_platform(self):
        script_text = (ROOT / "start_workspace.sh").read_text()

        self.assertNotIn("source deploy_and_run.sh", script_text)
        self.assertNotIn(". deploy_and_run.sh", script_text)
        self.assertNotIn("uvicorn backend.ark_main:app --host 127.0.0.1 --port 8004", script_text)
        self.assertNotIn("python3 -m http.server 3000", script_text)
        self.assertIn('WEB_ROOT="/Users/tristanzh/agent/web"', script_text)
        self.assertIn("com.tz.agent-web-service", script_text)
        self.assertIn("launchctl kickstart -k", script_text)
        self.assertIn("launchctl bootstrap", script_text)
        self.assertIn("http://127.0.0.1:3000/agent04", script_text)
        self.assertIn("8004 后端由 3000 平台按需托管", script_text)


if __name__ == "__main__":
    unittest.main()
