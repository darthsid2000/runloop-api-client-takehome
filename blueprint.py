import json, os
from pathlib import Path
from dotenv import load_dotenv

from runloop_api_client import Runloop
from PIL import Image, ImageDraw, ImageFont

ANSWERS_PATH = Path("answers.json")
PNG_PATH = Path("blueprint.png")

REQUIRED_KEYS = {
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

def read_answers():
    if ANSWERS_PATH.exists():
        return json.loads(ANSWERS_PATH.read_text())
    return dict(REQUIRED_KEYS)

def write_answers(d):
    # make sure all required keys are present (grader depends on this)
    for k, v in REQUIRED_KEYS.items():
        d.setdefault(k, v)
    ANSWERS_PATH.write_text(json.dumps(d, indent=2))

def text_to_png(text: str, out_path: Path, width=900, padding=20):
    lines = (text or "").splitlines() or ["(no output)"]
    font = ImageFont.load_default()
    line_h = font.getbbox("Ag")[3] + 4
    height = padding*2 + max(200, line_h*len(lines))
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill="black")
        y += line_h
    img.save(out_path)

def create_cowsay_blueprint(client: Runloop, name: str):
    dockerfile = r"""
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends cowsay && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
"""
    return client.blueprints.create_and_await_build_complete(
        name=name,
        dockerfile=dockerfile
    )

def run_cowsay_and_save_png(client: Runloop, devbox_id: str, out_path: Path):
    # Try PATH, then explicit Ubuntu path, else print message
    cmd = (
        r"sh -lc '"
        r"(command -v cowsay >/dev/null 2>&1 && cowsay \"Runloop rocks!\") || "
        r"([ -x /usr/games/cowsay ] && /usr/games/cowsay \"Runloop rocks!\") || "
        r"echo \"cowsay not installed or not on PATH\"'"
    )
    res = client.devboxes.execute_sync(id=devbox_id, command=cmd)
    text = (getattr(res, "stdout", None) or getattr(res, "stderr", None) or "").strip() or "(no output)"
    text_to_png(text, out_path)

def main():
    load_dotenv()
    client = Runloop()

    answers = read_answers()

    # 1) Create blueprint with cowsay
    bp_name = f"{os.environ.get('EMAIL')}-cowsay-blueprint"
    print(f"[2] Building blueprint '{bp_name}' (Dockerfile)…")
    try:
        blueprint = create_cowsay_blueprint(client, bp_name)

        print("[2] Blueprint built:", blueprint.id)
        answers["blueprint-name"] = bp_name
        answers["blueprint-id"] = blueprint.id
        write_answers(answers)

        # 2) Boot a devbox from the blueprint
        bp_devbox_name = f"{os.environ.get('EMAIL')}-from-blueprint"
        print("[2] Booting devbox from blueprint…")
        devbox = client.devboxes.create_and_await_running(
            name=bp_devbox_name,
            blueprint_id=blueprint.id,  # field name per SDK
        )
        print("[2] Devbox from blueprint:", devbox.id)
        answers["devbox-from-blueprint-id"] = devbox.id
        answers["devbox-from-blueprint-name"] = getattr(devbox, "name", bp_devbox_name)
        write_answers(answers)

        # 3) Prove cowsay and save blueprint.png
        print("[2] Running cowsay and saving blueprint.png…")
        run_cowsay_and_save_png(client, devbox.id, PNG_PATH)
        print(f"✅ Saved {PNG_PATH}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()