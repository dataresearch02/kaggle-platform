"""Run local Compose with health-ordered startup on Docker and Podman."""

import argparse
import json
import subprocess
import time

from storage import ROOT, project_containers


def run(*args, capture=False):
    return subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def wait_for(service, completed=False):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        ids = run(
            "ps",
            "-a",
            "-q",
            "--filter",
            "label=com.docker.compose.project=arena",
            "--filter",
            f"label=com.docker.compose.service={service}",
            capture=True,
        ).splitlines()
        if ids:
            state = json.loads(run("inspect", ids[0], capture=True))[0]["State"]
            if completed and state["Status"] == "exited":
                if state["ExitCode"] == 0:
                    return
                raise SystemExit(
                    f"{service} failed; inspect docker compose logs {service}"
                )
            if not completed and state.get("Health", {}).get("Status") == "healthy":
                return
            if not completed and state["Status"] in ("exited", "dead"):
                raise SystemExit(
                    f"{service} exited; inspect docker compose logs {service}"
                )
        time.sleep(2)
    raise SystemExit(
        f"Timed out waiting for {service}; inspect docker compose logs {service}"
    )


def stop_stack():
    servers = [
        name
        for name in project_containers(
            run("ps", "--format", "{{.Names}}", capture=True).splitlines(), "arena"
        )
        if name.startswith("arena-notebook-")
    ]
    if servers:
        run("stop", "--time", "60", *servers)
    run("compose", "down")


def repair_podman_dependencies():
    ids = run(
        "ps",
        "-a",
        "-q",
        "--filter",
        "label=com.docker.compose.project=arena",
        capture=True,
    ).splitlines()
    if not ids:
        return
    containers = json.loads(run("inspect", *ids, capture=True))
    if any(container.get("Dependencies") for container in containers):
        # These links cannot be removed from existing containers. Recreate the
        # complete Compose graph to avoid references to deleted dependency IDs.
        print(
            "Repairing Podman dependencies: recreating Arena containers with persistent data retained.",
            flush=True,
        )
        stop_stack()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "down"))
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.action == "down":
        stop_stack()
        return
    if args.build:
        run("compose", "build")
    # podman-compose translates completed dependencies into native --requires,
    # which incorrectly requires exited initialization containers to be running.
    # Suppress that translation and enforce the same gates explicitly here.
    is_podman = "podman" in run("--version", capture=True).lower()
    if not is_podman:
        run("compose", "up", "-d")
        return
    repair_podman_dependencies()
    for service in (
        "storage-check",
        "notebook-image",
        "db",
        "api",
        "evaluation-worker",
        "jupyterhub",
        "web",
    ):
        run(
            "compose",
            "up",
            "-d",
            "--no-deps",
            *(["--force-recreate"] if args.build else []),
            service,
        )
        if service not in ("web", "evaluation-worker"):
            wait_for(service, completed=service in ("storage-check", "notebook-image"))
    print("Arena is running at http://localhost:8080")


if __name__ == "__main__":
    main()
