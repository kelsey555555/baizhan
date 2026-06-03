# -*- coding: utf-8 -*-
"""
百战助手 - Web 可视化界面
"""
import sys
import os
import io
import json
import base64
import urllib.request, urllib.parse, ssl
from datetime import datetime# 强制 UTF-8 输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 把 scripts 目录加入 path，复用现有模块
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts')
sys.path.insert(0, SCRIPTS_DIR)

import bai_zhan_db as db
from import_boss_drops import import_boss_drops, query_boss_skills, query_skill_from_boss
import recommend as rec_mod
import team_optimizer as team_mod
import weekly_report as wr_mod

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'baizhan-assistant-secret-key'

# ========== 简易密码保护 (公网分享时启用) ==========
# 设置环境变量 BAIZHAN_PASSWORD 即启用; 留空则不要求密码
import os
APP_PASSWORD = os.environ.get("BAIZHAN_PASSWORD", "").strip()

def _is_authed():
    if not APP_PASSWORD:
        return True  # 未设密码 = 公开
    return request.cookies.get("bz_auth") == APP_PASSWORD

def _require_auth():
    from flask import Response
    return Response(
        "<!doctype html><html><head><meta charset=utf-8><title>需要密码</title>"
        "<style>body{font-family:sans-serif;background:#f5f7fa;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
        ".box{background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1);text-align:center;min-width:280px}"
        "input{width:100%;padding:8px;margin:8px 0;border:1px solid #ddd;border-radius:4px;font-size:14px}"
        "button{background:#0d6efd;color:#fff;border:none;padding:8px 24px;border-radius:4px;cursor:pointer;font-size:14px}"
        "h3{margin:0 0 16px}</style></head><body><form class=box method=post action=/login>"
        "<h3>🔒 百战助手</h3><input type=password name=pwd placeholder=请输入密码 autofocus>"
        "<br><button type=submit>进入</button></form></body></html>",
        401, {"Content-Type": "text/html; charset=utf-8"}
    )

@app.before_request
def gate():
    # 公开端点: 登录页 + 静态资源
    if request.path in ("/login", "/static/<path:filename>"):
        return None
    if request.endpoint == "static":
        return None
    if not _is_authed():
        return _require_auth()
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    if request.method == "POST":
        pwd = request.form.get("pwd", "").strip()
        if pwd == APP_PASSWORD:
            from flask import make_response
            resp = make_response(redirect(url_for("index")))
            resp.set_cookie("bz_auth", APP_PASSWORD, max_age=30*24*3600, httponly=True)
            return resp
        return _require_auth()
    return _require_auth()

@app.route("/logout")
def logout():
    from flask import make_response
    resp = make_response(redirect("/login"))
    resp.delete_cookie("bz_auth")
    return resp
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ========== 数据库辅助：config 表 ==========
def ensure_config_table():
    """确保 config 表存在"""
    conn = db.get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_config(key, default=None):
    conn = db.get_db()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row['value'])
        except Exception:
            return row['value']
    return default

def set_config(key, value):
    conn = db.get_db()
    conn.execute("""
        INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, ?)
    """, (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ========== 角色名处理 ==========
def split_char_name(full_name):
    """从 '角色名@服务器' 中分离"""
    if '@' in full_name:
        name, server = full_name.rsplit('@', 1)
        return name, server
    return full_name, ''


# ========== 路由：首页（角色列表） ==========
@app.route('/')
def index():
    ensure_config_table()
    conn = db.get_db()
    rows = conn.execute("""
        SELECT c.id, c.name, c.server, c.owner, c.essence, c.stamina,
               c.is_dps, c.is_n, c.is_CD,
               COUNT(s.id) AS skill_count
        FROM characters c
        LEFT JOIN skills s ON c.id = s.character_id
        GROUP BY c.id
        ORDER BY c.owner, c.name
    """).fetchall()
    conn.close()
    characters = []
    for r in rows:
        d = dict(r)
        # 名字列只显示名字,服务器单独列展示,不再拼接 @server
        d['display_name'] = d['name']
        characters.append(d)
    return render_template('index.html', characters=characters)


# ========== 路由：内联编辑（CD/owner/标签） ==========
@app.route('/char/<int:cid>/inline-update', methods=['POST'])
def inline_update(cid):
    data = request.get_json() or {}
    field = data.get('field')
    value = data.get('value')
    allowed = {
        'is_CD': lambda v: 1 if v in (1, '1', True, 'true', 'on') else 0,
        'is_dps': lambda v: 1 if v in (1, '1', True, 'true', 'on') else 0,
        'is_n': lambda v: 1 if v in (1, '1', True, 'true', 'on') else 0,
        'owner': lambda v: (v or '').strip(),
    }
    if field not in allowed:
        return jsonify({'ok': False, 'error': 'invalid field'}), 400
    val = allowed[field](value)
    conn = db.get_db()
    conn.execute(f"UPDATE characters SET {field}=? WHERE id=?", (val, cid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'field': field, 'value': val})


# ========== 路由：角色详情 ==========
@app.route('/char/<int:cid>')
def character_detail(cid):
    conn = db.get_db()
    char = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    if not char:
        conn.close()
        flash('角色不存在', 'error')
        return redirect(url_for('index'))
    skills = conn.execute("""
        SELECT * FROM skills WHERE character_id=?
        ORDER BY skill_level DESC, skill_name
    """, (cid,)).fetchall()
    conn.close()
    return render_template('character.html', char=dict(char), skills=[dict(s) for s in skills])


@app.route('/api/char/<int:cid>/add-skills', methods=['POST'])
def api_char_add_skills(cid):
    """为角色添加技能（OCR结果）"""
    data = request.get_json(silent=True) or {}
    skills = data.get('skills') or []
    if not skills:
        return jsonify({"ok": False, "error": "no skills"}), 400
    conn = db.get_db()
    char = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    if not char:
        conn.close()
        return jsonify({"ok": False, "error": "角色不存在"}), 404
    added = 0
    for s in skills:
        name = (s.get('name') or '').strip()
        level = int(s.get('level', 10))
        if not name:
            continue
        try:
            conn.execute("""
                INSERT OR REPLACE INTO skills (character_id, skill_name, skill_level, tier)
                VALUES (?, ?, ?, ?)
            """, (cid, name, level, level))
            added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "added": added})
