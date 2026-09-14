#!/usr/bin/env python3
"""Push an OCI image layout to a registry using chunked blob uploads.

skopeo/podman send each layer as one request; the mirror Quay's gunicorn worker
times out on multi-GB layers (502). Chunked uploads keep every request small.

Usage: push_oci_chunked.py OCI_DIR SOURCE_TAG REGISTRY/REPO:TAG
Credentials come from ~/.docker/config.json (or REGISTRY_AUTH_FILE).
"""

import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

CHUNK = 64 * 1024 * 1024


def ca_bundle(host):
    certs = Path("/etc/containers/certs.d") / host / "ca.crt"
    if certs.exists():
        return str(certs)
    return "/etc/pki/tls/certs/ca-bundle.crt"


class Registry:
    def __init__(self, host, repo):
        self.host, self.repo = host, repo
        self.base = f"https://{host}"
        self.session = requests.Session()
        self.session.verify = ca_bundle(host)
        authfile = os.getenv("REGISTRY_AUTH_FILE", str(Path.home() / ".docker/config.json"))
        encoded = json.loads(Path(authfile).read_text())["auths"][host]["auth"]
        self.basic = tuple(base64.b64decode(encoded).decode().split(":", 1))
        self.token = None

    def login(self):
        challenge = self.session.get(f"{self.base}/v2/").headers["WWW-Authenticate"]
        fields = dict(
            part.split("=", 1) for part in challenge[len("Bearer ") :].split(",")
        )
        fields = {k: v.strip('"') for k, v in fields.items()}
        response = self.session.get(
            fields["realm"],
            params={
                "service": fields["service"],
                "scope": f"repository:{self.repo}:push,pull",
            },
            auth=self.basic,
        )
        response.raise_for_status()
        self.token = response.json()["token"]

    def request(self, method, url, **kwargs):
        for attempt in range(2):
            if self.token is None:
                self.login()
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {self.token}"
            response = self.session.request(
                method, urljoin(self.base, url), headers=headers, **kwargs
            )
            kwargs["headers"] = headers
            if response.status_code != 401:
                return response
            self.token = None
        return response

    def has_blob(self, digest):
        return self.request("HEAD", f"/v2/{self.repo}/blobs/{digest}").status_code == 200

    def upload_blob(self, path, digest):
        size = path.stat().st_size
        response = self.request("POST", f"/v2/{self.repo}/blobs/uploads/")
        if response.status_code != 202:
            raise RuntimeError(f"start upload: {response.status_code} {response.text[:200]}")
        location = response.headers["Location"]
        offset = 0
        with path.open("rb") as source:
            while offset < size:
                data = source.read(CHUNK)
                end = offset + len(data) - 1
                response = self.request(
                    "PATCH",
                    location,
                    data=data,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "Content-Range": f"{offset}-{end}",
                        "Content-Length": str(len(data)),
                    },
                )
                if response.status_code != 202:
                    raise RuntimeError(
                        f"chunk {offset}-{end}: {response.status_code} {response.text[:200]}"
                    )
                location = response.headers["Location"]
                offset = end + 1
                print(f"    {offset / size:6.1%} of {size / 2**30:.2f} GiB", flush=True)
        separator = "&" if "?" in location else "?"
        response = self.request("PUT", f"{location}{separator}digest={digest}")
        if response.status_code != 201:
            raise RuntimeError(f"commit {digest}: {response.status_code} {response.text[:200]}")


def main():
    oci_dir, source_tag, destination = sys.argv[1:4]
    host, rest = destination.split("/", 1)
    repo, tag = rest.rsplit(":", 1)
    layout = Path(oci_dir)
    index = json.loads((layout / "index.json").read_text())
    entry = next(
        m
        for m in index["manifests"]
        if m.get("annotations", {}).get("org.opencontainers.image.ref.name") == source_tag
    )

    def blob(digest):
        algorithm, value = digest.split(":", 1)
        return layout / "blobs" / algorithm / value

    manifest_bytes = blob(entry["digest"]).read_bytes()
    manifest = json.loads(manifest_bytes)
    registry = Registry(host, repo)
    for descriptor in [manifest["config"], *manifest["layers"]]:
        digest = descriptor["digest"]
        if registry.has_blob(digest):
            print(f"exists  {digest[:19]}", flush=True)
            continue
        print(f"upload  {digest[:19]} ({descriptor['size'] / 2**20:.0f} MiB)", flush=True)
        for attempt in range(3):
            try:
                registry.upload_blob(blob(digest), digest)
                break
            except (RuntimeError, requests.RequestException) as error:
                print(f"    retry after error: {error}", flush=True)
        else:
            raise SystemExit(f"failed to upload {digest}")
    response = registry.request(
        "PUT",
        f"/v2/{repo}/manifests/{tag}",
        data=manifest_bytes,
        headers={"Content-Type": manifest.get("mediaType", entry["mediaType"])},
    )
    if response.status_code != 201:
        raise SystemExit(f"manifest: {response.status_code} {response.text[:300]}")
    print(f"pushed {destination} {response.headers.get('Docker-Content-Digest')}")


if __name__ == "__main__":
    main()
