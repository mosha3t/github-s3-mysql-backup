#!/usr/bin/env python3
"""
Cloud Backup Tool
Self-contained backup for MySQL, SQL Server, Amazon S3, and GitHub repos.
Encrypted config stored securely in ~/.cloud-backup/
"""

import os, sys, shutil, subprocess, datetime, traceback, argparse
import json, hashlib, base64, getpass
from pathlib import Path

REQUIRED = {
    "yaml": "pyyaml",
    "pymysql": "pymysql",
    "pymssql": "pymssql",
    "boto3": "boto3",
    "requests": "requests",
    "cryptography": "cryptography"
}

def ensure_deps():
    missing = [p for i,p in REQUIRED.items() if not _can_import(i)]
    if missing:
        print(f"📦 Installing: {', '.join(missing)} ...")
        subprocess.check_call([sys.executable,"-m","pip","install","--quiet"]+missing)
        print("   ✅ Done.\n")

def _can_import(name):
    try: __import__(name); return True
    except ImportError: return False

ensure_deps()

import yaml
import pymysql
import pymssql
import boto3
import requests
from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path.home() / ".cloud-backup"
CONFIG_ENC = DATA_DIR / ".config.enc"

SCRIPT_DIR = Path(__file__).resolve().parent
if SCRIPT_DIR.name == "Resources" and SCRIPT_DIR.parent.name == "Contents":
    APP_DIR = SCRIPT_DIR.parent.parent.parent
else:
    APP_DIR = SCRIPT_DIR
IMPORT_CONFIG = APP_DIR / "config.yaml"

# ---------------------------------------------------------------------------
# Colors & Console Output
# ---------------------------------------------------------------------------
class C:
    G="\033[92m"; Y="\033[93m"; R="\033[91m"; CN="\033[96m"
    B="\033[1m"; D="\033[2m"; X="\033[0m"

def banner():
    print(f"""
{C.CN}{C.B}╔══════════════════════════════════════════════════════════════╗
║                  CLOUD BACKUP TOOL                           ║
╚══════════════════════════════════════════════════════════════╝{C.X}
""")

def ts(): return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
def human(n):
    for u in ("B","KB","MB","GB","TB"):
        if abs(n)<1024: return f"{n:.1f} {u}"
        n/=1024
    return f"{n:.1f} PB"

def dsize(p):
    t=0
    for f in p.rglob("*"):
        if f.is_file(): t+=f.stat().st_size
    return t

def status(e,m): print(f"  {e}  {m}")
def section(t): print(f"\n{C.B}{C.CN}── {t} {'─'*(55-len(t))}{C.X}\n")
def ok(m): status("✅",f"{C.G}{m}{C.X}")
def warn(m): status("⚠️ ",f"{C.Y}{m}{C.X}")
def err(m): status("❌",f"{C.R}{m}{C.X}")
def info(m): status("ℹ️ ",f"{C.D}{m}{C.X}")

# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
def _key(pw, salt):
    return base64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256",pw.encode(),salt,100000))

