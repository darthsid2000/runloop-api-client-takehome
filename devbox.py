"""
USAGE:
  python devbox.py --run test.py
"""

import argparse
import base64
import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Runloop SDK
from runloop_api_client import Runloop

ANSWERS_PATH = Path("answers.json")
RESOURCES_DIR = Path("resources")


def load_answers():
    if ANSWERS_PATH.exists():
        return json.loads(ANSWERS_PATH.read_text())
    return {
        "api-key": "",
        "devbox-name": "",
        "devbox-id": "",
        "snapshot-id": "",
        "blueprint-name": "",
        "blueprint-id": "",
        "devbox-from-blueprint-id": "",
        "devbox-from-blueprint-name": "",
        "ext-scenario-run-id": "",
    }


def save_answers(updates: dict):
    answers = load_answers()
    answers.update(updates)
    ANSWERS_PATH.write_text(json.dumps(answers, indent=2))


def assert_prereqs(email: str, run_target: str):
    assert RESOURCES_DIR.exists(), "Missing ./resources folder (required by the assignment)."
    me_txt = RESOURCES_DIR / "me.txt"
    assert me_txt.exists(), "Missing ./resources/me.txt"
    assert (RESOURCES_DIR / "test.py").exists() or (RESOURCES_DIR / "test.js").exists(), \
        "Need ./resources/test.py or ./resources/test.js"
    if run_target not in ("test.py", "test.js"):
        raise ValueError("--run must be 'test.py' or 'test.js'")
    if "@" not in email:
        raise ValueError("--email must be a valid email")


def put_text_file(client, devbox_id: str, remote_path: str, text: str):
    """Write a text file on the devbox via base64 (no upload API needed)."""
    payload = base64.b64encode(text.encode()).decode()
    cmd = f"bash -lc \"mkdir -p $(dirname {remote_path}) && echo '{payload}' | base64 -d > {remote_path}\""
    client.devboxes.execute_sync(id=devbox_id, command=cmd)


def copy_resources_directory(client, devbox_id: str):
    """Recursively create directories and write files from ./resources onto the devbox."""
    for p in RESOURCES_DIR.rglob("*"):
        rel = p.relative_to(RESOURCES_DIR)
        remote = f"resources/{rel.as_posix()}"
        if p.is_dir():
            client.devboxes.execute_sync(id=devbox_id, command=f"bash -lc 'mkdir -p {remote}'")
        else:
            text = p.read_text() if p.suffix in {".txt", ".py", ".js", ".md"} else p.read_bytes().decode("utf-8", errors="ignore")
            put_text_file(client, devbox_id, remote, text)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="test.py", choices=["test.py", "test.js"], help="Which test to execute.")
    args = parser.parse_args()

    load_dotenv()
    assert_prereqs(os.environ.get("EMAIL"), args.run)

    # Initialize client
    client = Runloop()

    try:
        print("[1.a] Creating devbox...")
        devbox = client.devboxes.create_and_await_running(name=os.environ.get("EMAIL"))
        devbox_id = devbox.id
        print(f"[1.a] Devbox: {devbox_id}")

        # Record to answers.json
        save_answers({
            "api-key": os.environ.get("RUNLOOP_API_KEY"),
            "devbox-name": os.environ.get("EMAIL"),
            "devbox-id": devbox_id,
        })

        print("[1.b] Copying ./resources to devbox...")
        copy_resources_directory(client, devbox_id)

        print("[1.b] Editing resources/me.txt...")
        put_text_file(client, devbox_id, "resources/me.txt", os.environ.get("EMAIL"))


        print(f"[1.b] Running {args.run}...")
        run_cmd = "python3 resources/test.py" if args.run == "test.py" else "node resources/test.js"
        result = client.devboxes.execute_sync(id=devbox_id, command=f"bash -lc \"{run_cmd}\"")
        try:
            print(result.stdout)
        except Exception:
            pass

        print("[1.c] Creating snapshot...")
        snapshot = client.devboxes.snapshot_disk(id=devbox_id)
        snapshot_id = snapshot.id
        save_answers({"snapshot-id": snapshot_id})
        print(f"[1.c] Snapshot: {snapshot_id}")

        print("✅ Task 1 done.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up
        if 'devbox' in locals():
            print("\nShutting down devbox...")
            client.devboxes.shutdown(devbox.id)

if __name__ == "__main__":
    main()