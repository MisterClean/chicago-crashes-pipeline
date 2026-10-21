#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" = 0 ]; then
    # Railway mounts persistent volumes as root. Initialize ownership once, then
    # run all SQL, GDAL and HTTP work without root privileges.
    mkdir -p "$DATA_DIR"
    if [ "$(stat -c %u "$DATA_DIR")" != 10001 ]; then
        chown -R 10001:10001 "$DATA_DIR"
    fi
    exec gosu 10001:10001 /usr/local/bin/crashes-server "$@"
fi
exec /usr/local/bin/crashes-server "$@"