@app.route('/api/char/<int:cid>/boss-skills')
def api_char_boss_skills(cid):
    """返回角色技能按BOSS分组的数据"""
    conn = db.get_db()
    char = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    if not char:
        conn.close()
        return jsonify({"ok": False, "error": "角色不存在"}), 404
    skills = conn.execute(
        "SELECT * FROM skills WHERE character_id=?",
        (cid,)
    ).fetchall()
    skills_dict = {s['skill_name']: dict(s) for s in skills}
    rows = conn.execute(
        "SELECT DISTINCT boss_name FROM boss_drops ORDER BY boss_name"
    ).fetchall()
    boss_names = [r['boss_name'] for r in rows]
    bosses = []
    for bname in boss_names:
        drops = conn.execute(
            "SELECT * FROM boss_drops WHERE boss_name=?", (bname,)
        ).fetchall()
        boss_skills = []
        for d in drops:
            sd = dict(d)
            owned = skills_dict.get(sd['skill_name'])
            if owned:
                sd['collected'] = True
                sd['char_level'] = owned['skill_level']
                sd['char_tier'] = owned.get('tier', owned['skill_level'])
                sd['unlearnable'] = owned.get('unlearnable', 0)
            else:
                sd['collected'] = False
                sd['char_level'] = 0
                sd['unlearnable'] = 0
            boss_skills.append(sd)
        collected = sum(1 for s in boss_skills if s.get('collected'))
        bosses.append({
            "boss_name": bname,
            "skills": boss_skills,
            "total_skills": len(boss_skills),
            "collected_count": collected
        })
    conn.close()
    return jsonify({"ok": True, "char": dict(char), "bosses": bosses})


# ========== 路由：添加角色表单 ==========
def _get_boss_data():
    """Query boss_drops and return grouped boss data for templates"""
    import bai_zhan_db as db
    conn = db.get_db()
    rows = conn.execute("SELECT skill_name, boss_name, color FROM boss_drops WHERE skill_name IS NOT NULL AND skill_name != '' ORDER BY boss_name, skill_name").fetchall()
    conn.close()
    boss_map = {}
    for r in rows:
        bn = r["boss_name"]
        if bn not in boss_map:
            boss_map[bn] = []
        boss_map[bn].append({"name": r["skill_name"], "color": (r["color"] if r["color"] is not None else "") or ""})
    boss_names = sorted(boss_map.keys())
    boss_data = []
    for bn in boss_names:
        boss_data.append({"name": bn, "skills": boss_map[bn]})
    return boss_data


@app.route('/char/new', methods=['GET', 'POST'])
def character_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        server = request.form.get('server', '').strip()
        essence = request.form.get('essence', '0').strip()
        stamina = request.form.get('stamina', '0').strip()
        owner = request.form.get('owner', '').strip()
        is_dps = 1 if request.form.get('is_dps') else 0
        is_n = 1 if request.form.get('is_n') else 0
        is_CD = 1 if request.form.get('is_CD') else 0
        if not name or not server:
            flash('角色名和服务器不能为空', 'error')
            return redirect(url_for('character_new'))
        # 支持两种格式: 1) textarea (旧)  2) multi-select rows (新)
        skills_data = []
        # 优先用新格式 (skill_pick / skill_level_pick 列表)
        pick_names = request.form.getlist('skill_name')
        pick_tiers = request.form.getlist('skill_tier')
        pick_unlearnable = set(request.form.getlist('unlearnable'))
        for n, t in zip(pick_names, pick_tiers):
            n = n.strip()
            if not n: continue
            try:
                lvl = int(t)
                if lvl < 1 or lvl > 10: lvl = max(1, min(10, lvl))
            except (ValueError, TypeError):
                lvl = 10
            skills_data.append({
                "skill_name": n,
                "skill_level": lvl,
                "attribute_type": "",
                "is_common": False,
                "unlearnable": 1 if n in pick_unlearnable else 0,
            })
        # 如果没有新格式数据，回退到 textarea
        if not skills_data:
            skills_str = request.form.get('skills', '').strip()
            if skills_str:
                for line in skills_str.splitlines():
                    line = line.strip()
                    if not line or ':' not in line:
                        continue
                    s_name, s_lv = line.split(':', 1)
                    try:
                        skills_data.append({
                            "skill_name": s_name.strip(),
                            "skill_level": int(s_lv.strip()),
                            "attribute_type": "",
                            "is_common": False,
                        })
                    except ValueError:
                        pass
        db.add_character(name, server, essence, stamina, skills_data)
        db.set_role(name, owner, is_dps, is_n, is_CD)
        flash(f'已添加角色 [{name}@{server}]，录入 {len(skills_data)} 个技能', 'success')
        return redirect(url_for('index'))
    boss_data = _get_boss_data()
    return render_template('character_form.html', char=None, boss_data=boss_data, existing_skills={}, skills_text="")


