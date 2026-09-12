"""Administrator-controlled inference endpoints; no credentials in task containers."""

import json
import os
from urllib.parse import urlparse
import httpx


def configured():
    entries = json.loads(os.getenv("BENCHMARK_PROVIDERS_JSON", "[]"))
    result = {}
    for entry in entries:
        url = urlparse(entry["url"])
        if (
            url.scheme not in ("http", "https")
            or not url.netloc
            or url.username
            or url.password
        ):
            raise ValueError(
                "Benchmark provider URL must be an HTTP(S) endpoint without credentials"
            )
        if entry["id"] in result:
            raise ValueError("Duplicate benchmark provider ID")
        result[entry["id"]] = entry
    return result


def signature(provider_id):
    import hashlib

    provider = configured().get(provider_id)
    if not provider:
        return None
    return hashlib.sha256(
        json.dumps(
            {k: provider.get(k) for k in ("url", "model", "max_tokens")}, sort_keys=True
        ).encode()
    ).hexdigest()


def catalog():
    return [
        {
            "id": p["id"],
            "label": p.get("label", p["id"]),
            "model": p["model"],
            "available": not p.get("key_env") or bool(os.getenv(p["key_env"])),
        }
        for p in configured().values()
    ]


async def infer(provider_id, prompt):
    provider = configured().get(provider_id)
    if not provider:
        raise ValueError("Provider is not configured on the evaluation worker")
    secret = os.getenv(provider.get("key_env", ""), "")
    if provider.get("key_env") and not secret:
        raise ValueError(
            "Provider credentials are not configured on the evaluation worker"
        )
    if not isinstance(prompt, str) or len(prompt) > 20000:
        raise ValueError("API model prompts must be text of at most 20,000 characters")
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        async with client.stream(
            "POST",
            provider["url"],
            headers=headers,
            json={
                "model": provider["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": min(int(provider.get("max_tokens", 1024)), 4096),
                "temperature": 0,
            },
        ) as response:
            if response.status_code >= 300:
                # Provider error bodies may echo credentials or internal infrastructure.
                raise ValueError(f"Model provider returned HTTP {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1024 * 1024:
                    raise ValueError("Model provider response exceeded 1 MB")
    try:
        content = json.loads(body)["choices"][0]["message"]["content"]
        if not isinstance(content, str) or len(content) > 10000:
            raise ValueError()
        return content
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("Model provider returned an unsupported response")


async def broker(directory_fd, models):
    """Service bounded inference requests through a pinned directory descriptor."""
    import asyncio
    import re
    import stat
    import secrets

    seen = set()
    allowed = {m["version_id"]: m for m in models if m.get("provider_id")}
    while True:
        for filename in os.listdir(directory_fd):
            if (
                not re.fullmatch(r"[0-9a-f]{32}\.request\.json", filename)
                or filename in seen
            ):
                continue
            if len(seen) >= 128:
                return  # The runner times out; never make more billed requests.
            seen.add(filename)
            try:
                fd = os.open(
                    filename,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory_fd,
                )
                with os.fdopen(fd, "rb") as file:
                    info = os.fstat(file.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 100000:
                        raise ValueError("Invalid inference request")
                    request = json.loads(file.read(100001))
                model = allowed.get(request.get("model_version_id"))
                if not model:
                    raise ValueError("Model is not included in this benchmark run")
                provider = configured().get(model["provider_id"])
                if not provider or signature(model["provider_id"]) != model.get(
                    "provider_revision"
                ):
                    raise ValueError("Provider configuration changed; start a new run")
                result = {
                    "output": await infer(model["provider_id"], request.get("prompt"))
                }
            except Exception as exc:
                # Network exception strings include URLs; keep infrastructure private.
                result = {
                    "error": (
                        str(exc)[:500]
                        if isinstance(exc, ValueError)
                        else "Model inference failed"
                    )
                }
            temporary = secrets.token_hex(16) + ".reply.tmp"
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
                dir_fd=directory_fd,
            )
            with os.fdopen(fd, "w") as file:
                json.dump(result, file)
            os.rename(
                temporary,
                filename.replace(".request.", ".response."),
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        await asyncio.sleep(0.1)
