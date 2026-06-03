#!/usr/bin/env python3
"""
百战技能数据库管理脚本
用法:
  python3 bai_zhan_db.py init                    # 初始化数据库
  python3 bai_zhan_db.py add <角色名> <服务器> <精> <耐> <JSON数据>  # 添加角色技能
  python3 bai_zhan_db.py query <角色名>          # 查询角色技能
  python3 bai_zhan_db.py list                    # 列出所有角色
  python3 bai_zhan_db.py delete <角色名>          # 删除角色
  python3 bai_zhan_db.py setrole <角色名> <dps> <n>  # 设置角色标签(0/1)
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

DB_PATH = os.environ.get("BAIZHAN_DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "data", "bai_zhan.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'schema.sql')

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema = f.read()
    conn = get_db()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

def add_character(name, server, essence, stamina, skills_data):
    """
    添加角色技能数据
    skills_data: [{"skill_name": "xxx", "skill_level": 10, "attribute_type": "红破", "is_common": false}, ...]

    name: 纯角色名（不含@server），server 单独传入
    如果已存在，覆盖其所有技能（同一角色多次提交时完整替换）
    """
    import re
    # 兼容旧的 "@server" 格式: 自动剥离
    if name and '@' in name:
        m = re.match(r'^(.+?)@(.+)$', name)
        if m:
            name = m.group(1)
            # 如果 server 没传，使用 @ 后面那段
            if not server or server == '-':
                server = m.group(2)
    if not server or server == '-':
        server = ''

    conn = get_db()
    cursor = conn.cursor()

    # 查找是否已存在角色（精确匹配 name + server）
    existing = cursor.execute(
        "SELECT id FROM characters WHERE name=? AND server=?", (name, server or '')
    ).fetchone()
    
    if existing:
        char_id = existing['id']
        # 更新角色属性
        cursor.execute("""
            UPDATE characters SET essence=?, stamina=? WHERE id=?
        """, (essence, stamina, char_id))
        # 删除旧技能（关键：同一角色新提交时完整覆盖）
        cursor.execute("DELETE FROM skills WHERE character_id=?", (char_id,))
    else:
        # 插入新角色（name 不含 @server）
        cursor.execute("""
            INSERT INTO characters (name, server, essence, stamina)
            VALUES (?, ?, ?, ?)
        """, (name, server or '', essence, stamina))
        char_id = cursor.lastrowid

    # 插入新技能（带 tier）
    for skill in skills_data:
        sl = skill.get('skill_level', 0)
        cursor.execute("""
            INSERT INTO skills (character_id, skill_name, skill_level, attribute_type, is_common, tier)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            char_id,
            skill.get('skill_name', ''),
            sl,
            skill.get('attribute_type', ''),
            skill.get('is_common', False),
            max(0, sl) if sl else 0
        ))
    
    conn.commit()
    conn.close()
    print(f"✅ 角色 [{name}] 的 {len(skills_data)} 个技能已保存")

def query_character(server, name):
    """查询角色技能（按服务器+角色名精确匹配）"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 查找角色（精确匹配服务器+角色名）
    char = cursor.execute(
        "SELECT * FROM characters WHERE name=? AND server=?", (name, server)
    ).fetchone()
    
    if not char:
        print(f"❌ 未找到角色: {name}@{server}")
        return None
    
    # 查找技能
    skills = cursor.execute(
        "SELECT * FROM skills WHERE character_id=? ORDER BY skill_level DESC, skill_name",
        (char['id'],)
    ).fetchall()
    
    conn.close()
    
    return dict(char), [dict(s) for s in skills]

def list_characters():
    """列出所有角色"""
    conn = get_db()
    cursor = conn.cursor()
    chars = cursor.execute("""
        SELECT c.name, c.server, c.essence, c.stamina, COUNT(s.id) as skill_count
        FROM characters c
        LEFT JOIN skills s ON c.id = s.character_id
        GROUP BY c.id
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return [dict(c) for c in chars]

