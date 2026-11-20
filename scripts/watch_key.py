#!/usr/bin/env python3
"""Wait until a captured key decrypts the target account's session.db."""
import re, subprocess, sys, time, pathlib, shutil
HOME = pathlib.Path.home()
BIG = HOME/"Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_example_0001"
LOG = pathlib.Path("/tmp/wxhook_run.log")
HERE = pathlib.Path(__file__).resolve().parent
tmp = pathlib.Path("/tmp/keyprobe"); tmp.mkdir(exist_ok=True)
src = BIG/"db_storage/session/session.db"
last = set()
deadline = time.time()+1500
while time.time() < deadline:
    txt = LOG.read_text(errors="replace") if LOG.exists() else ""
    for m in re.finditer(r"rounds=256000.*?\n  pw=([0-9a-f]{64})\n  salt=([0-9a-f]{32})", txt):
        pw, salt = m.group(1), m.group(2)
        if pw in last: continue
        last.add(pw)
        if not src.exists(): continue
        shutil.copy2(src, tmp/"probe.db")
        for suf in ("-wal","-shm"):
            p = src.with_name(src.name+suf)
            if p.exists(): shutil.copy2(p, tmp/("probe.db"+suf))
        out = tmp/"probe_plain.db"
        if out.exists(): out.unlink()
        r = subprocess.run([str(HERE/"wxdec"), str(tmp/"probe.db"), pw, str(out)], capture_output=True, text=True)
        mark = "MATCH" if r.returncode == 0 else "no"
        print(f"[{time.strftime('%H:%M:%S')}] {mark} key={pw} salt={salt}", flush=True)
        if r.returncode == 0:
            print(f"@@BIGKEY {pw}", flush=True)
            sys.exit(0)
    time.sleep(4)
print("timeout, no matching key captured")
sys.exit(3)
