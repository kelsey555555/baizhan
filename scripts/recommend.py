#!/usr/bin/env python3
"""
百战推荐：查询角色缺哪些BOSS掉落的技能
用法: python3 recommend.py <BOSS名> [等级]
例: python3 recommend.py 冯度 10
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from bai_zhan_db import get_db

def get_boss_skills(boss_name):
    """获取指定BOSS掉落的所有技能"""
    conn = get_db()
    cursor = conn.cursor()
    
    results = cursor.execute("""
        SELECT skill_name, color FROM boss_drops
        WHERE boss_name LIKE ?
        ORDER BY skill_name
    """, (f"%{boss_name}%",)).fetchall()
    
    conn.close()
    return [dict(r) for r in results]

def get_characters_with_skill_level(skill_name, level):
    """获取拥有指定技能指定等级的角色"""
    conn = get_db()
    cursor = conn.cursor()
    
    results = cursor.execute("""
        SELECT c.name, c.server, s.skill_level
        FROM characters c
        JOIN skills s ON c.id = s.character_id
        WHERE s.skill_name = ? AND s.skill_level >= ?
        ORDER BY c.name
    """, (skill_name, level)).fetchall()
    
    conn.close()
    return [dict(r) for r in results]

def recommend(boss_name, min_level=10):
    """查询角色缺哪些BOSS掉落的技能"""
    # 获取BOSS掉落的技能
    boss_skills = get_boss_skills(boss_name)
    if not boss_skills:
        print(f"❌ 未找到BOSS [{boss_name}] 的掉落数据")
        return
    
    print(f"\n🎯 BOSS [{boss_name}] 掉落技能（共{len(boss_skills)}个）：")
    print("=" * 50)
    for s in boss_skills:
        print(f"  [{s['color']}] {s['skill_name']}")
    
    # 获取所有角色
    conn = get_db()
    cursor = conn.cursor()
    characters = cursor.execute("SELECT id, name, server FROM characters ORDER BY name").fetchall()
    conn.close()
    
    if not characters:
        print("\n❌ 数据库中没有角色数据")
        return
    
    # 对每个角色检查缺少哪些技能
    results = []
    for char in characters:
        char_id, char_name, char_server = char['id'], char['name'], char['server']
        
        # 获取该角色拥有的BOSS技能（>=指定等级）
        conn = get_db()
        cursor = conn.cursor()
        owned = cursor.execute("""
            SELECT skill_name, skill_level FROM skills
            WHERE character_id = ? AND skill_name IN (
                SELECT skill_name FROM boss_drops WHERE boss_name LIKE ?
            ) AND skill_level >= ?
        """, (char_id, f"%{boss_name}%", min_level)).fetchall()
        conn.close()
        
        owned_skills = {r['skill_name']: r['skill_level'] for r in owned}
        
        # 计算缺少的技能
        missing = []
        for bs in boss_skills:
            if bs['skill_name'] not in owned_skills:
                missing.append(bs['skill_name'])
            else:
                # 检查等级是否足够
                if owned_skills[bs['skill_name']] < min_level:
                    missing.append(f"{bs['skill_name']}(当前{owned_skills[bs['skill_name']]}级)")
        
        results.append({
            'name': char_name,
            'server': char_server,
            'owned': list(owned_skills.keys()),
            'missing': missing,
            'missing_count': len(missing)
        })
    
    # 按缺少数量排序
    results.sort(key=lambda x: x['missing_count'], reverse=True)
    
    # 输出结果
    print(f"\n📊 角色技能缺口分析（{min_level}级门槛）：")
    print("=" * 60)
    
    for r in results:
        status = "✅" if r['missing_count'] == 0 else "❌"
        print(f"\n{status} {r['name']} ({r['server']})")
        print(f"   已拥有 {len(r['owned'])}/{len(boss_skills)} 个技能")
        if r['missing']:
            print(f"   缺少技能: {', '.join(r['missing'])}")
        else:
            print(f"   缺少技能: 无")
    
    # 汇总统计
    print(f"\n{'='*60}")
    print(f"📋 汇总：")
    full = sum(1 for r in results if r['missing_count'] == 0)
    partial = sum(1 for r in results if 0 < r['missing_count'] < len(boss_skills))
    empty = sum(1 for r in results if r['missing_count'] == len(boss_skills))
    print(f"   ✅ 完全体: {full} 个角色")
    print(f"   ⚠️  部分缺: {partial} 个角色")
    print(f"   ❌ 全部缺: {empty} 个角色")
    
    # 给出推荐
    print(f"\n💡 推荐：")
    for r in results:
        if r['missing_count'] > 0:
            print(f"   {r['name']}: 优先补充 {r['missing'][0]}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 recommend.py <BOSS名> [等级]")
        print("例: python3 recommend.py 冯度 10")
        sys.exit(1)
    
    boss_name = sys.argv[1]
    level = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    recommend(boss_name, level)
