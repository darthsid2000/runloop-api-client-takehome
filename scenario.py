import json
import os
import base64
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from runloop_api_client import Runloop

load_dotenv()
EMAIL = os.getenv("EMAIL")

ANSWERS_PATH = Path("answers.json")
RESOURCES_DIR = Path("resources")
ME_TXT = RESOURCES_DIR / "me.txt"
TEST_PY = RESOURCES_DIR / "test.py"
TEST_JS = RESOURCES_DIR / "test.js"


def read_answers() -> Dict[str, str]:
    if ANSWERS_PATH.exists():
        with open(ANSWERS_PATH, "r") as f:
            return json.load(f)
    return {}


def write_answers(updates: Dict[str, str]):
    data = read_answers()
    data.update(updates)
    with open(ANSWERS_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def build_bash_scorer_script() -> str:
    # This script prints 1.0 if /workspace/resources contains me.txt and test.{py|js}; else 0.0
    # The platform reads stdout as a float score in [0.0, 1.0].
    return r"""
set -euo pipefail

dir="/workspace/resources"

if [[ -d "$dir" ]] && [[ -f "$dir/me.txt" ]] && ([[ -f "$dir/test.py" ]] || [[ -f "$dir/test.js" ]]); then
  echo 1.0
else
  echo 0.0
fi
""".strip()


def create_scenario(client: Runloop, email: str) -> str:
    scenario_name = f"{email}-resources-check"

    # Inline bash scorer via ScoringContractParam -> ScoringFunctionParam (bash_script_scorer)
    bash_script = build_bash_scorer_script()
    scoring_contract = {
        "scoring_function_parameters": [
            {
                "name": "resources_present",
                "weight": 1.0,
                "scorer": {
                    "type": "bash_script_scorer",
                    "bash_script": bash_script,
                },
            }
        ]
    }

    # input_context MUST include problem_statement
    input_context = {
        "problem_statement": "Verify ./resources exists and contains me.txt and test.{py|js}."
    }

    scenario = client.scenarios.create(
        name=scenario_name,
        input_context=input_context,
        scoring_contract=scoring_contract
    )
    return scenario.id


def put_text_file(client: Runloop, devbox_id: str, remote_path: str, text: str):
    """Write a text file on the devbox via base64 (no upload API needed)."""
    payload = base64.b64encode(text.encode()).decode()
    cmd = f"bash -lc \"mkdir -p $(dirname {remote_path}) && echo '{payload}' | base64 -d > {remote_path}\""
    client.devboxes.execute_sync(id=devbox_id, command=cmd)


def copy_resources_directory(client: Runloop, devbox_id: str):
    """Recursively create directories and write files from ./resources onto the devbox."""
    for p in RESOURCES_DIR.rglob("*"):
        rel = p.relative_to(RESOURCES_DIR)
        remote = f"resources/{rel.as_posix()}"
        if p.is_dir():
            client.devboxes.execute_sync(id=devbox_id, command=f"bash -lc 'mkdir -p {remote}'")
        else:
            text = p.read_text() if p.suffix in {".txt", ".py", ".js", ".md"} else p.read_bytes().decode("utf-8", errors="ignore")
            put_text_file(client, devbox_id, remote, text)


def run_test_script(client: Runloop, devbox_id: str):
    if TEST_PY.exists():
        result = client.devboxes.execute_sync(
            id=devbox_id,
            command="python3 resources/test.py",
        )
    elif TEST_JS.exists():
        result = client.devboxes.execute_sync(
            id=devbox_id,
            command="node resources/test.js",
        )
    else:
        raise RuntimeError("Neither test.py nor test.js available after upload.")
    print("[test stdout]", result.stdout)
    print("[test stderr]", result.stderr)


def main():
    client = Runloop()

    print("[3] Creating scenario…")
    scenario_id = create_scenario(client, EMAIL)
    print(f"[3] Scenario created: {scenario_id}")

    print("[3] Starting scenario run (awaiting env ready)…")
    run = client.scenarios.start_run_and_await_env_ready(
        scenario_id=scenario_id,
        run_name=f"{EMAIL}-resources-check-run"
    )
    run_id = run.id
    devbox_id = run.devbox_id
    print(f"[3] Scenario run started: {run_id}")
    print(f"[3] Using devbox: {devbox_id}")

    print("[3] Uploading resources & editing me.txt…")
    copy_resources_directory(client, devbox_id)
    put_text_file(client, devbox_id, "resources/me.txt", f"email={EMAIL}")

    print("[3] Executing test script…")
    run_test_script(client, devbox_id)

    print("[3] Scoring & completing scenario run…")
    client.scenarios.runs.score_and_complete(run_id)

    write_answers({"ext-scenario-run-id": run_id})
    print(f"[3] Wrote ext-scenario-run-id = {run_id} to answers.json")


if __name__ == "__main__":
    main()