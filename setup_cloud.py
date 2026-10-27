"""
One-time setup for cloud mode (GitHub Actions runs the queues while the laptop is off).

  python setup_cloud.py

- creates the `state` branch on GitHub from your current queue / published files
  (or uses it if it already exists)
- checks it out into ./state (a git worktree, ignored by the main branch)
- turns on CLOUD_SYNC=true in .env

The old files in this folder are left as they are, as a backup.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
FILES = ["published.json", "post_queue.json", "pin_queue.json", "price_state.json"]


def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r


def main():
    if (STATE / ".git").exists():
        print("./state already exists.")
    else:
        git("fetch", "-q", "origin")
        if git("rev-parse", "--verify", "-q", "origin/state", check=False).returncode == 0:
            git("worktree", "add", "-q", "-B", "state", str(STATE), "origin/state")
            print("Checked out the existing state branch into ./state")
        else:
            git("worktree", "add", "-q", "--detach", str(STATE))
            git("checkout", "-q", "--orphan", "state", cwd=STATE)
            git("rm", "-rfq", ".", cwd=STATE)
            for f in FILES:
                src = ROOT / f
                if src.exists():
                    shutil.copy2(src, STATE / f)
            (STATE / "README.md").write_text(
                "Automation state for the Penny Wise Finds tool (queues, published links).\n"
                "Written by the dashboard and the GitHub Actions job. Do not edit by hand.\n", encoding="utf-8")
            git("add", "-A", cwd=STATE)
            git("commit", "-q", "-m", "Initial automation state", cwd=STATE)
            git("push", "-q", "-u", "origin", "state", cwd=STATE)
            print("Created the state branch on GitHub with:", ", ".join(f for f in FILES if (STATE / f).exists()))

    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if re.search(r"^CLOUD_SYNC=", text, re.M):
        text = re.sub(r"^CLOUD_SYNC=.*$", "CLOUD_SYNC=true", text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n\n# Cloud mode: GitHub Actions posts the queue (python setup_cloud.py)\nCLOUD_SYNC=true\n"
    env.write_text(text, encoding="utf-8")
    print("CLOUD_SYNC=true is set in .env. Restart the dashboard (start.bat).")


if __name__ == "__main__":
    main()
