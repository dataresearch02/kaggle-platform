"""Add a local service token without replacing existing environment settings."""

from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
path = root / ".env"
content = path.read_text() if path.exists() else (root / ".env.example").read_text()
lines = content.splitlines()
key = "JUPYTERHUB_API_TOKEN="
found = False
for index, line in enumerate(lines):
    if line.startswith(key):
        found = True
        if len(line[len(key) :].strip()) < 32 or line.endswith("replace-me"):
            lines[index] = key + secrets.token_hex(32)
        break
if not found:
    lines.append(key + secrets.token_hex(32))
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("Notebook service configuration is ready in .env (credentials are not printed).")
