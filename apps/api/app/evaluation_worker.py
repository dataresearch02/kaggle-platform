"""Single durable evaluation consumer for the local Compose deployment."""

import asyncio
import signal
from .db import SessionLocal
from .notebook_commits import commit_worker, migrate_forks


async def serve():
    from sqlalchemy import inspect
    from .db import engine

    # Compose implementations can start the worker while the API creates tables.
    for _ in range(60):
        if inspect(engine).has_table("benchmark_runs"):
            break
        await asyncio.sleep(1)
    else:
        raise RuntimeError("Benchmark schema is not initialized; start the API first")
    from .runtime_jobs import cleanup

    await cleanup()
    with SessionLocal() as db:
        migrate_forks(db)
        from .benchmark_worker import recover

        recover(db)
    from .benchmark_worker import worker as benchmark_worker

    async with asyncio.TaskGroup() as group:
        group.create_task(commit_worker())
        group.create_task(benchmark_worker())


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
