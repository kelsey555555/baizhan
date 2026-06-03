#!/usr/bin/env python3
"""
百战本周BOSS分析：81-100号BOSS技能缺口分析
用法: 
  python3 weekly_report.py              # 全部分析
  python3 weekly_report.py <角色名>     # 特定角色细化方案
  python3 weekly_report.py init        # 初始化BOSS列表（从图片识别）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from bai_zhan_db import get_db

# 81-100号BOSS列表（本周）格式: (boss_name, tier)
# tier 10 = 10阶 BOSS (掉落10级和9级技能)
# tier 9  = 9阶 BOSS  (只掉落9级技能)
BOSSES_81_100 = [
    ("司徒一一", 10), ("鬼影小次郎", 10), ("秦雷", 10), ("方宇谦", 10), ("冯度", 10),
    ("源明雅", 10), ("华鹤炎", 10), ("罗翼", 10), ("程沐华·青年", 10), ("悉达罗摩", 10),
    ("阿依努尔", 10), ("方宇谦", 10), ("冯度", 10), ("上杉勇刀", 10), ("源明雅", 10),
    ("恶战日轮山城", 10), ("钱宗龙", 10), ("程沐华·青年", 10), ("韦柔丝", 10), ("谢云流·青年", 10),
    ("韦柔丝·异象", 9),
]

def get_weekly_bosses():
    """从 config 表读本周 BOSS 列表,10 阶在前。如果未配置则用默认列表。"""
    import json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key=?", ("weekly_bosses",))
        row = cur.fetchone()
        conn.close()
        bosses = []
        if row:
            try:
                data = json.loads(row["value"])
                if isinstance(data, list):
                    for d in data:
                        if isinstance(d, dict):
                            bosses.append((d.get("name", ""), int(d.get("tier", 10))))
                        elif isinstance(d, str):
                            bosses.append((d, 10))
            except Exception:
                pass
        if not bosses:
            bosses = list(BOSSES_81_100)
        bosses.sort(key=lambda x: -x[1])
        return bosses
    except Exception:
        return list(BOSSES_81_100)


def get_boss_drops(boss_name):
    """精确匹配 BOSS 名"""
    conn = get_db()
    cursor = conn.cursor()
    results = cursor.execute("""
        SELECT skill_name, color, tier FROM boss_drops WHERE boss_name = ?
    """, (boss_name,)).fetchall()
    conn.close()
    return [dict(r) for r in results]

def get_char_skills(char_id):
    conn = get_db()
    cursor = conn.cursor()
    results = cursor.execute("""
        SELECT skill_name, skill_level, unlearnable FROM skills WHERE character_id = ?
    """, (char_id,)).fetchall()
    conn.close()
    return {r['skill_name']: r['skill_level'] for r in results if not r['unlearnable']}

def get_all_characters():
    conn = get_db()
    cursor = conn.cursor()
    characters = cursor.execute("SELECT id, name, server FROM characters ORDER BY name").fetchall()
    conn.close()
    return [(c['id'], c['name'], c['server']) for c in characters]

def analyze_all():
    """全部分析"""
    # 去重BOSS
    raw_bosses = get_weekly_bosses()
    seen = set()
    unique_bosses = []
    tier_map = {}
    for b, t in raw_bosses:
        if b not in seen:
            unique_bosses.append(b)
            tier_map[b] = t
            seen.add(b)

    # 收集所有可刷技能
    # 改为 {skill_name: (boss, tier)} 供 9 级缺口判断
    all_drops = {}
    for boss in unique_bosses:
        for d in get_boss_drops(boss):
            sk = d['skill_name']
            if sk not in all_drops:
                all_drops[sk] = (boss, d.get('tier', 10) or tier_map.get(boss, 10))

    print(f"\n📋 本周BOSS（81-100，去重{len(unique_bosses)}个）:")
    print(f"   {', '.join(unique_bosses)}\n")
    print(f"共 {len(all_drops)} 个可刷技能\n")

    characters = get_all_characters()
    results = []

    for cid, cname, cserver in characters:
        skills = get_char_skills(cid)

        miss_10 = []
        miss_9 = []
        for skill, (boss, b_tier) in all_drops.items():
            lvl = skills.get(skill, 0)
            if lvl < 10:
                miss_10.append((skill, boss, lvl))
                if lvl < 9:
                    miss_9.append((skill, boss, lvl))

        by_boss_10 = {}
        for skill, boss, lvl in miss_10:
            by_boss_10.setdefault(boss, []).append((skill, lvl))

        results.append({
            'name': cname, 'server': cserver,
            'by_boss_10': by_boss_10,
            'miss_10_total': len(miss_10),
            'miss_9_total': len(miss_9),
            'skills': skills
        })

    results.sort(key=lambda x: (x['miss_10_total'], x['miss_9_total']), reverse=True)

    for r in results:
        print(f"{'='*55}")
        print(f"👤 {r['name']} ({r['server']})")
        print(f"   缺10级: {r['miss_10_total']}个 | 缺9级(未达10级): {r['miss_9_total']}个")
        
        bosses_sorted = sorted(r['by_boss_10'].items(), key=lambda x: len(x[1]), reverse=True)
        print(f"   【10级缺口明细】（按BOSS缺失数排序）")
        for boss, items in bosses_sorted[:6]:
            skill_info = []
            for skill, lvl in items:
                lvl_str = f"({lvl}级)" if lvl > 0 else "(未获得)"
                skill_info.append(f"{skill}{lvl_str}")
            print(f"   · {boss}({len(items)}个): {', '.join(skill_info[:4])}" +
                  (f" ...等" if len(items) > 4 else ""))
        if len(bosses_sorted) > 6:
            print(f"   · ...还有{len(bosses_sorted)-6}个BOSS的技能未显示")

    # 推荐
    print(f"\n{'='*55}")
    print(f"🎯 推荐刷技能顺序（先补10级缺最多的）:")
    for i, r in enumerate(results, 1):
        top = sorted(r['by_boss_10'].items(), key=lambda x: len(x[1]), reverse=True)
        if top:
            best_boss, best_items = top[0]
            top_skills = [s for s, _ in best_items[:4]]
            print(f"   {i}. {r['name']}: 优先刷【{best_boss}】→ {', '.join(top_skills)}" +
                  (f" 等{len(best_items)}个技能" if len(best_items) > 4 else ""))

def analyze_character(char_name):
    """特定角色详细分析"""
    raw_bosses = get_weekly_bosses()
    seen = set()
    unique_bosses = []
    tier_map = {}
    for b, t in raw_bosses:
        if b not in seen:
            unique_bosses.append(b)
            tier_map[b] = t
            seen.add(b)

    # 收集所有可刷技能
    all_drops = {}
    for boss in unique_bosses:
        for d in get_boss_drops(boss):
            if d['skill_name'] not in all_drops:
                all_drops[d['skill_name']] = boss

    characters = get_all_characters()
    target = None
    for cid, cname, cserver in characters:
        if cname == char_name:
            target = (cid, cname, cserver)
            break
    
    if not target:
        print(f"❌ 未找到角色: {char_name}")
        print(f"可用角色: {', '.join([c[1] for c in characters])}")
        return

    cid, cname, cserver = target
    skills = get_char_skills(cid)

    miss_10 = []
    miss_9 = []
    for skill, (boss, b_tier) in all_drops.items():
        lvl = skills.get(skill, 0)
        if lvl < 10:
            miss_10.append((skill, boss, lvl))
            if lvl < 9:
                miss_9.append((skill, boss, lvl))

    by_boss_10 = {}
    for skill, boss, lvl in miss_10:
        by_boss_10.setdefault(boss, []).append((skill, lvl))

    print(f"\n{'='*55}")
    print(f"👤 {cname} ({cserver}) - 细化补全方案")
    print(f"{'='*55}")
    print(f"\n📊 缺口统计:")
    print(f"   缺10级: {len(miss_10)}个 | 缺9级: {len(miss_9)}个")
    
    # 按BOSS分组显示详细方案
    print(f"\n📋 10级技能补全方案（按BOSS优先级排序）:")
    bosses_sorted = sorted(by_boss_10.items(), key=lambda x: len(x[1]), reverse=True)
    
    for idx, (boss, items) in enumerate(bosses_sorted, 1):
        print(f"\n   {'─'*50}")
        print(f"   【{idx}】{boss} ({len(items)}个技能)")
        print(f"   {'─'*50}")
        for skill, curr_lvl in sorted(items, key=lambda x: x[1]):
            curr_str = f"当前{curr_lvl}级" if curr_lvl > 0 else "未获得"
            print(f"   · {skill} ({curr_str}) → 建议10级")

    print(f"\n{'='*55}")
    print(f"💡 最佳路线建议:")
    top3 = bosses_sorted[:3]
    for i, (boss, items) in enumerate(top3, 1):
        print(f"   {i}. 先刷【{boss}】的: {', '.join([s for s,_ in items[:3]])}" +
              (f" 等{len(items)}个" if len(items) > 3 else ""))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        analyze_all()
    elif sys.argv[1] in ['init', '--init']:
        print("请提供新的BOSS列表，或在命令行传入BOSS名称")
        print("用法: python3 weekly_report.py <角色名>")
    else:
        analyze_character(sys.argv[1])