def list_all_chars():
    """列出所有角色详细信息（包含owner和标签）"""
    conn = get_db()
    cursor = conn.cursor()
    chars = cursor.execute("""
        SELECT name, server, owner, is_dps, is_n, is_CD
        FROM characters
        ORDER BY owner, name
    """).fetchall()
    conn.close()
    
    if not chars:
        print("❌ 暂无角色数据")
        return []
    
    print(f"\n{'='*75}")
    print(f"{'角色名':<18} {'服务器':<10} {'owner':<10} {'标签':<10} {'本周'}")
    print(f"{'='*75}")
    
    for c in chars:
        # 角色名处理（去掉重复的服务器后缀）
        name = c['name']
        server = c['server']
        if name.endswith(f'@{server}'):
            name = name.replace(f'@{server}', '')
        
        # 标签处理
        role = []
        if c['is_dps']: role.append('输出')
        if c['is_n']: role.append('奶')
        role_str = '/'.join(role) if role else '-'
        
        owner = c['owner'] or '-'
        cd_status = '已打' if c['is_CD'] == 1 else '未打'
        print(f"{name:<18} {server:<10} {owner:<10} {role_str:<10} {cd_status}")
    
    print(f"{'='*75}")
    print(f"共 {len(chars)} 个角色")
    return [dict(c) for c in chars]

def delete_character(name):
    """删除角色"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM characters WHERE name LIKE ?", (f"%{name}%",))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    if deleted > 0:
        print(f"✅ 已删除角色: {name}")
    else:
        print(f"❌ 未找到角色: {name}")

def set_role(name, owner, is_dps, is_n, is_cd=None):
    """
    设置角色标签和账号归属
    owner: 账号归属人
    is_dps: 0=非输出, 1=输出
    is_n: 0=非奶, 1=奶
    is_cd: 0=本周未打, 1=本周已打
    """
    conn = get_db()
    cursor = conn.cursor()
    
    if is_cd is not None:
        cursor.execute("""
            UPDATE characters SET owner=?, is_dps=?, is_n=?, is_CD=?
            WHERE name LIKE ?
        """, (owner, is_dps, is_n, is_cd, f"%{name}%"))
    else:
        cursor.execute("""
            UPDATE characters SET owner=?, is_dps=?, is_n=?
            WHERE name LIKE ?
        """, (owner, is_dps, is_n, f"%{name}%"))
    
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    
    role_str = []
    if is_dps: role_str.append("输出")
    if is_n: role_str.append("奶")
    if not role_str: role_str = ["无特殊标签"]
    
    if updated > 0:
        role_display = "/".join(role_str)
        cd_msg = f" 本周{'已打' if is_cd == 1 else '未打'}" if is_cd is not None else ""
        print(f"✅ 已更新角色 [{name}]: {role_display}{cd_msg}")
    else:
        print(f"❌ 未找到角色: {name}")
    return updated

def reset_all_cd():
    """将所有角色的is_CD重置为0（本周未打）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE characters SET is_CD = 0")
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"✅ 已重置 {updated} 个角色的本周CD状态为【未打】")
    return updated

def print_character_skills(server, name):
    """格式化打印角色技能"""
    result = query_character(server, name)
    if not result:
        return
    
    char, skills = result
    print(f"\n{'='*50}")
    print(f"角色: {char['name']}")
    print(f"服务器: {char['server']}")
    print(f"精力: {char['essence']} | 耐力: {char['stamina']}")
    print(f"{'='*50}")
    
    # 按等级分组
    by_level = {}
    for s in skills:
        level = s['skill_level']
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(s)
    
    for level in sorted(by_level.keys(), reverse=True):
        print(f"\n📌 {level}级技能 ({len(by_level[level])}个)")
        print("-" * 40)
        for s in by_level[level]:
            common = "⭐" if s['is_common'] else "  "
            attr = s['attribute_type'] or ''
            print(f"{common} {s['skill_name']:<15} {attr}")