def encrypt_and_store(cfg_text: bytes, password: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    salt = os.urandom(16)
    f = Fernet(_key(password, salt))
    enc = f.encrypt(cfg_text)
    payload = base64.b64encode(salt).decode() + ":" + enc.decode()
    CONFIG_ENC.write_text(payload)

def decrypt_config(password: str) -> dict:
    payload = CONFIG_ENC.read_text()
    salt_b64, enc = payload.split(":", 1)
    salt = base64.b64decode(salt_b64)
    f = Fernet(_key(password, salt))
    decrypted = f.decrypt(enc.encode())
    return yaml.safe_load(decrypted.decode())

# ---------------------------------------------------------------------------
# Config Loading with Password Flow
# ---------------------------------------------------------------------------
def load_config_with_password() -> dict:
    if CONFIG_ENC.exists():
        print(f"  {C.B}🔒 Config is encrypted.{C.X}")
        for attempt in range(3):
            pw = getpass.getpass("  Enter your backup password: ")
            try:
                cfg = decrypt_config(pw)
                ok("Config unlocked.")
                return cfg
            except (InvalidToken, Exception):
                if attempt < 2:
                    err("Wrong password. Try again.")
                else:
                    err("3 wrong attempts. Exiting.")
                    sys.exit(1)

    if IMPORT_CONFIG.exists():
        print(f"  {C.B}📋 First-time setup{C.X}")
        print(f"  Found config.yaml — will encrypt and secure it.\n")

        pw = getpass.getpass("  🔑 Set a password: ")
        pw2 = getpass.getpass("  🔑 Confirm password: ")
        if pw != pw2:
            err("Passwords don't match. Run the app again.")
            sys.exit(1)

        cfg_bytes = IMPORT_CONFIG.read_bytes()
        cfg = yaml.safe_load(cfg_bytes.decode())

        encrypt_and_store(cfg_bytes, pw)
        IMPORT_CONFIG.unlink()

        print()
        ok("Config encrypted and stored securely.")
        ok(f"Location: {CONFIG_ENC}")
        ok("config.yaml has been deleted.")
        info("You'll need this password every time you run a backup.\n")
        return cfg

    err("No configuration found!")
    err(f"Please place config.yaml next to 'Cloud Backup.app' and run again.")
    err(f"Expected location: {IMPORT_CONFIG}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Backup Services
# ---------------------------------------------------------------------------
def backup_database(cfg, backup_dir):
    section("Database Backup")
    dc = cfg.get("database", {})
    if not dc or not dc.get("enabled", False):
        info("Database backup disabled."); return True

    tp = dc.get("type", "mysql").lower().strip()
    host = dc.get("host","")
    port = dc.get("port", 3306 if tp=="mysql" else 1433)
    user = dc.get("username","")
    pw = dc.get("password","")
    dbs = dc.get("databases",[])

    if not host or not user or not pw:
        err("Database credentials missing."); return False

    info(f"Type: {C.B}{tp.upper()}{C.X}  Host: {C.B}{host}:{port}{C.X}")
    d = backup_dir/"database"; d.mkdir(parents=True,exist_ok=True)

    if tp == "mysql":
        return _mysql(host, port, user, pw, dbs, d)
    else:
        return _mssql(host, port, user, pw, dbs, d)

def _mysql(host, port, user, pw, dbs, out_dir):
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
        of = out_dir/f"{db}.sql"
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

def _mssql(host, port, user, pw, dbs, out_dir):
    if not dbs:
        warn("No databases listed for SQL Server."); return True
    aok=True
    for db in dbs:
        info(f"Backing up: {C.B}{db}{C.X}")
        of=out_dir/f"{db}.sql"
        try:
            cn=pymssql.connect(server=host,port=str(port),user=user,password=pw,database=db)
            cr=cn.cursor()
            cr.execute("SELECT TABLE_SCHEMA,TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY 1,2")
            tables=cr.fetchall()
            with open(of,"w",encoding="utf-8") as f:
                f.write(f"-- Cloud Backup — SQL Server — {db}\n-- {datetime.datetime.now().isoformat()}\n\n")
                for s,t in tables:
                    fn=f"[{s}].[{t}]"
                    cr.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",(s,t))
                    cols=[r[0] for r in cr.fetchall()]
                    cl=", ".join(f"[{c}]" for c in cols)
                    f.write(f"\n-- {fn}\n")
                    cr.execute(f"SELECT * FROM {fn}")
                    for row in cr.fetchall():
                        vs=[]
                        for v in row:
                            if v is None: vs.append("NULL")
                            elif isinstance(v,(int,float)): vs.append(str(v))
                            elif isinstance(v,bytes): vs.append(f"0x{v.hex()}")
                            elif isinstance(v,datetime.datetime): vs.append(f"'{v.isoformat()}'")
                            else: vs.append(f"'{str(v).replace(chr(39),chr(39)+chr(39))}'")
                        f.write(f"INSERT INTO {fn} ({cl}) VALUES ({', '.join(vs)});\n")
            ok(f"{db} → {of.name} ({human(of.stat().st_size)})")
            cn.close()
        except Exception as e:
            err(f"Failed: {db}: {e}"); aok=False
    return aok

def backup_s3(cfg, backup_dir):
    section("Amazon S3 Backup")
    sc=cfg.get("s3",{})
    if not sc or not sc.get("enabled",False):
        info("S3 disabled. Skipping."); return True

    ak,sk=sc.get("aws_access_key_id",""),sc.get("aws_secret_access_key","")
    rg=sc.get("region","us-east-1"); bkts=sc.get("buckets",[])
    if not ak or not sk:
        err("AWS keys missing."); return False
    if not bkts:
        warn("No buckets listed."); return True

    sd=backup_dir/"s3"; sd.mkdir(parents=True,exist_ok=True)
    s3=boto3.Session(aws_access_key_id=ak,aws_secret_access_key=sk,region_name=rg).client("s3")

    aok=True
    for bk in bkts:
        info(f"Syncing: {C.B}{bk}{C.X}")
        bd=sd/bk; bd.mkdir(parents=True,exist_ok=True)
        try:
            pg=s3.get_paginator("list_objects_v2"); fc=0; tb=0
            for page in pg.paginate(Bucket=bk):
                for obj in page.get("Contents",[]):
                    k,sz=obj["Key"],obj["Size"]
                    if k.endswith("/") and sz==0: continue
                    lp=bd/k; lp.parent.mkdir(parents=True,exist_ok=True)
                    if lp.exists() and lp.stat().st_size==sz: continue
                    s3.download_file(bk,k,str(lp)); fc+=1; tb+=sz
                    if fc%50==0: info(f"  {fc} files ({human(tb)})")
            ok(f"{bk} → {fc} new/updated files (total: {human(dsize(bd))})")
        except Exception as e:
            err(f"Failed: {bk}: {e}"); aok=False
    return aok

def backup_github(cfg, backup_dir):
    section("GitHub Repos Backup")
    gc=cfg.get("github",{})
    if not gc or not gc.get("enabled",False):
        info("GitHub disabled. Skipping."); return True

    tok=gc.get("personal_access_token",""); org=gc.get("organization","")
    if not tok:
        err("GitHub token missing."); return False
    if not org:
        err("GitHub org/user missing."); return False
    if not shutil.which("git"):
        err("git not installed."); return False

    gd=backup_dir/"github"/org; gd.mkdir(parents=True,exist_ok=True)
    hd={"Authorization":f"token {tok}","Accept":"application/vnd.github.v3+json"}

    repos=[]; pg=1
    url=f"https://api.github.com/orgs/{org}/repos"
    test=requests.get(url,headers=hd,params={"per_page":1})
    if test.status_code!=404:
        info(f"'{org}' is an organization.")
    else:
        me=requests.get("https://api.github.com/user",headers=hd)
        if me.status_code==200 and me.json().get("login","").lower()==org.lower():
            url=f"https://api.github.com/user/repos"
            info(f"'{org}' is your own account (includes private repos).")
        else:
            url=f"https://api.github.com/users/{org}/repos"
            info(f"'{org}' is a user account.")

    while True:
        params={"per_page":100,"page":pg}
        if "/user/repos" in url:
            params["affiliation"]="owner"
        else:
            params["type"]="all"
        r=requests.get(url,headers=hd,params=params)
        if r.status_code!=200:
            err(f"GitHub API: {r.json().get('message',r.text)}"); return False
        rp=r.json()
        if not rp: break
        repos.extend(rp); pg+=1

    if not repos:
        warn(f"No repos for '{org}'."); return True
    if not gc.get("include_private",True):
        repos=[r for r in repos if not r.get("private",False)]

    info(f"Found {len(repos)} repo(s).")
    aok=True; cloned=0; updated=0

    for repo in repos:
        nm=repo["name"]
        au=repo["clone_url"].replace("https://",f"https://{tok}@")
        rd=gd/nm
        try:
            if rd.exists() and (rd/".git").exists():
                info(f"Updating: {nm}")
                subprocess.run(["git","-C",str(rd),"remote","set-url","origin",au], capture_output=True,text=True,timeout=30)
                subprocess.run(["git","-C",str(rd),"fetch","--all","--prune"], capture_output=True,text=True,timeout=120)
                subprocess.run(["git","-C",str(rd),"pull","--ff-only"], capture_output=True,text=True,timeout=60)
                updated+=1
            else:
                info(f"Cloning: {nm}...")
                if rd.exists(): shutil.rmtree(rd)
                r=subprocess.run(["git","clone",au,str(rd)], capture_output=True,text=True,timeout=300)
                if r.returncode!=0:
                    err(f"Failed: {nm}: {r.stderr.strip()[:100]}"); aok=False; continue
                cloned+=1

            br=subprocess.run(["git","-C",str(rd),"branch","-r"], capture_output=True,text=True,timeout=10)
            branches=[]
            for line in br.stdout.strip().split("\n"):
                b=line.strip()
                if not b or "HEAD" in b: continue
                local=b.replace("origin/","")
                branches.append(local)
                subprocess.run(["git","-C",str(rd),"branch","--track",local,b], capture_output=True,text=True,timeout=10)

            info(f"  {nm}: {len(branches)} branch(es) — {', '.join(branches[:5])}{'...' if len(branches)>5 else ''}")

        except subprocess.TimeoutExpired:
            err(f"Timeout: {nm}"); aok=False
        except Exception as e:
            err(f"{nm}: {e}"); aok=False

    ok(f"GitHub: {cloned} cloned, {updated} updated ({len(repos)} total)")
    return aok

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
SVCMAP = {"db": "Database", "s3": "Amazon S3", "github": "GitHub"}

def main():
    banner()

    # Load config (handles password prompt internally)
    cfg = load_config_with_password()
    print()

    # Service selection
    parser = argparse.ArgumentParser(description="Cloud Backup Tool")
    parser.add_argument("--only", nargs="+", choices=["db", "s3", "github"], metavar="SVC")
    args = parser.parse_args()

    if args.only:
        sel = args.only
    elif sys.stdin.isatty():
        print(f"  {C.B}What would you like to back up?{C.X}\n")
        print(f"    {C.CN}1{C.X})  Everything")
        print(f"    {C.CN}2{C.X})  Database only")
        print(f"    {C.CN}3{C.X})  Amazon S3 only")
        print(f"    {C.CN}4{C.X})  GitHub repos only")
        print(f"    {C.CN}5{C.X})  Pick multiple (e.g. 2,3)\n")
        ch = input("  Choice [1]: ").strip() or "1"
        mm = {"1": None, "2": ["db"], "3": ["s3"], "4": ["github"]}
        if ch in mm:
            sel = mm[ch]
        else:
            nk = {"2": "db", "3": "s3", "4": "github"}
            sel = [nk[p.strip()] for p in ch.split(",") if p.strip() in nk] or None
        print()
    else:
        sel = None

    rdb = rs3 = rgh = True
    if sel:
        rdb = "db" in sel
        rs3 = "s3" in sel
        rgh = "github" in sel
        info(f"Selected: {', '.join(SVCMAP[k] for k in sel)}")
    else:
        info("Running all enabled services.")

    base = Path(cfg.get("backup_directory", "~/Desktop/Cloud Backups")).expanduser()
    bdir = base / ts()
    bdir.mkdir(parents=True, exist_ok=True)

    print(f"  📂  Folder: {C.B}{bdir}{C.X}")
    print(f"  🕐  Started: {C.B}{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.X}")

    res = {}
    if rdb:
        res["Database"] = backup_database(cfg, bdir)
    if rs3:
        res["Amazon S3"] = backup_s3(cfg, bdir)
    if rgh:
        res["GitHub"] = backup_github(cfg, bdir)

    # Summary
    section("Summary")
    tsz = human(dsize(bdir))
    print(f"  📦  Size: {C.B}{tsz}{C.X}")
    print(f"  📂  Location: {bdir}\n")

    ap = True
    for s, v in res.items():
        if v:
            ok(f"{s}: OK")
        else:
            err(f"{s}: FAILED")
            ap = False

    ln = base / "latest"
    if ln.is_symlink() or ln.exists():
        ln.unlink()
    ln.symlink_to(bdir)

    if ap:
        print(f"\n{C.G}{C.B}  🎉  All backups completed!{C.X}\n")
    else:
        print(f"\n{C.Y}{C.B}  ⚠️   Some errors. Check above.{C.X}\n")

    (bdir / "backup_log.txt").write_text(
        f"Cloud Backup — {datetime.datetime.now().isoformat()}\n" +
        "".join(f"  {s}: {'OK' if v else 'FAIL'}\n" for s, v in res.items()) +
        f"Size: {tsz}\n"
    )

    return 0 if ap else 1

if __name__=="__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: print(f"\n{C.Y}Cancelled.{C.X}"); sys.exit(130)
    except Exception as e: print(f"\n{C.R}Error: {e}{C.X}"); traceback.print_exc(); sys.exit(1)
