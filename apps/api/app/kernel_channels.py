"""Wait for both Jupyter channels before sending code once."""

import asyncio
import json
import secrets
import time
from datetime import datetime, timezone


async def wait_for_kernel(socket, username):
    # A new kernel/socket can accept a request before its IOPub subscription
    # is ready. A silent empty execution traverses both real kernel channels.
    # kernel_info replies can be cached by the server without an IOPub response.
    # Only this harmless probe is retried; user code is sent exactly once.
    ready_deadline = time.monotonic() + 30
    ready = False
    while not ready:
        info_id = secrets.token_hex(16)
        await socket.send(
            json.dumps(
                {
                    "header": {
                        "msg_id": info_id,
                        "username": username,
                        "session": secrets.token_hex(16),
                        "date": datetime.now(timezone.utc).isoformat(),
                        "msg_type": "execute_request",
                        "version": "5.3",
                    },
                    "parent_header": {},
                    "metadata": {},
                    "channel": "shell",
                    "buffers": [],
                    "content": {
                        "code": "",
                        "silent": True,
                        "store_history": False,
                        "user_expressions": {},
                        "allow_stdin": False,
                        "stop_on_error": True,
                    },
                }
            )
        )
        shell_ready = iopub_ready = False
        try:
            while not (shell_ready and iopub_ready):
                if time.monotonic() >= ready_deadline:
                    raise ValueError("Kernel channels did not become ready in time")
                raw = await asyncio.wait_for(
                    socket.recv(), min(2, ready_deadline - time.monotonic())
                )
                if not isinstance(raw, str):
                    continue
                message = json.loads(raw)
                if message.get("parent_header", {}).get("msg_id") != info_id:
                    continue
                kind = message["header"]["msg_type"]
                shell_ready = shell_ready or kind == "execute_reply"
                iopub_ready = iopub_ready or (
                    kind == "status"
                    and message["content"].get("execution_state") == "idle"
                )
            ready = True
        except asyncio.TimeoutError:
            if time.monotonic() >= ready_deadline:
                raise ValueError("Kernel channels did not become ready in time")
