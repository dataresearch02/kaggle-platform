#!/usr/bin/env python3
"""Arena build-and-deploy pipeline for the ocp4.lab.local cluster.

Runs on this connected host. Builds only components whose committed sources
changed, using the offline Dockerfiles in sources/, pushes them to the mirror
Quay and rolls them out to the arena namespace, rolling back on failure.

  python3 deploy/pipeline.py plan        show what a run would build and deploy
  python3 deploy/pipeline.py run         test, build, push, deploy and verify
  python3 deploy/pipeline.py releases    list recorded releases
  python3 deploy/pipeline.py rollback    redeploy the release before the current one
"""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
ROOT = DEPLOY.parent
KIT = ROOT / "sources"
RELEASES = DEPLOY / "releases"
STATE = DEPLOY / "state"
WORK = DEPLOY / ".work"
LOGS = DEPLOY / "logs"

REGISTRY = os.environ.get("ARENA_REGISTRY", "registry.ocp4.lab.local:8443/init")
AUTHFILE = os.environ.get("REGISTRY_AUTH_FILE", str(Path.home() / ".docker/config.json"))
NAMESPACE = "arena"
HOSTNAME = "arena.apps.ocp4.lab.local"
DEPLOYMENTS = ("api", "evaluation-worker", "jupyterhub", "web")
# Bump to rebuild every component after changing how images are built.
BUILD_RECIPE = "1"

COMPONENTS = {
    "api": {"paths": ["apps/api"], "bases": ["python"], "wheels": "python/api"},
    "hub": {"paths": ["infra/jupyterhub"], "bases": ["hub"], "wheels": "python/hub"},
    "web": {"paths": ["apps/web"], "bases": ["node", "nginx"], "wheels": None},
    "runtime": {"paths": ["infra/singleuser"], "bases": ["runtime"], "wheels": "python/runtime"},
}
IMAGE_ENV = {"api": "API_IMAGE", "hub": "HUB_IMAGE", "web": "WEB_IMAGE", "runtime": "RUNTIME_IMAGE"}
# Changes here need new wheels or npm tarballs downloaded from the internet.
DEPENDENCY_SPECS = [
    "apps/api/requirements.txt",
    "apps/api/requirements-dev.txt",
    "apps/web/package.json",
    "apps/web/package-lock.json",
    "package.json",
    "package-lock.json",
    "infra/singleuser/requirements-training.txt",
    "sources/scripts/bundle.py",
]
# Changes limited to these only need the npm cache refreshed.
NPM_SPECS = ["apps/web/package.json", "apps/web/package-lock.json", "package.json", "package-lock.json"]
BUILD_INPUTS = [
    "apps",
    "infra",
    "scripts",
    "sources/.dockerignore",
    "sources/dockerfiles",
    "sources/scripts",
    "package.json",
    "package-lock.json",
]


class PipelineError(Exception):
    pass


def log(message):
    print(f"\n==> {message}", flush=True)


def run(*args, capture=False, check=True, quiet=False, env=None, input=None, cwd=None):
    args = [str(arg) for arg in args]
    if not quiet:
        print("+ " + " ".join(args), flush=True)
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        raise PipelineError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


def git(*args):
    return run("git", "-C", ROOT, *args, capture=True, quiet=True).stdout.strip()


def oc(*args, check=True):
    return run("oc", *args, capture=True, quiet=True, check=check)


# ---------------------------------------------------------------- sources


def dirty_sources():
    return git("status", "--porcelain", "--untracked-files=all", "--", *BUILD_INPUTS)


def spec_digests(commit):
    digests = {}
    for path in DEPENDENCY_SPECS:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{commit}:{path}"], capture_output=True
        )
        digests[path] = hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None
    return digests


def record_dependencies(digests):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "dependencies.json").write_text(json.dumps({"digests": digests}, indent=2) + "\n")


