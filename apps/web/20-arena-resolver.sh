#!/bin/sh
set -eu

# Use the container runtime's DNS server on both Docker and Podman. Resolve the
# API service periodically so recreating it does not leave nginx using an old IP.
arena_resolvers=$(awk '$1 == "nameserver" { if (index($2, ":")) printf "[%s] ", $2; else printf "%s ", $2 }' /etc/resolv.conf)
if [ -z "$arena_resolvers" ]; then
    echo 'No container DNS resolver was configured' >&2
    exit 1
fi
printf 'resolver %s valid=10s ipv6=off;\n' "$arena_resolvers" > /etc/nginx/conf.d/00-arena-resolver.conf