def query_skill_by_char(server, name, skill_name):
    """
    查询指定角色指定技能的信息
    参数: server, name(含region如"角色名@大区"), skill_name
    """
    # 解析 name@region 格式
    if '@' in name:
        char_name, region = name.rsplit('@', 1)
    else:
        char_name = name
        region = None
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 查找角色（支持模糊匹配服务器和角色名）
    # region 可能为空，优先用 name+server 匹配
    query = "SELECT * FROM characters WHERE name LIKE ? AND server LIKE ?"
    params = [f"%{char_name}%", f"%{server}%"]
    # 如果同时传了 region 且数据库中该角色有 region，则匹配
    # 如果数据库 region 为 NULL，则 name+server 匹配即可
    if region:
        query += " AND (region LIKE ? OR region IS NULL)"
        params.append(f"%{region}%")
    
    char = cursor.execute(query, params).fetchone()
    
    if not char:
        print(f"❌ 未找到角色: {name} (服务器: {server})")
        conn.close()
        return None
    
    # 查找技能（支持模糊匹配）
    skill = cursor.execute("""
        SELECT * FROM skills 
        WHERE character_id=? AND skill_name LIKE ?
        ORDER BY skill_level DESC
    """, (char['id'], f"%{skill_name}%")).fetchone()
    
    conn.close()
    
    if not skill:
        print(f"❌ 角色 [{char['name']}] 未拥有技能 [{skill_name}]")
        return None
    
    # 格式化输出
    print(f"\n🎯 查询结果:")
    print(f"{'='*40}")
    print(f"角色: {char['name']}")
    print(f"服务器: {char['server']}")
    print(f"{'='*40}")
    print(f"技能名: {skill['skill_name']}")
    print(f"等级: {skill['skill_level']}级")
    print(f"属性: {skill['attribute_type'] or '无'}")
    print(f"常用: {'⭐ 是' if skill['is_common'] else '否'}")
    
    return dict(skill)

