#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""主机负载归因采样器（每分钟一次，systemd timer 驱动）。

目的：解决「load 峰值到底是谁」这类事后无法归因的问题。
每行一个 JSON，落 logs/host_load.log：
  ts / load1,5,15 / runq(procs running) / nproc
  cpu: user,sys,iowait,idle 1 秒采样增量百分比
  disk: 读 /proc/diskstats 1 秒增量，取读字节最多的那块盘（tps/读MB/排队估计）
  containers: 各容器 CPU% + BlockIO 增量（docker stats --no-stream）
  top: 按 CPU 排序的前 5 个进程

只读，不改任何生产状态；单次耗时约 2~3 秒。
"""
import json, os, subprocess, time, datetime

LOG = "/opt/d4follow/logs/host_load.log"
MAX_BYTES = 20 * 1024 * 1024


def cpu_snapshot():
    with open("/proc/stat") as f:
        parts = f.readline().split()[1:]
    v = [int(x) for x in parts]
    # user nice system idle iowait irq softirq steal
    return {"user": v[0] + v[1], "sys": v[2] + v[5] + v[6], "idle": v[3], "iowait": v[4]}


def disk_snapshot():
    out = {}
    with open("/proc/diskstats") as f:
        for line in f:
            p = line.split()
            if len(p) < 14:
                continue
            name = p[2]
            if not (name.startswith("sd") or name.startswith("vd") or name.startswith("xvd")
                    or name.startswith("nvme") or name.startswith("dm-")):
                continue
            if name[-1].isdigit() and not name.startswith("nvme"):
                continue
            out[name] = {
                "reads": int(p[3]), "rd_sectors": int(p[5]),
                "ios": int(p[3]) + int(p[7]),
            }
    return out


def pct(delta, total):
    return round(100.0 * delta / total, 2) if total > 0 else 0.0


def main():
    c1, d1 = cpu_snapshot(), disk_snapshot()
    time.sleep(1.0)
    c2, d2 = cpu_snapshot(), disk_snapshot()

    dtot = sum(max(0, c2[k] - c1[k]) for k in ("user", "sys", "idle", "iowait"))
    cpu = {
        "user": pct(c2["user"] - c1["user"], dtot),
        "sys": pct(c2["sys"] - c1["sys"], dtot),
        "iowait": pct(c2["iowait"] - c1["iowait"], dtot),
        "idle": pct(c2["idle"] - c1["idle"], dtot),
    }

    disks = []
    for name, v2 in d2.items():
        v1 = d1.get(name)
        if not v1:
            continue
        ios = max(0, v2["ios"] - v1["ios"])
        mb = max(0, v2["rd_sectors"] - v1["rd_sectors"]) * 512 / 1048576.0
        if ios or mb > 1:
            disks.append({"dev": name, "tps": round(ios / 1.0, 1), "rd_MBps": round(mb, 1)})
    disks.sort(key=lambda x: (x["rd_MBps"], x["tps"]), reverse=True)

    conts = []
    try:
        raw = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            stderr=subprocess.DEVNULL, timeout=25).decode("utf-8", "replace")
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:                        # noqa: BLE001
                continue
            conts.append({
                "n": o.get("Name"),
                "cpu": o.get("CPUPerc"),
                "mem": (o.get("MemUsage") or "").split("/")[0].strip(),
                "bio": o.get("BlockIO"),
            })
    except Exception as e:                            # noqa: BLE001
        conts = [{"err": repr(e)[:80]}]

    top = []
    try:
        raw = subprocess.check_output(
            ["ps", "-eo", "pcpu,pmem,stat,comm", "--sort=-pcpu"],
            stderr=subprocess.DEVNULL, timeout=10).decode("utf-8", "replace").splitlines()
        for line in raw[1:6]:
            p = line.split(None, 3)
            if len(p) == 4:
                top.append("%s%% %s %s" % (p[0], p[2], p[3].strip()[:24]))
    except Exception:                                 # noqa: BLE001
        pass

    try:
        with open("/proc/loadavg") as f:
            la = f.read().split()
        load = [la[0], la[1], la[2]]
        runnable = la[3]
    except Exception:                                 # noqa: BLE001
        load, runnable = [], ""

    rec = {
        "ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "load": load, "runnable": runnable,
        "nproc": os.cpu_count(),
        "cpu": cpu, "disk": disks[:3],
        "containers": conts, "top": top,
    }

    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_BYTES:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                             # noqa: BLE001
        print("LOG_ERR", repr(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
