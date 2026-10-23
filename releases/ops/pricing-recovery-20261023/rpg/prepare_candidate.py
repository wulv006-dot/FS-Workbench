"""Create the bounded RPG candidate from the exact incident baseline; never deploy."""
import argparse
import ast
import hashlib
from pathlib import Path
import shutil

EXPECTED = {
    "srv_exec.py": "7b4ceeb1dd9a087060de9aa883ed42dc58d161ca31503d3d08f12d97c7507420",
    "p2pah_local.py": "1e0688eee7f5459b18a3b7c68f7cacc321ad0b2eae3d034914c75352c4527485",
    "admin_cache_local.py": "6287da0b53dfd823bdcb0af29e8384d231de333c96164a5ab10d501558243806",
    "srv_run.py": "6c0dfd5d12076aac8565a4476b16bf57d57342f516a047b4ccf7040eb0c6e8e5",
    "index.html": "9ff319e13f899ea7a340bdd5f16ace497420242921a651a97093c32427da571e",
}

CLEAR_MAIN = '''def clear_main_cache(log=log):
    """Clear Admin cache using the existing FS global owner, with no local login."""
    if admin_cache is None:
        return False, "shared_admin_client_unavailable"
    token = admin_cache.load_token()
    if not token:
        return False, "shared_admin_unavailable"
    for attempt in range(2):
        status, body = admin_cache.clear_cache("all", token)
        try:
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError()
            code = result.get("code")
            message = result.get("msg") or ""
        except (ValueError, TypeError):
            return False, "admin_clear_unconfirmed:http_%s" % status
        if status == 200 and code == 1:
            return True, message
        if status == 200 and code == 0 and _throttled(message) and attempt == 0:
            log("  后台已确认频控，等 31 秒后仅重试清缓存")
            time.sleep(31)
            continue
        return False, "admin_clear_unconfirmed:http_%s_code_%s" % (status, code)
    return False, "admin_clear_unconfirmed"


'''

PHASE = '''
EXECUTION = {"job_id": os.environ.get("FS_RPG_JOB_ID"), "write_attempts": 0, "finished": False}


def save_execution():
    path = os.environ.get("FS_RPG_EXECUTION_RECEIPT")
    if not path:
        raise RuntimeError("execution_receipt_required")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(EXECUTION, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def before_write():
    EXECUTION["write_attempts"] += 1
    save_execution()


def run_job():
    path = os.environ.get("FS_RPG_EXECUTION_RECEIPT")
    if not path and (len(sys.argv) < 2 or sys.argv[1] not in ("write", "writegold")):
        return P.main()
    if not path or not EXECUTION["job_id"]:
        raise RuntimeError("execution_identity_required")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as stream:
            previous = json.load(stream)
        if previous.get("job_id") != EXECUTION["job_id"] or previous.get("write_attempts", 0):
            raise RuntimeError("reconcile_original_execution_before_retry")
    save_execution()
    try:
        return P.main()
    finally:
        EXECUTION["finished"] = True
        save_execution()

'''

CLASSIFY = '''def execution_state(result, phase, returncode):
    """Only a finished, persisted zero-write phase proves failover is safe."""
    complete = (isinstance(result, dict) and isinstance(result.get("jobs"), list)
                and "ok" in result and "fail" in result and isinstance(result.get("mismatch"), list))
    if returncode == 0 and complete:
        return "confirmed", False
    if complete and (result.get("ok") or result.get("mismatch")):
        return "partial", False
    if (returncode not in (0, -9, -1) and phase.get("finished") is True
            and type(phase.get("write_attempts")) is int and phase["write_attempts"] == 0):
        return "prewrite_failed", True
    return "unknown", False


'''


