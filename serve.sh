#!/usr/bin/env bash
# Start the app — the API and the built frontend, one process (PLAN 5).
#
#   ./serve.sh                     http://127.0.0.1:8000
#   ./serve.sh --phone             bind every interface, so your phone can reach it
#   ./serve.sh --build             rebuild the frontend first
#   ./serve.sh --reload            restart on backend edits (passed to memo serve)
#
# Unrecognised arguments go to `memo serve` as they are.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

host=127.0.0.1
port=8000
build=auto      # auto: build only when there is nothing to serve | always | never
migrate=yes
pass=()

while (($#)); do
	case "$1" in
	--phone) host=0.0.0.0 ;;
	--host) host="$2"; shift ;;
	--host=*) host="${1#*=}" ;;
	--port) port="$2"; shift ;;
	--port=*) port="${1#*=}" ;;
	--build) build=always ;;
	--no-build) build=never ;;
	--no-migrate) migrate=no ;;
	-h | --help)
		sed -n '2,9p' "$0" | cut -c3-
		exit 0
		;;
	*) pass+=("$1") ;;
	esac
	shift
done

if [[ $build == always || ($build == auto && ! -f $root/frontend/build/index.html) ]]; then
	if [[ ! -d $root/frontend/node_modules ]]; then
		npm --prefix "$root/frontend" install
	fi
	npm --prefix "$root/frontend" run build
fi

# Settings read ./.env, so the server has to be started from backend/.
cd "$root/backend"

if [[ $migrate == yes ]]; then
	uv run alembic upgrade head
fi

if [[ $host == 0.0.0.0 ]]; then
	lan="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]; exit}')"
	if [[ -n ${lan:-} ]]; then
		echo "on this network: http://$lan:$port"
	fi
fi

exec uv run memo serve --host "$host" --port "$port" ${pass[@]+"${pass[@]}"}
