"""
Keeps the state files (queues, published.json, price_state.json) in a `state` branch on
GitHub, so the laptop dashboard and the GitHub Actions job (cloud_run.py) share them.

Off by default. Turn on with CLOUD_SYNC=true in .env (see SETUP-GUIDE.md, "Cloud").
Then STATE_DIR (default ./state) is a git worktree of the `state` branch.

Every change goes through transact(): pull the latest state, apply the change, commit,
push. If someone else pushed in between, the push is rejected and the change is
re-applied on the fresh state, so the two sides never overwrite each other.
"""
import subprocess
import threading
import time

import publish as pw

ENABLED = pw.CLOUD_SYNC
DIR = pw.STATE_DIR
_lock = threading.RLock()
_last_pull = {"t": 0.0}


def _git(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(DIR), *args], capture_output=True, text=True,
                          check=check, timeout=120)


def pull():
    if not ENABLED:
        return
    with _lock:
        _git("fetch", "-q", "origin", "state")
        _git("reset", "-q", "--hard", "origin/state")
        _last_pull["t"] = time.time()


def refresh(max_age: float = 20):
    """Pull if the local copy is older than max_age seconds (for read-only pages)."""
    if ENABLED and time.time() - _last_pull["t"] > max_age:
        try:
            pull()
        except Exception as e:
            print("state pull failed:", e)


def transact(fn, message: str):
    """Run fn() on the latest state and publish its changes. Returns fn's result."""
    if not ENABLED:
        return fn()
    with _lock:
        for attempt in range(5):
            pull()
            result = fn()
            if not _git("status", "--porcelain").stdout.strip():
                return result
            _git("add", "-A")
            _git("commit", "-q", "-m", message)
            if _git("push", "-q", "origin", "HEAD:state", check=False).returncode == 0:
                return result
            time.sleep(2 + attempt * 2)   # someone else pushed first: retry on fresh state
        raise RuntimeError("Could not save the state to GitHub (push kept failing).")
