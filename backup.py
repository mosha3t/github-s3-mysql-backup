#!/usr/bin/env python3
"""
Cloud Backup Tool
Backs up MySQL databases with full schema + data dumps.
"""

import os, sys, subprocess, datetime, traceback, argparse
from pathlib import Path

REQUIRED = {"yaml":"pyyaml","pymysql":"pymysql"}

def ensure_deps():
    missing = [p for i,p in REQUIRED.items() if not _can_import(i)]
    if missing:
        print(f"Installing: {', '.join(missing)} ...")
        subprocess.check_call([sys.executable,"-m","pip","install","--quiet"]+missing)

def _can_import(name):
    try: __import__(name); return True
    except ImportError: return False

ensure_deps()

import yaml
import pymysql

SCRIPT_DIR = Path(__file__).resolve().parent

class C:
    G="\033[92m"; Y="\033[93m"; R="\033[91m"; CN="\033[96m"
    B="\033[1m"; D="\033[2m"; X="\033[0m"

def ts(): return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
def human(n):
    for u in ("B","KB","MB","GB","TB"):
        if abs(n)<1024: return f"{n:.1f} {u}"
        n/=1024
    return f"{n:.1f} PB"

def ok(m): print(f"  ✅  {C.G}{m}{C.X}")
def warn(m): print(f"  ⚠️   {C.Y}{m}{C.X}")
def err(m): print(f"  ❌  {C.R}{m}{C.X}")
def info(m): print(f"  ℹ️   {C.D}{m}{C.X}")
def section(t): print(f"\n{C.B}{C.CN}── {t} {'─'*(55-len(t))}{C.X}\n")

def backup_mysql(cfg, backup_dir):
    section("Database Backup")
    dc = cfg.get("database", {})
    if not dc or not dc.get("enabled", False):
        info("Database backup disabled."); return True

    host = dc.get("host","")
    port = dc.get("port", 3306)
    user = dc.get("username","")
    pw = dc.get("password","")
    dbs = dc.get("databases",[])

    if not host or not user or not pw:
        err("Database credentials missing."); return False

    info(f"Host: {C.B}{host}:{port}{C.X}")
    d = backup_dir/"database"; d.mkdir(parents=True,exist_ok=True)

    aok=True
    try:
        c=pymysql.connect(host=host,port=int(port),user=user,password=pw,
                          connect_timeout=15,charset="utf8mb4")
        cur=c.cursor()
        if not dbs:
            info("Discovering databases...")
            cur.execute("SHOW DATABASES")
            skip={"information_schema","performance_schema","mysql","sys"}
            dbs=[r[0] for r in cur.fetchall() if r[0] not in skip]
            info(f"Found {len(dbs)}: {', '.join(dbs)}")
        c.close()
    except Exception as e:
        err(f"Connection failed: {e}"); return False

    for db in dbs:
        info(f"Backing up: {C.B}{db}{C.X}")
        of = d/f"{db}.sql"
        try:
            cn=pymysql.connect(host=host,port=int(port),user=user,password=pw,
                               database=db,connect_timeout=15,charset="utf8mb4")
            cr=cn.cursor()
            cr.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cr.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")

            with open(of,"w",encoding="utf-8") as f:
                f.write(f"-- Cloud Backup — {db}\n-- {datetime.datetime.now().isoformat()}\n\n")
                f.write("SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n\n")

                cr.execute("SHOW FULL TABLES WHERE Table_type='BASE TABLE'")
                tables=[r[0] for r in cr.fetchall()]

                for t in tables:
                    cr.execute(f"SHOW CREATE TABLE `{t}`")
                    ddl=cr.fetchone()
                    f.write(f"DROP TABLE IF EXISTS `{t}`;\n{ddl[1]};\n\n")
                    cr.execute(f"SELECT * FROM `{t}`")
                    rows=cr.fetchall()
                    cols=[d[0] for d in cr.description]
                    cl=", ".join(f"`{c}`" for c in cols)
                    if rows:
                        for i in range(0,len(rows),500):
                            batch=rows[i:i+500]
                            f.write(f"INSERT INTO `{t}` ({cl}) VALUES\n")
                            rs=[]
                            for row in batch:
                                vs=[]
                                for v in row:
                                    if v is None: vs.append("NULL")
                                    elif isinstance(v,(int,float)): vs.append(str(v))
                                    elif isinstance(v,bytes): vs.append(f"X'{v.hex()}'")
                                    elif isinstance(v,(datetime.datetime,datetime.date)): vs.append(f"'{v}'")
                                    else:
                                        e=str(v).replace("\\","\\\\").replace("'","\\'")
                                        vs.append(f"'{e}'")
                                rs.append(f"({', '.join(vs)})")
                            f.write(",\n".join(rs)+";\n")

                f.write("\nSET FOREIGN_KEY_CHECKS=1;\n")

            cr.execute("COMMIT")
            ok(f"{db} → {of.name} ({human(of.stat().st_size)}, {len(tables)} tables)")
            cn.close()
        except Exception as e:
            err(f"Failed: {db}: {e}"); aok=False
    return aok

def main():
    print(f"\n{C.CN}{C.B}  Cloud Backup Tool{C.X}\n")

    cfg_path = SCRIPT_DIR / "config.yaml"
    if not cfg_path.exists():
        err(f"config.yaml not found at {SCRIPT_DIR}"); return 1

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    base=Path(cfg.get("backup_directory","~/Desktop/Cloud Backups")).expanduser()
    bdir=base/ts(); bdir.mkdir(parents=True,exist_ok=True)
    info(f"Backup folder: {bdir}")

    result = backup_mysql(cfg, bdir)

    if result: print(f"\n{C.G}{C.B}  Done!{C.X}\n")
    else: print(f"\n{C.Y}{C.B}  Completed with errors.{C.X}\n")
    return 0 if result else 1

if __name__=="__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: print("\nCancelled."); sys.exit(130)
    except Exception as e: print(f"\nError: {e}"); traceback.print_exc(); sys.exit(1)
