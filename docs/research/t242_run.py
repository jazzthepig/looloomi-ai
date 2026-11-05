#!/usr/bin/env python3
"""T-242 运行包装:等资金费缓存就绪 → 跑分析 → 抓 deriv(OI 副口径) → 再跑一次。"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache"
RUNLOG = "/Volumes/CometCloudAI/cometcloud-local/research/t242/run.log"


def log(*a):
    print(*a, flush=True)


def wait_rows(table, min_rows, timeout=1800):
    path = os.path.join(CACHE, table + ".json")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(path) as f:
                d = json.load(f)
            if len(d["rows"]) >= min_rows:
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def run(cmd, tag):
    log("=== %s ===" % tag, flush=True)
    with open(RUNLOG, "a") as lg:
        lg.write("\n=== %s %s ===\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), tag))
        lg.flush()
        p = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT)
    log("=== %s exit %s ===" % (tag, p.returncode), flush=True)
    return p.returncode


def main():
    ok = wait_rows("v_funding_daily", 300000)
    log("funding ready:", ok, flush=True)
    if not ok:
        return
    run([sys.executable, os.path.join(HERE, "t242_crowding_setups.py")], "analysis-1-no-deriv")
    run([sys.executable, os.path.join(HERE, "t242_fetch2.py"), "deriv_metrics_daily"], "fetch-deriv")
    run([sys.executable, os.path.join(HERE, "t242_crowding_setups.py")], "analysis-2-with-deriv")
    log("PIPELINE DONE", flush=True)


if __name__ == "__main__":
    main()
