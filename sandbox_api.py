from fastapi import FastAPI
import subprocess
import tempfile
import os
import uuid

app = FastAPI()


@app.post("/run")
async def run_code(payload: dict):

    code = payload.get("code", "")

    blocked = [
        "os.system",
        "subprocess",
        "socket",
        "shutil",
        "__import__",
        "open("
    ]

    for b in blocked:
        if b in code:
            return {
                "stdout": "",
                "stderr": f"BLOCKED: {b}"
            }

    session = str(uuid.uuid4())

    with tempfile.TemporaryDirectory() as tmp:

        path = os.path.join(tmp, f"{session}.py")

        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            proc = subprocess.run(
                ["python3", path],
                capture_output=True,
                text=True,
                timeout=3
            )

            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr
            }

        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": "TIMEOUT"
              }