def changed_dependency_specs():
    path = STATE / "dependencies.json"
    if not path.exists():
        # The offline kit's wheels and npm cache were prepared from this commit.
        commit = json.loads((KIT / "manifests/source.json").read_text())["git_commit"]
        digests = spec_digests(commit)
        head = spec_digests("HEAD")
        for spec, digest in digests.items():
            # Kit tooling committed after the kit was prepared is the copy that prepared it.
            if digest is None and spec.startswith("sources/"):
                digests[spec] = head[spec]
        record_dependencies(digests)
    recorded = json.loads(path.read_text())["digests"]
    head = spec_digests("HEAD")
    return [spec for spec in DEPENDENCY_SPECS if head[spec] != recorded.get(spec)]


def base_record(name):
    return json.loads((KIT / "images/base" / f"{name}.json").read_text())


def component_image(name):
    spec = COMPONENTS[name]
    state = hashlib.sha256(f"recipe={BUILD_RECIPE}\n".encode())
    for path in spec["paths"] + ["sources/.dockerignore", f"sources/dockerfiles/{name}.Dockerfile"]:
        state.update(f"{path}={git('rev-parse', 'HEAD:' + path)}\n".encode())
    for base in spec["bases"]:
        state.update(f"base:{base}={base_record(base)['image_id']}\n".encode())
    if spec["wheels"]:
        for wheel in sorted((KIT / spec["wheels"]).glob("*.whl")):
            state.update(f"wheel:{wheel.name}:{wheel.stat().st_size}\n".encode())
    return f"{REGISTRY}/arena-{name}:src-{state.hexdigest()[:12]}"


