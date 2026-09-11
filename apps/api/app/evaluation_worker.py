"""Single durable evaluation consumer for the local Compose deployment."""

import asyncio
import os
import signal
import httpx
from .db import SessionLocal
from .notebook_commits import commit_worker, migrate_forks


async def serve():
    # A single local consumer owns all containers carrying this label. Clean up
    # interrupted runs before marking their durable jobs failed for explicit retry.
    transport = httpx.AsyncHTTPTransport(
        uds=os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=30
    ) as docker:
        response = await docker.get(
            "/containers/json",
            params={"all": "true", "filters": '{"label":["arena.evaluation=true"]}'},
        )
        response.raise_for_status()
        for container in response.json():
            removed = await docker.delete(
                f"/containers/{container['Id']}", params={"force": "true"}
            )
            removed.raise_for_status()
    with SessionLocal() as db:
        migrate_forks(db)
    await commit_worker()


async def main():
    task = asyncio.create_task(serve())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
