#!/usr/bin/env python3
"""Проверка кластера CloudNativePG. Коды выхода: 0 OK, 1 WARNING, 2 CRITICAL."""
import json
import subprocess
import sys

CTX, NS, CLUSTER = "multi", "shop", "shop-db"
MAX_LAG_BYTES = 1_000_000


def kubectl(*args):
    r = subprocess.run(["kubectl", "--context", CTX, "-n", NS, *args],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout


def main():
    try:
        c = json.loads(kubectl("get", "cluster", CLUSTER, "-o", "json"))
    except Exception as e:
        print(f"CRITICAL: cannot read cluster: {e}")
        return 2

    want = c["spec"]["instances"]
    st = c.get("status", {})
    ready = st.get("readyInstances", 0)
    primary = st.get("currentPrimary")
    phase = st.get("phase", "unknown")

    if not primary:
        print("CRITICAL: no primary")
        return 2
    if ready == 0:
        print("CRITICAL: no ready instances")
        return 2

    warnings = []
    if ready < want:
        warnings.append(f"ready {ready}/{want}")

    # отставание реплик: сколько байт WAL ещё не воспроизведено
    sql = ("select application_name, state, "
           "coalesce(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn), 0)::bigint "
           "from pg_stat_replication")
    try:
        out = kubectl("exec", primary, "-c", "postgres", "--",
                      "psql", "-tA", "-F", "|", "-c", sql)
        rows = [line.split("|") for line in out.strip().splitlines() if line]
    except Exception as e:
        print(f"CRITICAL: cannot query replication: {e}")
        return 2

    if len(rows) < want - 1:
        warnings.append(f"replicas connected {len(rows)}/{want - 1}")
    for name, state, lag in rows:
        if state != "streaming":
            warnings.append(f"{name}: state={state}")
        if int(lag) > MAX_LAG_BYTES:
            warnings.append(f"{name}: lag {lag} bytes")

    if warnings:
        print(f"WARNING: phase='{phase}', primary={primary}; " + "; ".join(warnings))
        return 1
    print(f"OK: primary={primary}, ready {ready}/{want}, replicas streaming")
    return 0


if __name__ == "__main__":
    sys.exit(main())