def load_bundle():
    spec = importlib.util.spec_from_file_location("arena_bundle", KIT / "scripts/bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- images


def ensure_base(name):
    record = base_record(name)
    result = subprocess.run(
        ["podman", "image", "inspect", "--format", "{{.Id}}", record["offline_tag"]],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != record["image_id"]:
        run("podman", "load", "-i", KIT / "images/base" / f"{name}.tar")
    return record


def refresh_dependencies():
    log("Dependency files changed since the kit was prepared: downloading wheels and npm cache")
    for marker in sorted((KIT / "images/base").glob("*.json")):
        record = ensure_base(marker.stem)
        # bundle.py resolves bases by upstream tag. Point that tag at the kit's
        # recorded image so it reuses the pinned base instead of pulling a newer one.
        run("podman", "tag", record["image_id"], record["upstream"])
    run(sys.executable, KIT / "scripts/bundle.py", "prepare", cwd=ROOT)
    record_dependencies(spec_digests("HEAD"))


def refresh_npm_cache():
    log("Refreshing the npm cache for the web build (needs internet)")
    record = ensure_base("node")
    cache = KIT / "node/cache"
    cache.mkdir(parents=True, exist_ok=True)
    # Directory listings left by copying the kit over HTTP (index.html?C=N;O=D...)
    # are not cache entries, and npm cache verify crashes on them.
    for listing in cache.rglob("index.html*"):
        listing.unlink()
    try:
        # Same steps as bundle.py prepare: install inside Alpine so platform-specific
        # tarballs (esbuild, rollup) match the offline build.
        run(
            "podman", "run", "--rm", "--user", "0:0", "--security-opt", "label=disable",
            "-v", f"{KIT}:/bundle:rw", "--entrypoint", "sh", record["offline_tag"], "-ec",
            "mkdir -p /tmp/web && cp /bundle/project/apps/web/package*.json /tmp/web/\n"
            "cd /tmp/web && npm ci --cache /bundle/node/cache --no-audit --no-fund\n"
            "npm cache verify --cache /bundle/node/cache",
        )
    finally:
        # npm debug logs can contain network configuration; keep them out of the kit.
        shutil.rmtree(cache / "_logs", ignore_errors=True)
    recorded = json.loads((STATE / "dependencies.json").read_text())["digests"]
    head = spec_digests("HEAD")
    recorded.update({spec: head[spec] for spec in NPM_SPECS})
    record_dependencies(recorded)


def registry_has(image):
    return (
        subprocess.run(
            ["skopeo", "inspect", "--raw", "--authfile", AUTHFILE, f"docker://{image}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def test_api():
    log("API tests (offline, arbitrary UID)")
    ensure_base("python")
    run(
        "podman", "run", "--rm", "--network", "none", "--security-opt", "label=disable",
        "--user", "123456:0", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
        # Mount the whole snapshot: some tests reach repository files such as scripts/.
        "-v", f"{KIT / 'project'}:/repo:ro",
        "-v", f"{KIT / 'python/api'}:/wheels:ro",
        "-w", "/repo/apps/api", "--entrypoint", "sh",
        base_record("python")["offline_tag"], "-ec",
        "pip install --quiet --disable-pip-version-check --no-index --find-links /wheels"
        " --target /tmp/deps -r requirements-dev.txt\n"
        "PYTHONPATH=/tmp/deps python -m pytest -q -p no:cacheprovider tests",
    )


def build(name, image, commit, no_cache):
    log(f"Build {name} -> {image}")
    for base in COMPONENTS[name]["bases"]:
        ensure_base(base)
    command = [
        "podman", "build", "--network=none", "--pull=never",
        "--label", f"org.opencontainers.image.revision={commit}",
        "--label", f"io.arena.component={name}",
        "-f", KIT / "dockerfiles" / f"{name}.Dockerfile", "-t", image,
    ]
    if no_cache:
        command.append("--no-cache")
    run(*command, KIT)


def push(name, image):
    log(f"Push {image}")
    tag = image.rsplit(":", 1)[1]
    layout = WORK / f"oci-{name}"
    shutil.rmtree(layout, ignore_errors=True)
    # Quay's registry worker times out on multi-GB single-request layer uploads,
    # so compress into an OCI layout and upload it in chunks.
    run(
        "skopeo", "copy", "--quiet", "--dest-compress", "--dest-compress-format", "gzip",
        f"containers-storage:{image}", f"oci:{layout}:{tag}",
    )
    run(sys.executable, DEPLOY / "push_oci_chunked.py", layout, tag, image)
    shutil.rmtree(layout, ignore_errors=True)


def prune_local_images(keep):
    result = run(
        "podman", "images", "--format", "{{.Repository}}:{{.Tag}}",
        "--filter", f"reference={REGISTRY}/arena-*", capture=True, quiet=True,
    )
    for reference in result.stdout.split():
        if ":src-" in reference and reference not in keep:
            run("podman", "rmi", reference, check=False)


# ---------------------------------------------------------------- cluster


def live_images():
    result = oc("get", "deploy", "api", "jupyterhub", "web", "-n", NAMESPACE, "-o", "json", check=False)
    config = oc("get", "configmap", "arena-config", "-n", NAMESPACE, "-o", "json", check=False)
    if result.returncode or config.returncode:
        return {}
    names = {"api": "api", "jupyterhub": "hub", "web": "web"}
    images = {
        names[item["metadata"]["name"]]: item["spec"]["template"]["spec"]["containers"][0]["image"]
        for item in json.loads(result.stdout)["items"]
    }
    images["runtime"] = json.loads(config.stdout)["data"]["NOTEBOOK_IMAGE"]
    return images


def render(images, output):
    env = dict(os.environ, **{IMAGE_ENV[name]: image for name, image in images.items()})
    run(DEPLOY / "render.sh", output, env=env, quiet=True)


def manifest_changes(manifest):
    result = run(
        "oc", "diff", "-f", manifest, "-f", DEPLOY / "postgres.yaml",
        capture=True, check=False, quiet=True,
    )
    if result.returncode > 1:
        raise PipelineError("oc diff failed")
    changes = []
    for line in result.stdout.splitlines():
        if line.startswith("diff -u -N "):
            # e.g. /tmp/LIVE-123/apps.v1.Deployment.arena.api
            parts = line.split()[3].rsplit("/", 1)[1].split(".")
            changes.append(f"{parts[-3]}/{parts[-1]}")
    return changes


def active_evaluations():
    jobs = json.loads(oc("get", "jobs", "-n", NAMESPACE, "-l", "arena.evaluation=true", "-o", "json").stdout)
    return [j["metadata"]["name"] for j in jobs["items"] if j.get("status", {}).get("active")]


def fetch(path):
    context = ssl._create_unverified_context()  # router default certificate
    try:
        with urllib.request.urlopen(f"https://{HOSTNAME}{path}", context=context, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, OSError) as error:
        return 0, str(error).encode()


def smoke_test():
    log("Smoke tests")
    checks = [
        ("portal /", lambda: fetch("/")[0] == 200),
        ("API /api/health", lambda: fetch("/api/health") == (200, b'{"status":"ok"}')),
    ]
    for label, check in checks:
        for attempt in range(24):
            if check():
                print(f"ok   {label}")
                break
            time.sleep(5)
        else:
            raise PipelineError(f"smoke test failed: {label}")
    run(
        "oc", "exec", "-n", NAMESPACE, "deploy/api", "--", "python", "-c",
        "import urllib.request; urllib.request.urlopen("
        "'http://jupyterhub:8081/jupyter/hub/health', timeout=10)",
        quiet=True,
    )
    print("ok   API -> JupyterHub service")
    slices = json.loads(
        oc("get", "endpointslices", "-n", NAMESPACE, "-l",
           "kubernetes.io/service-name=jupyterhub", "-o", "json").stdout
    )
    targets = [
        endpoint.get("targetRef", {}).get("name", "")
        for item in slices["items"]
        for endpoint in item.get("endpoints") or []
    ]
    if not targets or any(not name.startswith("jupyterhub-") for name in targets):
        raise PipelineError(f"jupyterhub Service has unexpected endpoints: {targets}")
    print("ok   jupyterhub Service targets only the Hub")


def deploy(manifest, runtime_image, live_runtime):
    log("Validate manifests (server-side dry run)")
    run("oc", "apply", "--dry-run=server", "-f", manifest, "-f", DEPLOY / "postgres.yaml", capture=True)
    if runtime_image != live_runtime:
        log("Cache the new runtime image on every node before switching to it")
        daemonsets = [i for i in json.loads(Path(manifest).read_text())["items"] if i["kind"] == "DaemonSet"]
        run("oc", "apply", "-f", "-", input=json.dumps({"apiVersion": "v1", "kind": "List", "items": daemonsets}))
        run("oc", "rollout", "status", "daemonset/arena-runtime-prepull", "-n", NAMESPACE, "--timeout=45m")
    log("Apply")
    applied = run("oc", "apply", "-f", manifest, "-f", DEPLOY / "postgres.yaml", capture=True)
    for line in applied.stdout.splitlines():
        if not line.endswith(" unchanged"):
            print(line)
    for name in DEPLOYMENTS:
        run("oc", "rollout", "status", f"deployment/{name}", "-n", NAMESPACE, "--timeout=10m")
    smoke_test()


# ---------------------------------------------------------------- releases


def releases():
    if not RELEASES.exists():
        return []
    records = [json.loads(p.read_text()) for p in RELEASES.glob("*/release.json")]
    return sorted(records, key=lambda r: r["id"])


def current_release():
    path = RELEASES / "current"
    return path.read_text().strip() if path.exists() else None


def save_release(record):
    directory = RELEASES / record["id"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "release.json").write_text(json.dumps(record, indent=2) + "\n")


def set_current(release_id):
    (RELEASES / "current").write_text(release_id + "\n")


def new_release(commit, images, status, note=""):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "id": f"{stamp}-{commit[:7]}",
        "commit": commit,
        "images": images,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    save_release(record)
    return record


def ensure_baseline():
    if current_release():
        return
    live = live_images()
    if len(live) != len(COMPONENTS):
        return
    record = new_release("0000000", live, "baseline", "images live before the first pipeline run")
    render(live, RELEASES / record["id"] / "manifest.json")
    set_current(record["id"])
    print(f"Recorded baseline release {record['id']} from the live cluster")


def redeploy(record, live):
    manifest = RELEASES / record["id"] / "manifest.json"
    deploy(manifest, record["images"]["runtime"], live.get("runtime"))
    set_current(record["id"])


# ---------------------------------------------------------------- commands


def compute_plan():
    commit = git("rev-parse", "HEAD")
    live = live_images()
    components = {}
    for name in COMPONENTS:
        image = component_image(name)
        changed = live.get(name) != image
        if not changed:
            action = "unchanged"
        elif registry_has(image):
            action = "deploy (already built)"
        else:
            action = "build, push, deploy"
        components[name] = {"image": image, "live": live.get(name), "action": action}
    return commit, live, components


def print_plan(commit, components):
    print(f"Commit    {git('log', '-1', '--format=%h %s', commit)}")
    print(f"Registry  {REGISTRY}")
    for name, item in components.items():
        live = (item["live"] or "-").rsplit(":", 1)[-1]
        print(f"  {name:8} {item['action']:24} {item['image'].rsplit(':', 1)[1]:18} live: {live}")


def command_plan(args):
    dirty = dirty_sources()
    if dirty:
        print("WARNING: uncommitted changes are NOT included in a run:\n" + dirty)
    changed = changed_dependency_specs()
    if changed:
        print(f"Dependency files changed ({', '.join(changed)}): a run refreshes them from the internet first.")
    commit, live, components = compute_plan()
    print_plan(commit, components)
    images = {name: item["image"] for name, item in components.items()}
    with tempfile.TemporaryDirectory() as temporary:
        manifest = Path(temporary) / "manifest.json"
        render(images, manifest)
        changes = manifest_changes(manifest)
    print("Cluster objects that would change: " + (", ".join(changes) if changes else "none"))


def command_run(args):
    dirty = dirty_sources()
    if dirty:
        raise PipelineError("Commit or stash these changes first; images are built from committed sources:\n" + dirty)
    ensure_baseline()
    previous = current_release()

    log("Snapshot committed sources into sources/project")
    load_bundle().snapshot()
    changed = changed_dependency_specs()
    if args.refresh_deps or any(spec not in NPM_SPECS for spec in changed):
        refresh_dependencies()
        args.no_cache = True
    elif args.refresh_npm or changed:
        refresh_npm_cache()

    commit, live, components = compute_plan()
    print_plan(commit, components)
    images = {name: item["image"] for name, item in components.items()}
    to_build = [name for name, item in components.items() if item["action"] == "build, push, deploy"]

    if "api" in to_build and not args.skip_tests:
        test_api()
    for name in to_build:
        build(name, images[name], commit, args.no_cache)
        push(name, images[name])

    record = new_release(commit, images, "deploying")
    manifest = RELEASES / record["id"] / "manifest.json"
    render(images, manifest)
    changes = manifest_changes(manifest)
    if not changes:
        record["status"] = "deployed"
        record["note"] = "no cluster changes"
        save_release(record)
        set_current(record["id"])
        log("Cluster already matches this commit; nothing to deploy")
        return

    busy = active_evaluations()
    if busy and live.get("api") != images["api"] and not args.force:
        record["status"] = "cancelled"
        save_release(record)
        raise PipelineError(
            f"Evaluation jobs are running ({', '.join(busy)}); restarting the worker would fail them. "
            "Re-run later (built images are reused) or pass --force."
        )

    log(f"Deploy release {record['id']}: {', '.join(changes)}")
    try:
        deploy(manifest, images["runtime"], live.get("runtime"))
    except PipelineError as error:
        record["status"] = "failed"
        record["note"] = str(error)
        save_release(record)
        target = next((r for r in releases() if r["id"] == previous), None)
        if target and not args.no_rollback:
            log(f"Deployment failed ({error}); rolling back to {previous}")
            redeploy(target, live_images())
            raise PipelineError(f"deployment failed and was rolled back to {previous}: {error}")
        raise
    record["status"] = "deployed"
    save_release(record)
    set_current(record["id"])

    notebooks = json.loads(oc("get", "pods", "-n", NAMESPACE, "-l", "arena.notebook=true", "-o", "json").stdout)
    stale = [
        p["metadata"]["name"]
        for p in notebooks["items"]
        if p["spec"]["containers"][0]["image"] != images["runtime"]
    ]
    if stale:
        print(f"Note: running notebook servers keep the old runtime until restarted: {', '.join(stale)}")
    keep = set(images.values())
    old = next((r for r in releases() if r["id"] == previous), None)
    if old:
        keep.update(old["images"].values())
    prune_local_images(keep)
    log(f"Release {record['id']} deployed")


def command_releases(args):
    current = current_release()
    for record in releases():
        marker = "*" if record["id"] == current else " "
        tags = " ".join(f"{k}={v.rsplit(':', 1)[1]}" for k, v in record["images"].items())
        print(f"{marker} {record['id']:26} {record['status']:10} {tags} {record.get('note', '')}")


def command_rollback(args):
    current = current_release()
    candidates = [r for r in releases() if r["status"] in ("deployed", "baseline")]
    if args.to:
        target = next((r for r in candidates if r["id"] == args.to), None)
    else:
        ids = [r["id"] for r in candidates]
        earlier = [r for r in candidates if current is None or r["id"] < current]
        target = earlier[-1] if earlier and current in ids else None
    if target is None:
        raise PipelineError("no earlier deployed release to roll back to (see: pipeline.py releases)")
    log(f"Roll back from {current} to {target['id']}")
    redeploy(target, live_images())
    log(f"Rolled back to {target['id']} (database schema changes are not reverted)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="show what a run would build and deploy")
    run_parser = commands.add_parser("run", help="test, build, push, deploy and verify")
    run_parser.add_argument("--skip-tests", action="store_true", help="skip the offline API tests")
    run_parser.add_argument("--no-cache", action="store_true", help="rebuild image layers from scratch")
    run_parser.add_argument("--refresh-deps", action="store_true", help="re-download wheels and npm cache")
    run_parser.add_argument("--refresh-npm", action="store_true", help="re-download only the npm cache")
    run_parser.add_argument("--force", action="store_true", help="deploy even while evaluations run")
    run_parser.add_argument("--no-rollback", action="store_true", help="leave a failed release in place")
    commands.add_parser("releases", help="list recorded releases")
    rollback_parser = commands.add_parser("rollback", help="redeploy an earlier release")
    rollback_parser.add_argument("--to", metavar="RELEASE", help="release id (default: the one before current)")
    args = parser.parse_args()

    if args.command in ("run", "rollback") and not os.environ.get("ARENA_PIPELINE_LOG"):
        LOGS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = LOGS / f"{stamp}-{args.command}.log"
        env = dict(os.environ, ARENA_PIPELINE_LOG=str(log_path))
        child = subprocess.Popen(
            [sys.executable, "-u", __file__, *sys.argv[1:]],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        with log_path.open("wb") as output:
            for line in child.stdout:
                sys.stdout.buffer.write(line)
                sys.stdout.flush()
                output.write(line)
        code = child.wait()
        print(f"Log: {log_path}")
        sys.exit(code)

    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "pipeline.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("Another pipeline command is running")
        try:
            {
                "plan": command_plan,
                "run": command_run,
                "releases": command_releases,
                "rollback": command_rollback,
            }[args.command](args)
        except PipelineError as error:
            print(f"\nPIPELINE FAILED: {error}", file=sys.stderr, flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