def prepare(baseline, output):
    for name, expected in EXPECTED.items():
        actual = hashlib.sha256((baseline / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("baseline_changed:" + name)
    output.mkdir(parents=True, exist_ok=True)
    text = (baseline / "p2pah_local.py").read_text(encoding="utf-8")
    start = text.index("def clear_main_cache(log=log):")
    end = text.index("def cmd_write(a):", start)
    text = text[:start] + CLEAR_MAIN + text[end:]
    marker = '{"ts": dt.datetime.now().isoformat(timespec="seconds"),'
    assert text.count(marker) == 3
    text = text.replace(marker, '{"operation_id": os.environ.get("FS_RPG_JOB_ID"), "ts": dt.datetime.now().isoformat(timespec="seconds"),')
    ast.parse(text)
    (output / "p2pah_local.py").write_bytes(text.encode("utf-8"))

    text = (baseline / "srv_exec.py").read_text(encoding="utf-8")
    old = 'cmd = [DOCKER, "run", "--rm",'
    assert text.count(old) == 1
    text = text.replace(old, old + '''
           "--network", "fc27-cloud-net",
           "-e", "FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767",
           "-e", "FS_RPG_JOB_ID=" + jid,
           "-e", "FS_RPG_EXECUTION_RECEIPT=/srv/_jobs/" + jid + ".execution.json",
           "--mount", "type=bind,src=/opt/fs-order-session/fc_shared_admin.py,dst=/srv/fc_shared_admin.py,readonly",''')
    text = text.replace('def run_once():', CLASSIFY + 'def run_once():', 1)
    old = '''    ok = (rc == 0) and (res or {}).get("ok") is not False
    if res is None:
        res = {"ok": rc == 0, "returncode": rc, "sec": sec}
'''
    new = '''    try:
        with open(os.path.join(JOBS, jid + ".execution.json"), encoding="utf-8") as stream:
            phase = json.load(stream)
        if not isinstance(phase, dict) or phase.get("job_id") != jid:
            phase = {}
    except (OSError, ValueError):
        phase = {}
    if not isinstance(res, dict) or res.get("operation_id") != jid:
        res = None
    write_state, safe_failover = execution_state(res, phase, rc)
    ok = rc == 0 and write_state == "confirmed" and res.get("ok") is not False
    if res is None:
        res = {"ok": False, "returncode": rc, "sec": sec}
    res["write_state"] = write_state
    res["write_attempts"] = phase.get("write_attempts")
    res["original_job_id"] = jid
'''
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = '    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-160:]'
    assert text.count(old) == 1
    text = text.replace(old, '''    if isinstance(res, dict):
        res["publication_status"] = (
            "cache_failed" if ok and res.get("clearcache_wanted") and res.get("clearcache_ok") is False
            else "backend_complete" if ok else "unconfirmed")

''' + old)
    old = '            "clearcache_ok": (res or {}).get("clearcache_ok") if isinstance(res, dict) else None,'
    assert text.count(old) == 1
    text = text.replace(old, old + '\n            "publication_status": (res or {}).get("publication_status"),\n            "write_state": write_state,')
    old = '''    if not ok:
        try:
            _failover_to_local'''
    assert text.count(old) == 1
    text = text.replace(old, '''    if not ok and safe_failover:
        try:
            _failover_to_local''')
    old = '    # 金币单：把容器现场读到的「采购成本现值」落 gold_state 表'
    assert text.count(old) == 1
    text = text.replace(old, '''    if not ok and not safe_failover:
        log("  写入状态 %s：保留原工单 %s 待对账，不克隆或重放价格" % (write_state, jid))
        msg_alert.alert(con, "job-reconcile-" + jid, "改价结果待核（禁止重复执行）",
                        "原工单 %s 的写入状态为 %s；请按原ID核对已写行及回执，不新建重试单。" % (jid, write_state),
                        cooldown_s=1800)

''' + old)
    ast.parse(text)
    (output / "srv_exec.py").write_bytes(text.encode("utf-8"))
    text = (baseline / "srv_run.py").read_text(encoding="utf-8")
    text = text.replace('import os\n', 'import os\nimport json\n', 1)
    text = text.replace('class SrvSession(P.Session):', PHASE + '\nclass SrvSession(P.Session):', 1)
    text = text.replace('P.Session = SrvSession', '''    def write_rows(self, rows):
        before_write()
        return super().write_rows(rows)

    def set_gold_cost(self, row_id, value):
        before_write()
        return super().set_gold_cost(row_id, value)


P.Session = SrvSession''', 1)
    text = text.replace('sys.exit(P.main())', 'sys.exit(run_job())', 1)
    ast.parse(text)
    (output / "srv_run.py").write_bytes(text.encode("utf-8"))

    text = (baseline / "index.html").read_text(encoding="utf-8")
    marker = 'const SRV_ST = '
    helper = '''function executionLabel(j){
  let q={}; try{q=JSON.parse(j.result_json||'{}')||{};}catch(e){}
  if(q.write_state==='unknown') return ['写入待核','var(--yellow)'];
  if(q.write_state==='partial') return ['部分写入待核','var(--yellow)'];
  if(q.publication_status==='cache_failed') return ['已写入·缓存未刷新','var(--yellow)'];
  return LJ_ST[j.status]||[j.status,'var(--ov0)'];
}
'''
    assert text.count(marker) == 1
    text = text.replace(marker, helper + marker, 1)
    assert text.count("LJ_ST[j.status] || [j.status,'var(--ov0)']") == 3
    text = text.replace("LJ_ST[j.status] || [j.status,'var(--ov0)']", 'executionLabel(j)')
    assert text.count("LJ_ST[j.status]||[j.status]") == 1
    text = text.replace("LJ_ST[j.status]||[j.status]", 'executionLabel(j)')
    old = "+ '<b style=\"color:'+(lr.ok?'var(--green)':'var(--red)')+'\">'+(lr.ok?'成功':'失败')+'</b>'"
    new = "+ '<b style=\"color:'+executionLabel({status:lr.ok?'done':'failed',result_json:JSON.stringify(lr)})[1]+'\">'+executionLabel({status:lr.ok?'done':'failed',result_json:JSON.stringify(lr)})[0]+'</b>'"
    assert text.count(old) == 1
    text = text.replace(old, new)
    (output / "index.html").write_bytes(text.encode("utf-8"))
    shutil.copyfile(Path(__file__).with_name("admin_cache_local.py"), output / "admin_cache_local.py")
    shutil.copyfile(Path(__file__).with_name("fc_shared_admin.py"), output / "fc_shared_admin.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.baseline, args.output)
