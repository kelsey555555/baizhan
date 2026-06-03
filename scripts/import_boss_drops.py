#!/usr/bin/env python3
"""导入BOSS掉落数据"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(__file__))
from bai_zhan_db import get_db

BOSS_DROPS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'boss_drops.json')

def import_boss_drops():
    with open(BOSS_DROPS_PATH, 'r', encoding='utf-8') as f:
        boss_drops = json.load(f)
    
    conn = get_db()
    cursor = conn.cursor()
    
    imported = 0
    for drop in boss_drops:
        cursor.execute("""
            INSERT OR IGNORE INTO boss_drops (skill_name, boss_name, color, cooldown, effect)
            VALUES (?, ?, ?, ?, ?)
        """, (
            drop['skill_name'],
            drop['boss_name'],
            drop['color'],
            drop['cooldown'],
            drop['effect']
        ))
        if cursor.rowcount > 0:
            imported += 1
    
    conn.commit()
    conn.close()
    print(f"✅ 已导入 {imported} 条BOSS掉落数据")

def query_skill_from_boss(skill_name):
    """查询技能由哪个BOSS掉落"""
    conn = get_db()
    cursor = conn.cursor()
    
    results = cursor.execute("""
        SELECT * FROM boss_drops WHERE skill_name LIKE ?
        ORDER BY skill_name
    """, (f"%{skill_name}%",)).fetchall()
    
    conn.close()
    
    if not results:
        print(f"❌ 未找到技能 [{skill_name}] 的掉落信息")
        return []
    
    print(f"\n🔍 技能 [{skill_name}] 的BOSS掉落来源：")
    print(f"{'='*50}")
    for row in results:
        print(f"  BOSS: {row['boss_name']}")
        print(f"  颜色: {row['color']}")
        print(f"  调息: {row['cooldown']}")
        print(f"  效果: {row['effect']}")
        print(f"{'-'*50}")
    
    return [dict(r) for r in results]

def query_boss_skills(boss_name):
    """查询某BOSS掉落的所有技能"""
    conn = get_db()
    cursor = conn.cursor()
    
    results = cursor.execute("""
        SELECT * FROM boss_drops WHERE boss_name LIKE ?
        ORDER BY skill_name
    """, (f"%{boss_name}%",)).fetchall()
    
    conn.close()
    
    if not results:
        print(f"❌ 未找到BOSS [{boss_name}] 的掉落技能")
        return []
    
    print(f"\n🎯 BOSS [{boss_name}] 掉落的技能：")
    print(f"{'='*50}")
    for row in results:
        color = row['color'] or '-'
        print(f"  [{color}] {row['skill_name']}")
    
    print(f"\n共 {len(results)} 个技能")
    return [dict(r) for r in results]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 import_boss_drops.py import  # 导入BOSS掉落数据")
        print("  python3 import_boss_drops.py skill <技能名>  # 查询技能掉落")
        print("  python3 import_boss_drops.py boss <BOSS名>  # 查询BOSS掉落技能")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == 'import':
        import_boss_drops()
    elif cmd == 'skill':
        if len(sys.argv) < 3:
            print("用法: skill <技能名>")
            sys.exit(1)
        query_skill_from_boss(sys.argv[2])
    elif cmd == 'boss':
        if len(sys.argv) < 3:
            print("用法: boss <BOSS名>")
            sys.exit(1)
        query_boss_skills(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
