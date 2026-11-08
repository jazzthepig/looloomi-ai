"""T-292 探针(第 8 版):停掉卡住的旧拉数进程,列出还活着哪些。"""
import os
import signal
import subprocess
import sys

out = subprocess.run(["ps", "-eo", "pid,etime,command"], capture_output=True, text=True).stdout
killed = []
for line in out.splitlines():
    if "t292_pull.py" in line and "grep" not in line:
        pid = int(line.split()[0])
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception as e:
            print("kill failed", pid, e)
print("killed:", killed)
