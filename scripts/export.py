#!/usr/bin/env python3
"""WeChat 4.2 macOS DB exporter: copy db+wal, decrypt via wxdec (sqlite3_key), verify."""
import json, os, shutil, subprocess, sys, pathlib

BASE = pathlib.Path.home()/"Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
HERE = pathlib.Path(__file__).resolve().parent
WXDEC = HERE/"wxdec"

def main():
    acct = json.load(open(HERE/"account_key.json"))
    src = BASE/acct["account"]/"db_storage"
    work = HERE/"work"/acct["account"]; out = HERE/"out"/acct["account"]
    work.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)
    dbs = sorted(p for p in src.rglob("*.db"))
    print(f"account={acct['account']} dbs={len(dbs)}")
    ok = fail = 0
    for db in dbs:
        rel = db.relative_to(src); w = work/rel; o = out/rel
        w.parent.mkdir(parents=True, exist_ok=True); o.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db, w)
        for suf in ("-wal", "-shm"):
            if db.with_name(db.name+suf).exists(): shutil.copy2(db.with_name(db.name+suf), w.with_name(w.name+suf))
        if o.exists(): o.unlink()
        r = subprocess.run([str(WXDEC), str(w), acct["key"], str(o)], capture_output=True, text=True)
        if r.returncode != 0:
            fail += 1; print(f"FAIL {rel}: {r.stdout.strip()} {r.stderr.strip()}")
        else:
            ok += 1
            n = subprocess.run(["sqlite3", str(o), "select count(*) from sqlite_master"], capture_output=True, text=True).stdout.strip()
            print(f"ok   {str(rel):36s} objects={n} ({o.stat().st_size//1024}K)")
    print(f"done ok={ok} fail={fail} -> {out}")

if __name__ == "__main__":
    main()
