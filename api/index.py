import os, sys

# Vercel serverless: use /tmp for writable storage
os.environ["BAIZHAN_DB_PATH"] = "/tmp/bai_zhan.db"

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

# Seed database on cold start
if not os.path.exists("/tmp/bai_zhan.db"):
    from bai_zhan_db import init_db
    from import_boss_drops import import_boss_drops
    init_db()
    import_boss_drops()

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
sys.path.insert(0, WEB_DIR)
os.chdir(WEB_DIR)

from app import app

# Vercel WSGI handler
handler = app