def query_skill_all(skill_name, level=None):
    """
    反向查询：哪些角色拥有指定技能
    参数: skill_name, level(可选，如"10级"或10)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # 解析等级
    skill_level = None
    if level:
        level_str = str(level).replace('级', '')
        try:
            skill_level = int(level_str)
        except ValueError:
            pass
    
    # 构建查询
    if skill_level:
        results = cursor.execute("""
            SELECT c.name, c.server, c.region, s.skill_name, s.skill_level, s.attribute_type, s.is_common
            FROM characters c
            JOIN skills s ON c.id = s.character_id
            WHERE s.skill_name LIKE ? AND s.skill_level = ?
            ORDER BY c.name, s.skill_level DESC
        """, (f"%{skill_name}%", skill_level)).fetchall()
    else:
        results = cursor.execute("""
            SELECT c.name, c.server, c.region, s.skill_name, s.skill_level, s.attribute_type, s.is_common
            FROM characters c
            JOIN skills s ON c.id = s.character_id
            WHERE s.skill_name LIKE ?
            ORDER BY c.name, s.skill_level DESC
        """, (f"%{skill_name}%",)).fetchall()
    
    conn.close()
    
    if not results:
        level_hint = f"{skill_level}级" if skill_level else ""
        print(f"❌ 没有角色拥有技能 [{skill_name}] {level_hint}")
        return []
    
    # 按角色分组显示
    print(f"\n🔍 查询结果: 技能 [{skill_name}] {f'{skill_level}级' if skill_level else ''}")
    print(f"{'='*50}")
    
    current_char = None
    for row in results:
        char_key = f"{row['name']}@{row['server']}"
        if char_key != current_char:
            current_char = char_key
            print(f"\n👤 {row['name']} ({row['server']})")
        
        common = "⭐" if row['is_common'] else "  "
        attr = row['attribute_type'] or ''
        print(f"   {common} {row['skill_level']}级 | {attr}")
    
    print(f"\n共 {len(set(r['name'] for r in results))} 个角色拥有此技能")
    
    return [dict(r) for r in results]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == 'init':
        init_db()
    elif cmd == 'add':
        if len(sys.argv) < 7:
            print("用法: add <角色名> <服务器> <精力> <耐力> <技能JSON>")
            sys.exit(1)
        name = sys.argv[2]
        server = sys.argv[3]
        essence = sys.argv[4]
        stamina = sys.argv[5]
        skills_data = json.loads(sys.argv[6])
        add_character(name, server, essence, stamina, skills_data)
    elif cmd == 'query':
        if len(sys.argv) < 4:
            print("用法: query <服务器> <角色名>")
            sys.exit(1)
        server = sys.argv[2]
        name = sys.argv[3]
        print_character_skills(server, name)
    elif cmd == 'list':
        chars = list_characters()
        if not chars:
            print("暂无角色数据")
        else:
            print(f"\n{'='*60}")
            print(f"{'角色名':<15} {'服务器':<10} {'精力':<10} {'耐力':<10} {'技能数'}")
            print(f"{'='*60}")
            for c in chars:
                print(f"{c['name']:<15} {c['server']:<10} {c['essence']:<10} {c['stamina']:<10} {c['skill_count']}")
            print(f"{'='*60}")
            print(f"共 {len(chars)} 个角色")
    elif cmd == 'listall':
        # 列出所有角色详细信息（包含owner和标签）
        list_all_chars()
    elif cmd == 'delete':
        if len(sys.argv) < 3:
            print("用法: delete <角色名>")
            sys.exit(1)
        delete_character(sys.argv[2])
    elif cmd == 'setrole':
        if len(sys.argv) < 6:
            print("用法: setrole <角色名> <owner> <dps> <n>")
            print("  owner: 账号归属人")
            print("  dps: 0=非输出, 1=输出")
            print("  n: 0=非奶, 1=奶")
            print("示例: setrole 一堪舆一 老宋 1 0")
            sys.exit(1)
        name = sys.argv[2]
        owner = sys.argv[3]
        is_dps = int(sys.argv[4])
        is_n = int(sys.argv[5])
        is_cd = int(sys.argv[6]) if len(sys.argv) > 6 else None
        set_role(name, owner, is_dps, is_n, is_cd)
    elif cmd == 'skill':
        # 用法: skill <服务器> <角色名@大区> <技能名>
        #    或: skill <技能名> <等级>
        if len(sys.argv) == 4:
            # skill <技能名> <等级> - 反向查询
            skill_name = sys.argv[2]
            level = sys.argv[3]
            query_skill_all(skill_name, level)
        elif len(sys.argv) >= 5:
            # skill <服务器> <角色名@大区> <技能名> - 正向查询
            server = sys.argv[2]
            name = sys.argv[3]
            skill_name = sys.argv[4]
            query_skill_by_char(server, name, skill_name)
        else:
            print("用法:")
            print("  正向查询: skill <服务器> <角色名@大区> <技能名>")
            print("  反向查询: skill <技能名> <等级>")
    elif cmd == '技能查询':
        # 用法: 技能查询 <技能名> [等级]
        # 查询哪些角色拥有该技能，支持等级过滤
        if len(sys.argv) < 3:
            print("用法: 技能查询 <技能名> [等级]")
            print("示例: 技能查询 天工机甲龙")
            print("示例: 技能查询 天工机甲龙 10级")
            sys.exit(1)
        skill_name = sys.argv[2]
        level = sys.argv[3] if len(sys.argv) >= 4 else None
        query_skill_all(skill_name, level)
    elif cmd == '刷新CD':
        # 将所有角色的is_CD重置为0
        reset_all_cd()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