# ========== 路由：编辑角色 ==========
@app.route('/char/<int:cid>/edit', methods=['GET', 'POST'])
def character_edit(cid):
    conn = db.get_db()
    char = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    if not char:
        conn.close()
        flash('角色不存在', 'error')
        return redirect(url_for('index'))
    if request.method == 'POST':
        essence = request.form.get('essence', '0').strip()
        stamina = request.form.get('stamina', '0').strip()
        owner = request.form.get('owner', '').strip()
        is_dps = 1 if request.form.get('is_dps') else 0
        is_n = 1 if request.form.get('is_n') else 0
        is_CD = 1 if request.form.get('is_CD') else 0
        skills_data = []
        pick_names = request.form.getlist('skill_name')
        pick_tiers = request.form.getlist('skill_tier')
        pick_unlearnable = set(request.form.getlist('unlearnable'))
        for n, t in zip(pick_names, pick_tiers):
            n = n.strip()
            if not n: continue
            try:
                lvl = int(t)
                if lvl < 1 or lvl > 10: lvl = max(1, min(10, lvl))
            except (ValueError, TypeError):
                lvl = 10
            skills_data.append({
                "skill_name": n,
                "skill_level": lvl,
                "attribute_type": "",
                "is_common": False,
                "unlearnable": 1 if n in pick_unlearnable else 0,
            })
        if not skills_data:
            skills_str = request.form.get('skills', '').strip()
            if skills_str:
                for line in skills_str.splitlines():
                    line = line.strip()
                    if not line or ':' not in line:
                        continue
                    s_name, s_lv = line.split(':', 1)
                    try:
                        skills_data.append({
                            "skill_name": s_name.strip(),
                            "skill_level": int(s_lv.strip()),
                            "attribute_type": "",
                            "is_common": False,
                        })
                    except ValueError:
                        pass
        conn.execute("UPDATE characters SET essence=?, stamina=? WHERE id=?", (essence, stamina, cid))
        conn.execute("DELETE FROM skills WHERE character_id=?", (cid,))
        for s in skills_data:
            sl = s['skill_level']
            conn.execute("""
                INSERT INTO skills (character_id, skill_name, skill_level, attribute_type, is_common, tier, unlearnable)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (cid, s['skill_name'], sl, s['attribute_type'], s['is_common'], max(0, sl) if sl else 0, s.get('unlearnable', 0)))
        conn.execute("UPDATE characters SET owner=?, is_dps=?, is_n=?, is_CD=? WHERE id=?",
                     (owner, is_dps, is_n, is_CD, cid))
        conn.commit()
        conn.close()
        flash('已更新', 'success')
        return redirect(url_for('character_detail', cid=cid))
    skills = conn.execute("SELECT * FROM skills WHERE character_id=? ORDER BY skill_level DESC, skill_name", (cid,)).fetchall()
    skills_text = "\n".join(f"{s['skill_name']}:{s['skill_level']}" for s in skills)
    existing_skills_dict = {}
    for s in skills:
        existing_skills_dict[s["skill_name"]] = {"tier": s["skill_level"], "unlearnable": (s["unlearnable"] if s["unlearnable"] is not None else 0)}

    boss_rows = conn.execute("""
        SELECT skill_name, boss_name, color FROM boss_drops
        WHERE skill_name IS NOT NULL AND skill_name != ''
        ORDER BY boss_name, skill_name
    """).fetchall()
    conn.close()

    boss_map = {}
    for r in boss_rows:
        bn = r['boss_name']
        if bn not in boss_map:
            boss_map[bn] = []
        boss_map[bn].append({'name': r['skill_name'], 'color': (r['color'] if r['color'] is not None else '') or ''})

    boss_names = sorted(boss_map.keys())
    boss_data = []
    for bn in boss_names:
        boss_data.append({'name': bn, 'skills': boss_map[bn]})

    return render_template('character_form.html', char=dict(char), skills_text=skills_text, existing_skills=existing_skills_dict, boss_data=boss_data)


# ========== 路由：删除角色（API 形式，前端弹窗确认） ==========
@app.route('/char/<int:cid>/delete', methods=['POST'])
def character_delete(cid):
    conn = db.get_db()
    name = conn.execute("SELECT name FROM characters WHERE id=?", (cid,)).fetchone()
    if not name:
        conn.close()
        return jsonify({'ok': False, 'error': '角色不存在'}), 404
    conn.execute("DELETE FROM skills WHERE character_id=?", (cid,))
    conn.execute("DELETE FROM characters WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted': name['name']})


# ========== 路由：BOSS 列表 ==========
@app.route('/bosses')
def bosses_list():
    """BOSS ???????????? boss_drops?"""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM boss_drops ORDER BY boss_name, skill_name"
    ).fetchall()
    conn.close()
    boss_map = {}
    for r in rows:
        sd = dict(r)
        bn = sd['boss_name']
        if bn not in boss_map:
            boss_map[bn] = {'name': bn, 'skills': [], 'boss_tier': sd.get('tier', 10)}
        boss_map[bn]['skills'].append(sd)
        if sd.get('tier'):
            boss_map[bn]['boss_tier'] = max(boss_map[bn]['boss_tier'], sd['tier'])
    bosses = list(boss_map.values())
    bosses.sort(key=lambda b: (-b['boss_tier'], b['name']))
    for b in bosses:
        b['total'] = len(b['skills'])
    return render_template('bosses.html', bosses=bosses)
@app.route('/api/bosses/stats')
def api_bosses_stats():
    """返回所有BOSS及技能列表，可选指定角色ID显示收集状态（批量查询优化版）"""
    char_id = request.args.get('char_id', type=int)
    q = request.args.get('q', '').strip()
    conn = db.get_db()
    
    # 批量查询所有掉落数据，按boss_name分组
    if q:
        all_drops = conn.execute("""
            SELECT * FROM boss_drops
            WHERE boss_name LIKE ? OR skill_name LIKE ?
            ORDER BY boss_name, skill_name
        """, (f'%{q}%', f'%{q}%')).fetchall()
    else:
        all_drops = conn.execute(
            "SELECT * FROM boss_drops ORDER BY boss_name, skill_name"
        ).fetchall()
    
    # 按boss_name分组
    boss_map = {}
    for d in all_drops:
        sd = dict(d)
        bn = sd['boss_name']
        if bn not in boss_map:
            boss_map[bn] = []
        boss_map[bn].append(sd)
    
    # 如果指定了角色，查询其技能
    char_skills = {}
    if char_id:
        skill_rows = conn.execute(
            "SELECT skill_name, skill_level, tier FROM skills WHERE character_id = ?",
            (char_id,)
        ).fetchall()
        for sr in skill_rows:
            char_skills[sr['skill_name']] = {'level': sr['skill_level'], 'tier': sr['tier']}
    
    bosses = []
    for name, skills in boss_map.items():
        for sd in skills:
            sk = sd['skill_name']
            if char_id:
                owned = char_skills.get(sk)
                if owned:
                    sd['collected'] = True
                    sd['char_level'] = owned['level']
                    sd['char_tier'] = owned['tier']
                else:
                    sd['collected'] = False
                    sd['char_level'] = 0
        
        total = len(skills)
        collected = sum(1 for s in skills if s.get('collected'))
        
        bosses.append({
            'boss_name': name,
            'skills': skills,
            'total_skills': total,
            'collected_count': collected,
        })
    
    # 查询所有角色供下拉选择
    chars = conn.execute(
        "SELECT id, name, server, owner FROM characters ORDER BY owner, name"
    ).fetchall()
    
    conn.close()
    return jsonify({
        'ok': True,
        'bosses': bosses,
        'characters': [dict(c) for c in chars],
    })
# ========== 路由：技能反向查询 ==========
@app.route('/skill-search')
def skill_search():
    q = request.args.get('q', '').strip()
    level = request.args.get('level', '').strip()
    report = ''
    if q:
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            db.query_skill_all(q, level or None)
        finally:
            sys.stdout = old_stdout
        report = buf.getvalue()
    return render_template('skill_search.html', q=q, level=level, report=report)




# ========== Sync jx3box data ==========
JX3BOX_URLS = [
    "https://www.jx3box.com/api/baizhan/skills",
    "https://www.jx3box.com/api/baizhan/bosses",
    "https://www.jx3box.com/static/baizhan/skills.json",
    "https://www.jx3box.com/static/baizhan/drops.json",
    "https://helper.jx3box.com/api/baizhan",
]

def _fetch_jx3box():
    """Try multiple jx3box endpoints, return (raw_text, url) or (None, error)"""
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    last_err = None
    for url in JX3BOX_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                data = r.read()
                if data:
                    return data.decode("utf-8", errors="replace"), url
        except Exception as e:
            last_err = f"{url}: {e}"
    return None, last_err

@app.route("/sync-jx3box", methods=["GET", "POST"])
def sync_jx3box():
    if request.method == "POST":
        action = request.form.get("action", "fetch")
        if action == "import_json":
            # Import boss_drops JSON
            raw = request.form.get("json_data", "").strip()
            if not raw:
                flash("Please paste JSON data", "error")
                return redirect(url_for("sync_jx3box"))
            try:
                data = json.loads(raw)
            except Exception as e:
                flash(f"JSON parse failed: {e}", "error")
                return redirect(url_for("sync_jx3box"))
            if isinstance(data, dict) and "boss_drops" in data:
                data = data["boss_drops"]
            if not isinstance(data, list):
                flash("Bad format", "error")
                return redirect(url_for("sync_jx3box"))
            conn = db.get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM boss_drops")
            before = cur.fetchone()[0]
            for d in data:
                if not isinstance(d, dict): continue
                sn = (d.get("skill_name") or d.get("name") or "").strip()
                bn = (d.get("boss_name") or d.get("boss") or "").strip()
                if not sn or not bn: continue
                cur.execute("""INSERT OR IGNORE INTO boss_drops (skill_name, boss_name, color, cooldown, effect)
                               VALUES (?, ?, ?, ?, ?)""",
                            (sn, bn, d.get("color","-"), d.get("cooldown","-"), d.get("effect","-")))
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM boss_drops")
            after = cur.fetchone()[0]
            try:
                with open(os.path.join(os.path.dirname(db.DB_PATH), "boss_drops.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception: pass
            conn.close()
            flash(f"Imported {after - before} new boss_drops records (total: {after})", "success")
            return redirect(url_for("bosses_list"))
        elif action == "sync_weekly":
            # Sync weekly BOSS map from jx3box
            try:
                import urllib.request, ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                url = "https://cms.jx3box.com/api/cms/app/monster/map"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                resp = json.loads(urllib.request.urlopen(req, context=ctx, timeout=15).read())
                if resp.get("code") != 0:
                    msg = resp.get("msg"); flash(f"jx3box error: {msg}", "error")
                    return redirect(url_for("sync_jx3box"))
                week = resp["data"]
                week_id = week["id"]
                week_start = week["start"]
                boss_list = week["data"]
                conn = db.get_db()
                cur = conn.cursor()
                # ensure jx3box_id column
                try:
                    cur.execute("ALTER TABLE boss_info ADD COLUMN jx3box_id INTEGER")
                    conn.commit()
                except Exception: pass
                week_num = datetime.now().strftime("%Y-W%V")
                saved = 0
                for idx, b in enumerate(boss_list, 1):
                    npc_id = b["dwBossID"]
                    level_state = b.get("nLevelState", 1)
                    # try to match existing boss by jx3box_id
                    existing = cur.execute("SELECT id, boss_name FROM boss_info WHERE jx3box_id=?", (npc_id,)).fetchone()
                    if existing:
                        # update existing
                        cur.execute("""UPDATE boss_info SET boss_number=?, is_weekly=1, week_number=?, level=?, updated_at=? WHERE id=?""",
                                    (idx, week_num, level_state, datetime.now().isoformat(), existing[0]))
                    else:
                        # create placeholder
                        boss_name = f"jx3box_{npc_id}"
                        cur.execute("""INSERT INTO boss_info
                                       (boss_name, boss_number, jx3box_id, is_weekly, week_number, level, updated_at)
                                       VALUES (?, ?, ?, 1, ?, ?, ?)""",
                                    (boss_name, idx, npc_id, week_num, level_state, datetime.now().isoformat()))
                    saved += 1
                conn.commit()
                conn.close()
                flash(f"Synced {saved} weekly BOSS entries (Week {week_id} starting {week_start}). Go to /boss-info to edit names.", "success")
                return redirect(url_for("boss_info_list"))
            except Exception as e:
                flash(f"Sync weekly failed: {e}", "error")
                return redirect(url_for("sync_jx3box"))
        else:
            raw, info = _fetch_jx3box()
            if raw:
                return render_template("sync_jx3box.html", raw=raw, source=info, ok=True)
            return render_template("sync_jx3box.html", raw=None, source=info, ok=False)
    return render_template("sync_jx3box.html", raw=None, source=None, ok=None)


# ========== 路由：组队推荐 ==========
@app.route('/queue')
def queue():
    """排表页: 3 车 × 3 角色, 拖拽排布"""
    return render_template('queue.html')


@app.route('/api/queue/optimize')
def api_queue_optimize():
    """返回最优组队数据 (供 /queue 智能排表按钮用)"""
    try:
        data = team_mod.optimize_teams_data()
        return jsonify({"ok": True, **data})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/queue/save', methods=['POST'])
def api_queue_save():
    """保存当前排表状态到 config"""
    ensure_config_table()
    data = request.get_json(silent=True) or {}
    if 'cars' not in data:
        return jsonify({"ok": False, "error": "缺少 cars"}), 400
    set_config('queue_state', data)
    return jsonify({"ok": True, "saved_at": datetime.now().isoformat()})


@app.route('/api/queue/load')
def api_queue_load():
    """加载保存的排表"""
    ensure_config_table()
    state = get_config('queue_state', None)
    return jsonify({"ok": True, "state": state})


@app.route('/api/queue/reset', methods=['POST'])
def api_queue_reset():
    """清除排表（重置）"""
    ensure_config_table()
    set_config('queue_state', None)
    set_config('queue_draft', None)
    return jsonify({"ok": True})


@app.route('/api/queue/draft-save', methods=['POST'])
def api_queue_draft_save():
    """自动保存排表草稿"""
    ensure_config_table()
    data = request.get_json(silent=True) or {}
    if 'cars' not in data:
        return jsonify({"ok": False, "error": "no cars"}), 400
    set_config('queue_draft', data)
    return jsonify({"ok": True, "saved_at": datetime.now().isoformat()})


@app.route('/api/queue/draft-load')
def api_queue_draft_load():
    """加载最新的排表草稿"""
    ensure_config_table()
    state = get_config('queue_draft', None)
    return jsonify({"ok": True, "state": state})


@app.route('/api/queue/mark-cd', methods=['POST'])
def api_queue_mark_cd():
    """一键标记某车上角色为已打"""
    data = request.get_json(silent=True) or {}
    ids = data.get('char_ids') or []
    cd = 1 if data.get('cd', 1) in (1, '1', True, 'true', 'on') else 0
    if not ids:
        return jsonify({"ok": False, "error": "no char_ids"}), 400
    conn = db.get_db()
    updated = 0
    for cid in ids:
        try:
            cur = conn.execute("UPDATE characters SET is_CD=? WHERE id=?", (cd, int(cid)))
            if cur.rowcount > 0:
                updated += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "updated": updated, "cd": cd})


@app.route('/loot-drops')
def loot_drops_page():
    """出货待分记录页"""
    return render_template('loot_drops.html')


@app.route('/api/loot/list')
def api_loot_list():
    """获取出货待分列表（支持筛选待分/全部）"""
    only_pending = request.args.get('pending', '0') in ('1', 'true', 'yes')
    conn = db.get_db()
    if only_pending:
        rows = conn.execute("""
            SELECT l.*, c.name AS char_name, c.server AS char_server, c.owner AS char_owner,
                   c1.name AS char1_name, c2.name AS char2_name, c3.name AS char3_name
            FROM loot_drops l
            LEFT JOIN characters c ON l.char_id = c.id
            LEFT JOIN characters c1 ON l.char1_id = c1.id
            LEFT JOIN characters c2 ON l.char2_id = c2.id
            LEFT JOIN characters c3 ON l.char3_id = c3.id
            WHERE l.distributed = 0
            ORDER BY l.obtained_at DESC, l.id DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT l.*, c.name AS char_name, c.server AS char_server, c.owner AS char_owner,
                   c1.name AS char1_name, c2.name AS char2_name, c3.name AS char3_name
            FROM loot_drops l
            LEFT JOIN characters c ON l.char_id = c.id
            LEFT JOIN characters c1 ON l.char1_id = c1.id
            LEFT JOIN characters c2 ON l.char2_id = c2.id
            LEFT JOIN characters c3 ON l.char3_id = c3.id
            ORDER BY l.distributed ASC, l.obtained_at DESC, l.id DESC
        """).fetchall()
    conn.close()
    return jsonify({"ok": True, "drops": [dict(r) for r in rows]})


@app.route('/api/loot/add', methods=['POST'])
def api_loot_add():
    """添加出货待分记录"""
    data = request.get_json(silent=True) or {}
    skill_name = (data.get('skill_name') or '').strip()
    if not skill_name:
        return jsonify({"ok": False, "error": "请输入掉落的技能"}), 400

    char_id = data.get('char_id')
    char1_id = data.get('char1_id')
    char2_id = data.get('char2_id')
    char3_id = data.get('char3_id')
    notes = (data.get('notes') or '').strip()
    conn = db.get_db()
    cur = conn.execute("""
        INSERT INTO loot_drops (boss_name, skill_name, char_id, char1_id, char2_id, char3_id, notes, obtained_at)
        VALUES ('', ?, ?, ?, ?, ?, ?, date('now', 'localtime'))
    """,
        (skill_name, char_id, char1_id, char2_id, char3_id, notes))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": new_id})


@app.route('/api/loot/<int:lid>/update', methods=['POST'])
def api_loot_update(lid):
    data = request.get_json(silent=True) or {}
    conn = db.get_db()
    fields = []
    values = []
    if 'char_id' in data: fields.append('char_id = ?'); values.append(data['char_id'])
    if 'notes' in data: fields.append('notes = ?'); values.append(data['notes'])
    if 'distributed' in data:
        fields.append('distributed = ?')
        values.append(1 if data['distributed'] in (1, '1', True, 'true') else 0)
    if not fields:
        conn.close()
        return jsonify({"ok": False, "error": "nothing to update"}), 400
    values.append(lid)
    conn.execute('UPDATE loot_drops SET ' + ', '.join(fields) + ' WHERE id = ?', values)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route('/api/loot/<int:lid>/delete', methods=['POST'])
def api_loot_delete(lid):
    conn = db.get_db()
    conn.execute('DELETE FROM loot_drops WHERE id = ?', (lid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route('/teams')
def teams():
    output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = output
    try:
        team_mod.optimize_teams()
    finally:
        sys.stdout = old_stdout
    report = output.getvalue()
    return render_template('teams.html', report=report)


# ========== 路由：周报 ==========
@app.route('/weekly')
def weekly():
    char_name = request.args.get('char', '').strip()
    output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = output
    try:
        if char_name:
            conn = db.get_db()
            row = conn.execute("SELECT name FROM characters WHERE name LIKE ? LIMIT 1", (f"%{char_name}%",)).fetchone()
            if row:
                wr_mod.analyze_character(row['name'])
            else:
                print(f"未找到角色: {char_name}")
            conn.close()
        else:
            wr_mod.analyze_all()
    finally:
        sys.stdout = old_stdout
    report = output.getvalue()
    return render_template('weekly.html', report=report, char_name=char_name)


# ========== 路由：批量设置 CD ==========
@app.route('/batch-cd', methods=['GET', 'POST'])
def batch_cd():
    if request.method == 'POST':
        ids = request.form.getlist('char_ids')
        cd = 1 if request.form.get('cd') == '1' else 0
        if not ids:
            flash('请至少选择一个角色', 'error')
            return redirect(url_for('batch_cd'))
        conn = db.get_db()
        for cid in ids:
            conn.execute("UPDATE characters SET is_CD=? WHERE id=?", (cd, int(cid)))
        conn.commit()
        conn.close()
        status = "已打" if cd == 1 else "未打"
        flash(f'已将 {len(ids)} 个角色的 CD 设为【{status}】', 'success')
        return redirect(url_for('index'))
    conn = db.get_db()
    rows = conn.execute("""
        SELECT id, name, server, owner, is_dps, is_n, is_CD
        FROM characters ORDER BY owner, name
    """).fetchall()
    conn.close()
    return render_template('batch_cd.html', characters=[dict(r) for r in rows])


# ========== 路由：刷新 CD（全部） ==========
@app.route('/reset-cd', methods=['POST'])
def reset_cd():
    db.reset_all_cd()
    flash('已刷新所有角色的本周 CD 状态为【未打】', 'success')
    return redirect(url_for('index'))


# ========== 路由：导入本周 BOSS ==========
@app.route('/weekly-bosses', methods=['GET', 'POST'])
def weekly_bosses():
    """本周 BOSS 管理: 支持 9/10 阶区分, BOSS 从下拉选, 同一 BOSS 可同时出现在两阶
    保存为 [{name, tier}, ...]"""
    ensure_config_table()
    current = get_config("weekly_bosses", None)

    # 收集所有可选 BOSS (仅来自 boss_drops.boss_name, 按用户要求)
    boss_options = []
    try:
        for r in db.get_db().execute("SELECT DISTINCT boss_name FROM boss_drops WHERE boss_name IS NOT NULL AND boss_name != '' AND boss_name NOT LIKE 'jx3box_%' ORDER BY boss_name"):
            if r["boss_name"]:
                boss_options.append(r["boss_name"])
    except Exception:
        pass

    bosses_with_tier = []
    if not current:
        try:
            bosses_with_tier = [{"name": n, "tier": int(t)} for n, t in wr_mod.BOSSES_81_100]
        except Exception:
            bosses_with_tier = []
    else:
        for b in current:
            if isinstance(b, dict):
                bosses_with_tier.append({"name": b.get("name", ""), "tier": int(b.get("tier", 10))})
            elif isinstance(b, str):
                bosses_with_tier.append({"name": b, "tier": 10})
    if request.method == 'POST':
        names = request.form.getlist('boss_name')
        tiers = request.form.getlist('boss_tier')
        new_list = []
        seen = set()  # 用 (name, tier) 去重, 允许同名不同阶
        for n, t in zip(names, tiers):
            n = (n or '').strip()
            if not n:
                continue
            try:
                tier = int(t)
            except (ValueError, TypeError):
                tier = 10
            if tier not in (9, 10):
                tier = 10
            key = (n, tier)
            if key in seen:
                continue
            seen.add(key)
            new_list.append({"name": n, "tier": tier})
        # 排序: 10 阶优先, 同阶内按名字
        new_list.sort(key=lambda x: (-x["tier"], x["name"]))
        set_config('weekly_bosses', new_list)
        flash(f"已保存本周 BOSS 列表 ({len(new_list)} 个: 10阶 {sum(1 for b in new_list if b['tier']==10)} / 9阶 {sum(1 for b in new_list if b['tier']==9)})", 'success')
        return redirect(url_for('weekly_bosses'))
    return render_template('weekly_bosses.html', bosses=bosses_with_tier, bosses_with_tier=bosses_with_tier, boss_options=boss_options)

@app.route("/boss-info")
def boss_info_list():
    q = request.args.get("q", "").strip()
    conn = db.get_db()
    if q:
        rows = conn.execute("SELECT * FROM boss_info WHERE boss_name LIKE ? ORDER BY boss_number", (f"%{q}%",)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM boss_info ORDER BY boss_number").fetchall()
    conn.close()
    return render_template("boss_info.html", bosses=[dict(r) for r in rows], q=q)

@app.route("/boss-info/new", methods=["GET", "POST"])
def boss_info_new():
    if request.method == "POST":
        boss_name = request.form.get("boss_name", "").strip()
        boss_number = request.form.get("boss_number", type=int)
        map_name = request.form.get("map_name", "").strip()
        map_url = request.form.get("map_url", "").strip()
        level = request.form.get("level", type=int)
        refresh_time = request.form.get("refresh_time", "").strip()
        route = request.form.get("route", "").strip()
        is_weekly = 1 if request.form.get("is_weekly") else 0
        week_number = request.form.get("week_number", "").strip()
        notes = request.form.get("notes", "").strip()
        if not boss_name:
            flash("BOSS名称不能为空", "error")
            return render_template("boss_info_form.html", boss={})
        conn = db.get_db()
        conn.execute("""INSERT INTO boss_info (boss_name,boss_number,map_name,map_url,level,refresh_time,route,is_weekly,week_number,notes,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                     (boss_name, boss_number, map_name, map_url, level, refresh_time, route, is_weekly, week_number, notes, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash("Added", "success")
        return redirect(url_for("boss_info_list"))
    return render_template("boss_info_form.html", boss={})

@app.route("/boss-info/<int:bid>/edit", methods=["GET", "POST"])
def boss_info_edit(bid):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM boss_info WHERE id=?", (bid,)).fetchone()
    if not row:
        conn.close()
        flash("Not found", "error")
        return redirect(url_for("boss_info_list"))
    if request.method == "POST":
        d = request.form
        conn.execute("""UPDATE boss_info SET boss_name=?, boss_number=?, map_name=?, map_url=?, level=?, refresh_time=?, route=?, is_weekly=?, week_number=?, notes=?, updated_at=? WHERE id=?""",
                     (d["boss_name"], d.get("boss_number", type=int), d["map_name"], d["map_url"],
                      d.get("level", type=int), d["refresh_time"], d["route"],
                      1 if d.get("is_weekly") else 0, d["week_number"], d.get("notes", ""),
                      datetime.now().isoformat(), bid))
        conn.commit()
        conn.close()
        flash("Updated", "success")
        return redirect(url_for("boss_info_list"))
    conn.close()
    return render_template("boss_info_form.html", boss=dict(row))
@app.route("/boss-info/<int:bid>/delete", methods=["POST"])
def boss_info_delete(bid):
    conn = db.get_db()
    conn.execute("DELETE FROM boss_info WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/boss-info/batch", methods=["GET", "POST"])
def boss_info_batch():
    if request.method == "POST":
        raw = request.form.get("data", "").strip()
        if not raw:
            flash("No data", "error")
            return redirect(url_for("boss_info_batch"))
        rows = []
        if raw.startswith("["):
            try: rows = json.loads(raw)
            except Exception as e:
                flash(f"JSON parse failed: {e}", "error")
                return redirect(url_for("boss_info_batch"))
        else:
            lines = [l for l in raw.splitlines() if l.strip()]
            if lines:
                header = [h.strip() for h in lines[0].split(",")]
                for line in lines[1:]:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < len(header): parts += [""] * (len(header) - len(parts))
                    rows.append(dict(zip(header, parts)))
        conn = db.get_db()
        added = 0
        for d in rows:
            if not isinstance(d, dict): continue
            bn = (d.get("boss_name") or d.get("name") or "").strip()
            if not bn: continue
            try:
                conn.execute("""INSERT OR REPLACE INTO boss_info (boss_name, boss_number, map_name, level, route, is_weekly, week_number, notes, jx3box_id, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (bn,
                             int(d.get("boss_number") or d.get("number") or 0) or None,
                             d.get("map_name") or d.get("map") or "",
                             int(d.get("level") or 0) or None,
                             d.get("route") or "",
                             1 if d.get("is_weekly") in (1, "1", "true", True) else 0,
                             d.get("week_number") or "",
                             d.get("notes") or "",
                             int(d.get("jx3box_id") or 0) or None,
                             datetime.now().isoformat()))
                added += 1
            except: pass
        conn.commit()
        conn.close()
        flash(f"Imported {added} boss info records", "success")
        return redirect(url_for("boss_info_list"))
    return render_template("boss_info_batch.html")

@app.route("/skill-info")
def skill_info_list():
    q = request.args.get("q", "").strip()
    conn = db.get_db()
    if q:
        rows = conn.execute("SELECT * FROM skill_info WHERE skill_name LIKE ? OR effect LIKE ? ORDER BY skill_name", (f"%{q}%",)*2).fetchall()
    else:
        rows = conn.execute("SELECT * FROM skill_info ORDER BY skill_name").fetchall()
    conn.close()
    return render_template("skill_info.html", skills=[dict(r) for r in rows], q=q)


@app.route('/api/skills/grouped')
def api_skills_grouped():
    """返回技能按重数和BOSS分组的数据（用于角色编辑页技能库）"""
    conn = db.get_db()
    rows = conn.execute("""
        SELECT skill_name, boss_name, color, MAX(cooldown) as cooldown, MAX(effect) as effect
        FROM boss_drops
        WHERE skill_name IS NOT NULL AND skill_name != ''
        GROUP BY skill_name, boss_name
        ORDER BY boss_name, skill_name
    """).fetchall()
    # Also get boss_tier info - derive tier from skill_level range (9/10)
    # Group: tier -> boss -> skills
    tier_boss = conn.execute("""
        SELECT DISTINCT skill_name, boss_name, color FROM boss_drops
        WHERE skill_name IS NOT NULL AND skill_name != ''
        ORDER BY boss_name, skill_name
    """).fetchall()
    conn.close()
    
    grouped = {10: {}, 9: {}, 8: {}}
    skills_list = []
    for r in tier_boss:
        sd = dict(r)
        skills_list.append(sd)
        name = sd['boss_name']
        tier = 10  # default tier
        # Try to determine tier from the boss name or skill context
        if tier not in grouped:
            grouped[tier] = {}
        if name not in grouped[tier]:
            grouped[tier][name] = []
        grouped[tier][name].append({'name': sd['skill_name'], 'color': sd.get('color', '')})
    
    # Flatten into expected format: grouped -> {10: {boss: [{name, color}]}}
    return jsonify({
        'grouped': grouped,
        'skills': [{'name': s['skill_name'], 'color': s.get('color', '')} for s in skills_list]
    })
@app.route("/api/skills")
def api_skills():
    """返回所有已知的技能名（去重）"""
    conn = db.get_db()
    rows = conn.execute("SELECT DISTINCT skill_name, color FROM boss_drops WHERE skill_name IS NOT NULL AND skill_name != '' ORDER BY skill_name").fetchall()
    conn.close()
    return jsonify([{"name": r["skill_name"], "color": r["color"]} for r in rows])

@app.route("/api/skills/search")
def api_skills_search():
    """模糊搜索技能名"""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    conn = db.get_db()
    rows = conn.execute(
        "SELECT DISTINCT skill_name, color FROM boss_drops WHERE skill_name LIKE ? ORDER BY skill_name LIMIT 20",
        (f"%{q}%",)
    ).fetchall()
    conn.close()
    return jsonify([{"name": r["skill_name"], "color": r["color"]} for r in rows])


def _ensure_extra_tables():
    try:
        db.get_db().execute("ALTER TABLE skills ADD COLUMN unlearnable INTEGER DEFAULT 0")
        db.get_db().commit()
    except Exception:
        pass
    conn = db.get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS boss_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            boss_name TEXT UNIQUE NOT NULL,
            boss_number INTEGER,
            map_name TEXT,
            map_url TEXT,
            level INTEGER,
            refresh_time TEXT,
            route TEXT,
            is_weekly INTEGER DEFAULT 0,
            week_number TEXT,
            notes TEXT,
            jx3box_id INTEGER,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS skill_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT UNIQUE NOT NULL,
            color TEXT,
            cooldown TEXT,
            effect TEXT,
            category TEXT,
            is_common INTEGER DEFAULT 0,
            notes TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS loot_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            car_number INTEGER,
            boss_name TEXT NOT NULL,
            boss_tier INTEGER,
            skill_name TEXT NOT NULL,
            skill_tier INTEGER,
            char_id INTEGER,
            obtained_at TEXT DEFAULT (date('now', 'localtime')),
            distributed INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (char_id) REFERENCES characters(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_loot_dist ON loot_drops(distributed);
        CREATE INDEX IF NOT EXISTS idx_loot_boss ON loot_drops(boss_name);
        CREATE INDEX IF NOT EXISTS idx_loot_char ON loot_drops(char_id);
    ''')
    conn.commit()
    conn.close()


if __name__ == '__main__':
    _ensure_extra_tables()
    ensure_config_table()

    import socket
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f'\n  本机访问:  http://127.0.0.1:5000\n  局域网:    http://{local_ip}:5000 (需防火墙放行)\n  公网:      用 frp/ngrok/cpolar 等内网穿透\n', flush=True)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)







