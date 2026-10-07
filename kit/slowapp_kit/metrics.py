"""/out/.metrics.json at job end (docs/SLOWBOARD.md §7.4, M12, resources item 7).

From the container's cgroup: memory.peak, memory.events oom_kill and cpu.stat. Over HTTP (a warm
UI) the cgroup is shared with the UI, so the job child's own ru_maxrss is what admission learns.
"""
import json
import os
import resource
import time

CGROUP = os.environ.get("SLOWAPP_CGROUP", "/sys/fs/cgroup")


def _read(name):
    try:
        with open(os.path.join(CGROUP, name)) as f:
            return f.read()
    except OSError:
        return None


def _kv(text):
    out = {}
    for line in (text or "").splitlines():
        k, _, v = line.partition(" ")
        if v.strip().isdigit():
            out[k] = int(v)
    return out


def collect(started, exit_code, transport="cli", message=""):
    peak = _read("memory.peak")
    events = _kv(_read("memory.events"))
    cpu = _kv(_read("cpu.stat"))
    me, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    m = {
        "exit": exit_code,
        "message": message[:500],
        "transport": transport,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "ru_maxrss_kb": max(me.ru_maxrss, kids.ru_maxrss),        # Linux: kB
        "ru_cpu_ms": int((me.ru_utime + me.ru_stime + kids.ru_utime + kids.ru_stime) * 1000),
    }
    if transport == "cli":
        if peak and peak.strip().isdigit():
            m["memory_peak_kb"] = int(peak) // 1024
        if events:
            m["oom_kill"] = events.get("oom_kill", 0)
        if cpu:
            m["cpu_usec"] = cpu.get("usage_usec")
    return m


def write(out_dir, started, exit_code, transport="cli", message=""):
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, ".metrics.json"), "w") as f:
            json.dump(collect(started, exit_code, transport, message), f)
    except OSError:
        pass                                    # metrics never fail a job
