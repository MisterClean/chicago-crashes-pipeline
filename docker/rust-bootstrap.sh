#!/bin/sh
# Private maintenance process: starts no database, HTTP server or worker.
set -eu
umask 077

if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Bootstrap hold does not accept commands or arguments.' >&2
    exit 2
fi

DATA_DIR=${DATA_DIR:-/data}
export DATA_DIR
case "$DATA_DIR" in
    /|'') printf '%s\n' 'Bootstrap DATA_DIR must be an absolute data directory.' >&2; exit 2 ;;
    /*) ;;
    *) printf '%s\n' 'Bootstrap DATA_DIR must be absolute.' >&2; exit 2 ;;
esac
if [ "$(readlink -m -- "$DATA_DIR")" != "$DATA_DIR" ]; then
    printf '%s\n' 'Bootstrap DATA_DIR must be canonical without symlink or dot components.' >&2
    exit 2
fi
if [ -L "$DATA_DIR" ]; then
    printf '%s\n' 'Bootstrap DATA_DIR must not be a symlink.' >&2
    exit 2
fi

if [ "$(id -u)" = 0 ]; then
    # Persistent volumes arrive root-owned. No SQL or HTTP work runs as root.
    mkdir -p "$DATA_DIR"
    chmod 700 "$DATA_DIR"
    chown -R 10001:10001 "$DATA_DIR"
    exec gosu 10001:10001 /usr/local/bin/crashes-bootstrap
fi
if [ "$(id -u)" != 10001 ] || [ "$(id -g)" != 10001 ]; then
    printf '%s\n' 'Bootstrap must run as the crashes uid/gid 10001.' >&2
    exit 2
fi
if [ ! -d "$DATA_DIR" ] || [ ! -w "$DATA_DIR" ]; then
    printf '%s\n' 'Bootstrap data directory is missing or not writable.' >&2
    exit 2
fi

export DAILY_SYNC=false
child=
stop() {
    if [ -n "$child" ]; then
        kill "$child" 2>/dev/null || :
        wait "$child" 2>/dev/null || :
    fi
    exit 0
}
trap stop TERM INT
printf '%s\n' 'Private bootstrap hold ready as uid/gid 10001; HTTP and scheduling are stopped.'
while :; do
    sleep 60 &
    child=$!
    wait "$child" || :
    child=
done
