"""JupyterHub lifecycle and private working copies; no code executes in the API."""

import json
import os
from urllib.parse import quote, urlencode, unquote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Notebook, User

router = APIRouter(prefix="/api", tags=["Notebook runtime"])


def hub_username(user):
    # Stable IDs avoid username normalization and container-name collisions.
    return f"arena-{user.id}"


def notebook_document(notebook):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "cells": [
            {
                "id": f"cell-{notebook.id}",
                "cell_type": "code",
                "metadata": {},
                "source": notebook.code.splitlines(keepends=True),
                "execution_count": None,
                "outputs": [],
            }
        ],
    }


class HubClient:
    def __init__(self):
        self.api_url = os.getenv("JUPYTERHUB_API_URL", "").rstrip("/")
        self.proxy_url = os.getenv("JUPYTERHUB_PROXY_URL", "").rstrip("/")
        self.token = os.getenv("JUPYTERHUB_API_TOKEN", "")
        if not all((self.api_url, self.proxy_url, self.token)):
            raise HTTPException(
                503,
                "JupyterHub is not configured. Start the JupyterHub Compose stack and configure the API connection.",
            )

    async def request(self, method, path, *, contents=False, **kwargs):
        base = self.proxy_url if contents else self.api_url
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                result = await client.request(
                    method,
                    base + path,
                    headers={"Authorization": f"token {self.token}"},
                    **kwargs,
                )
        except httpx.RequestError:
            raise HTTPException(
                503,
                "JupyterHub is unreachable. Check the notebook service and try again.",
            )
        if result.status_code >= 500:
            raise HTTPException(
                502,
                "The notebook service could not complete this request. Check JupyterHub logs and retry.",
            )
        if result.status_code in (401, 403):
            raise HTTPException(
                502,
                "JupyterHub rejected the service credentials. Check its token and service roles.",
            )
        return result

    @staticmethod
    def expect(response, statuses=(200,)):
        if response.status_code not in statuses:
            raise HTTPException(
                502,
                "Unexpected response from the notebook service. Try again or check JupyterHub logs.",
            )
        return response

    async def status(self, user):
        response = await self.request("GET", f"/users/{hub_username(user)}")
        if response.status_code == 404:
            return {"state": "stopped"}
        model = self.expect(response).json()
        server = model.get("servers", {}).get("", {})
        if server.get("pending"):
            return {"state": "stopping" if server["pending"] == "stop" else "starting"}
        return {"state": "ready" if server.get("ready") else "stopped"}


def get_hub():
    return HubClient()


@router.get("/notebook-session")
async def session_status(
    user: User = Depends(current_user), hub: HubClient = Depends(get_hub)
):
    return await hub.status(user)


@router.post("/notebook-session")
async def start_session(
    user: User = Depends(current_user), hub: HubClient = Depends(get_hub)
):
    name = hub_username(user)
    result = await hub.request("GET", f"/users/{name}")
    if result.status_code == 404:
        created = await hub.request("POST", f"/users/{name}", json={})
        # A concurrent tab may have created the same Hub user.
        hub.expect(created, (201, 409))
    else:
        hub.expect(result)
    state = await hub.status(user)
    if state["state"] == "stopped":
        response = await hub.request("POST", f"/users/{name}/server", json={})
        # 400 can indicate another request already started the default server.
        if response.status_code == 400:
            state = await hub.status(user)
            if state["state"] not in ("starting", "ready"):
                hub.expect(response, (201, 202))
            return state
        hub.expect(response, (201, 202))
        return {"state": "starting" if response.status_code == 202 else "ready"}
    return state


@router.delete("/notebook-session")
async def stop_session(
    user: User = Depends(current_user), hub: HubClient = Depends(get_hub)
):
    state = await hub.status(user)
    if state["state"] == "starting":
        raise HTTPException(
            409, "Wait for the notebook server to finish starting before stopping it."
        )
    if state["state"] == "ready":
        response = await hub.request("DELETE", f"/users/{hub_username(user)}/server")
        hub.expect(response, (204, 202))
        return {"state": "stopping" if response.status_code == 202 else "stopped"}
    return state


@router.post("/notebooks/{id}/open")
async def open_notebook(
    id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    notebook = db.get(Notebook, id)
    if not notebook:
        raise HTTPException(404, "Notebook not found")
    if (await hub.status(user))["state"] != "ready":
        raise HTTPException(
            409, "Start your notebook server and wait until it is ready."
        )
    name = hub_username(user)
    path = f"arena-notebook-{id}.ipynb"
    endpoint = f"/user/{name}/api/contents/{path}"
    existing = await hub.request("GET", endpoint, contents=True, params={"content": 0})
    if existing.status_code == 404:
        # First-open import only. Never replace the working copy or its outputs.
        hub.expect(
            await hub.request(
                "PUT",
                endpoint,
                contents=True,
                json={
                    "type": "notebook",
                    "format": "json",
                    "content": notebook_document(notebook),
                },
            ),
            (200, 201),
        )
    else:
        hub.expect(existing)
    target = f"/jupyter/user/{name}/lab/tree/{quote(path)}"
    return {
        "url": "/jupyter/hub/arena-login?" + urlencode({"next": target}),
        "path": path,
    }


@router.get("/notebooks/{id}/working-copy")
async def download_working_copy(
    id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    if not db.get(Notebook, id):
        raise HTTPException(404, "Notebook not found")
    if (await hub.status(user))["state"] != "ready":
        raise HTTPException(
            409, "Start your notebook server to download the working copy."
        )
    response = await hub.request(
        "GET",
        f"/user/{hub_username(user)}/api/contents/arena-notebook-{id}.ipynb",
        contents=True,
    )
    if response.status_code == 404:
        raise HTTPException(404, "Open this notebook in JupyterLab first.")
    model = hub.expect(response).json()
    return Response(
        json.dumps(model["content"]),
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="arena-notebook-{id}.ipynb"'
        },
    )


@router.get("/internal/notebook-access", include_in_schema=False)
def notebook_access(request: Request, user: User = Depends(current_user)):
    """Nginx auth_request gate, also applied to kernel WebSocket handshakes."""
    path = unquote(urlsplit(request.headers.get("x-original-uri", "")).path)
    if (
        "\\" in path
        or any(segment in (".", "..") for segment in path.split("/"))
        or "%" in path
    ):
        raise HTTPException(403, "Invalid notebook path")
    name = hub_username(user)
    if path.startswith(f"/jupyter/user/{name}/"):
        return Response(status_code=204)
    # Browser users do not need the Hub management API. Permit only OAuth and UI
    # routes; provisioning and stopping go through authenticated Arena endpoints.
    if path.startswith("/jupyter/hub/api/") and not path.startswith(
        "/jupyter/hub/api/oauth2/"
    ):
        raise HTTPException(403, "Use the Arena notebook controls")
    if path.startswith("/jupyter/user/") or path.startswith("/jupyter/hub/user/"):
        raise HTTPException(403, "This notebook workspace belongs to another user")
    if path.startswith("/jupyter/hub/") or path == "/jupyter/":
        return Response(status_code=204)
    raise HTTPException(403, "Invalid notebook path")
