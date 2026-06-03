#!/usr/bin/env python3
"""
百战组队优化器 - 按BOSS技能缺口分组
目标: 2输出+1奶为一组，让全队缺失技能的BOSS冲突最少

用法: python3 team_optimizer.py
"""
import sys
import os
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(__file__))
from bai_zhan_db import get_db

# 默认 BOSS 列表（当 /weekly-bosses 没配置时使用）格式: (boss_name, tier)
DEFAULT_BOSSES = [
    ("司徒一一", 10), ("鬼影小次郎", 10), ("秦雷", 10), ("方宇谦", 10), ("冯度", 10),
    ("源明雅", 10), ("华鹤炎", 10), ("罗翼", 10), ("程沐华·青年", 10), ("悉达罗摩", 10),
    ("阿依努尔", 10), ("上杉勇刀", 10), ("恶战日轮山城", 10), ("钱宗龙", 10), ("谢云流·青年", 10),
    # 9阶 BOSS 变体示例
    ("韦柔丝·异象", 9),
]


def get_weekly_bosses():
    """从 config 表读本周 BOSS 列表，10 阶排在前面。如果未配置则用默认列表。"""
    import json
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
        bosses = DEFAULT_BOSSES
    # 排序：10 阶在前
    bosses.sort(key=lambda x: -x[1])
    return bosses


# 兼容旧代码引用
BOSSES_81_100 = DEFAULT_BOSSES

def get_boss_drops(boss_name):
    """精确匹配 BOSS 名（韦柔丝 ≠ 韦柔丝·异象）"""
    conn = get_db()
    cursor = conn.cursor()
    results = cursor.execute("""
        SELECT skill_name, tier FROM boss_drops WHERE boss_name = ?
    """, (boss_name,)).fetchall()
    conn.close()
    return [(r['skill_name'], r['tier']) for r in results]

def get_char_missing_skills(char_id):
    """获取角色缺失的10级和9级技能（按 BOSS 精确匹配 + tier 规则）"""
    conn = get_db()
    cursor = conn.cursor()
    owned = cursor.execute("""
        SELECT skill_name, skill_level, tier, unlearnable FROM skills WHERE character_id = ?
    """, (char_id,)).fetchall()
    owned_dict = {r['skill_name']: r['skill_level'] for r in owned}
    owned_tier = {r['skill_name']: r['tier'] for r in owned}
    unlearnable_set = {r['skill_name'] for r in owned if r['unlearnable']}
    conn.close()

    unique_bosses = list(dict.fromkeys(BOSSES_81_100))

    all_boss_skills = {}  # skill -> (boss, tier)
    for boss, tier in unique_bosses:
        for skill, s_tier in get_boss_drops(boss):
            if skill not in all_boss_skills:
                all_boss_skills[skill] = (boss, tier)

    miss_10 = []
    miss_9 = []
    for skill, (boss, boss_tier) in all_boss_skills.items():
        if skill in unlearnable_set:
            continue
        lvl = owned_dict.get(skill, 0)
        # 10级 缺口: 任何 boss 都能补
        if lvl < 10:
            miss_10.append((skill, boss, lvl, boss_tier))
        # 9级 缺口: 只算 9阶 boss 也能补的（即该 boss 是 10阶，因为 10阶掉9和10；9阶只掉9）
        if lvl < 9 and boss_tier >= 9:
            miss_9.append((skill, boss, lvl, boss_tier))

    return miss_10, miss_9

def get_all_characters():
    conn = get_db()
    cursor = conn.cursor()
    chars = cursor.execute("""
        SELECT id, name, server, is_dps, is_n, owner, is_CD
        FROM characters
    """).fetchall()
    conn.close()
    return [(c['id'], c['name'], c['server'], c['is_dps'], c['is_n'], c['owner'], c['is_CD']) for c in chars]

def calculate_team_conflict(team_char_ids, miss_10_all, miss_9_all):
    """
    计算队伍在10级技能上的冲突程度
    team_char_ids: [char_id, ...]
    返回: (冲突分数, 每个BOSS被多少角色需要)
    """
    boss_need_count = defaultdict(set)  # boss -> set of char_ids
    
    for char_id in team_char_ids:
        for skill, boss, _, _ in miss_10_all.get(char_id, []):
            boss_need_count[boss].add(char_id)
    
    # 冲突分数 = 有多人同时需要的技能总数
    conflict = 0
    for boss, chars in boss_need_count.items():
        if len(chars) > 1:
            conflict += len(chars) - 1  # 每人贡献1，多的算冲突
    
    return conflict, boss_need_count

def optimize_teams():
    # 优先使用 weekly_bosses 配置
    weekly = get_weekly_bosses()
    global BOSSES_81_100
    BOSSES_81_100 = weekly
    print(f"使用本周 BOSS 列表 ({len(weekly)} 个): 10阶 {sum(1 for _,t in weekly if t==10)} 个, 9阶 {sum(1 for _,t in weekly if t==9)} 个")
    characters = get_all_characters()
    
    if len(characters) < 3:
        print("❌ 角色数量不足，需要至少3个角色（2输出+1奶）")
        return
    
    # 分离输出和奶（只选未打CD的角色，去重，同角色不会同时为两个不同位置）
    # 格式: (char_id, name, server, owner)
    dps_list = [(c[0], c[1], c[2], c[5]) for c in characters if c[3] == 1 and c[6] == 0]
    healer_list = [(c[0], c[1], c[2], c[5]) for c in characters if c[4] == 1 and c[6] == 0]
    
    # 去重（双心法角色只出现一次）
    dps_list_unique = []
    seen_dps = set()
    for d in dps_list:
        if d[0] not in seen_dps:
            dps_list_unique.append(d)
            seen_dps.add(d[0])
    
    healer_list_unique = []
    seen_healer = set()
    for h in healer_list:
        if h[0] not in seen_healer:
            healer_list_unique.append(h)
            seen_healer.add(h[0])
    
    dps_list = dps_list_unique
    healer_list = healer_list_unique
    
    # 获取所有角色的缺失技能
    miss_10_all = {}
    miss_9_all = {}
    char_names = {}
    
    for char in characters:
        char_id, name, server, _, _, _, _ = char
        miss_10, miss_9 = get_char_missing_skills(char_id)
        miss_10_all[char_id] = miss_10
        miss_9_all[char_id] = miss_9
        char_names[char_id] = f"{name}"
    
    # 收集所有BOSS掉落技能
    # 去重 BOSS，保留 (boss, tier) 形式
    seen_b = set()
    unique_bosses = []
    for b, t in BOSSES_81_100:
        if b not in seen_b:
            seen_b.add(b)
            unique_bosses.append((b, t))
    all_drops = {}
    for boss, b_tier in unique_bosses:
        for skill, s_tier in get_boss_drops(boss):
            if skill not in all_drops:
                all_drops[skill] = (boss, b_tier)
    
    # 生成所有可能的队伍组合（2输出+1奶）
    teams = []
    for dps1_idx, dps1 in enumerate(dps_list):
        for dps2_idx in range(dps1_idx + 1, len(dps_list)):
            dps2 = dps_list[dps2_idx]
            for healer in healer_list:
                # 确保三人不同
                char_ids = [dps1[0], dps2[0], healer[0]]
                if len(set(char_ids)) != 3:
                    continue
                
                # 确保三人属于不同owner
                owners = [dps1[3], dps2[3], healer[3]]
                if len(set(owners)) != 3:
                    continue
                
                conflict, boss_need_count = calculate_team_conflict(char_ids, miss_10_all, miss_9_all)
                
                # 统计每个角色的需求
                char_needs = {}
                for char_id in char_ids:
                    by_boss = defaultdict(list)
                    for skill, boss, lvl, b_tier in miss_10_all.get(char_id, []):
                        by_boss[boss].append((skill, lvl))
                    char_needs[char_id] = by_boss
                
                teams.append({
                    'conflict': conflict,
                    'chars': char_ids,
                    'boss_need': boss_need_count,
                    'char_needs': char_needs
                })
    
    # 按冲突分数排序（低的在前）
    teams.sort(key=lambda x: x['conflict'])
    
    if not teams:
        print("❌ 找不到符合条件的队伍（需要3个不同owner的角色）")
        print("   当前owner分布:")
        # 统计owner分布
        owner_chars = defaultdict(list)
        for c in characters:
            owner = c[5] if c[5] else '(未设置)'
            owner_chars[owner].append(c[1])
        for owner, chars in owner_chars.items():
            print(f"   {owner}: {', '.join(chars)}")
        print("\n💡 请确保至少有3个不同owner的角色，并设置好标签（输出/奶）")
        return
    
    # 使用最优方案
    best = teams[0]
    
    # 计算技能需求统计
    skill_need_count = defaultdict(int)  # skill -> 多少人需要
    for char_id in best['chars']:
        seen = set()
        for skill, boss, lvl, b_tier in miss_10_all.get(char_id, []):
            if skill not in seen:
                seen.add(skill)
                skill_need_count[skill] += 1
    
    # 按需求人数分组
    by_need1 = []  # 仅1人需要
    by_need2 = []  # 2人需要
    by_need3 = []  # 3人需要
    for skill, (boss, b_tier) in all_drops.items():
        cnt = skill_need_count.get(skill, 0)
        if cnt == 1:
            by_need1.append((skill, boss))
        elif cnt == 2:
            by_need2.append((skill, boss))
        elif cnt >= 3:
            by_need3.append((skill, boss))
    
    # 按BOSS分组
    def group_by_boss(skill_list):
        groups = defaultdict(list)
        for skill, boss in skill_list:
            groups[boss].append(skill)
        return groups

    # 优先 BOSS 表：把 10 阶 BOSS 排在前面
    def boss_priority(boss_name):
        # 查 BOSS tier
        for bn, t in BOSSES_81_100:
            if bn == boss_name:
                return -t  # 10 阶排前
        return 0
    
    # 输出结果
    print("=" * 55)
    print("📊 三人队伍技能需求分析")
    print("=" * 55)
    print(f"\n总可刷技能: {len(all_drops)} 个")
    print(f"仅1人需求: {len(by_need1)} 个 ✅")
    print(f"2人需求: {len(by_need2)} 个 ⚠️")
    print(f"3人需求: {len(by_need3)} 个")
    
    # 冲突最少的BOSS
    groups1 = group_by_boss(by_need1)
    # 先按 tier（10 阶优先），再按技能数
    sorted_bosses1 = sorted(groups1.keys(), key=lambda b: (boss_priority(b), -len(groups1[b])))

    print(f"\n{'='*55}")
    print("🎯 冲突最少的BOSS（优先刷 10 阶）")
    print("=" * 55)
    for boss in sorted_bosses1[:5]:
        skills = groups1[boss]
        tier = dict(BOSSES_81_100).get(boss, 10)
        tier_tag = "🔟10阶" if tier == 10 else "9️⃣9阶"
        print(f"\n【{boss}】{tier_tag} ({len(skills)}个技能仅1人需要)")
        for s in skills[:5]:
            print(f"   · {s}")
        if len(skills) > 5:
            print(f"   ...还有{len(skills)-5}个")
    
    # 冲突最多的BOSS
    all_conflict = by_need2 + by_need3
    groups_conflict = group_by_boss(all_conflict)
    sorted_bosses_conflict = sorted(groups_conflict.keys(), key=lambda b: (boss_priority(b), -len(groups_conflict[b])))
    
    print(f"\n{'='*55}")
    print("⚠️  冲突最多的BOSS（需协调）")
    print("=" * 55)
    for boss in sorted_bosses_conflict[:5]:
        cnt = len(groups_conflict[boss])
        who = "3人" if boss in group_by_boss(by_need3) else "2人"
        skills = groups_conflict[boss]
        print(f"\n【{boss}】({cnt}个技能{who}需要)")
        for s in skills[:5]:
            print(f"   · {s}")
        if len(skills) > 5:
            print(f"   ...还有{len(skills)-5}个")
    
    print(f"\n{'='*55}")
    print("💡 刷技能建议")
    print("=" * 55)
    print("1. 优先刷三人冲突最少的BOSS（无竞争）")
    print("2. 冲突多的BOSS轮流刷，或根据等级差距分配")
    
    # 输出最优组队
    print(f"\n{'='*55}")
    print("🎯 最优组队方案（冲突最少）")
    print("=" * 55)
    
    char_display = []
    for char_id in best['chars']:
        char = next((c for c in characters if c[0] == char_id), None)
        if char:
            owner = char[5] if char[5] else '(未设置)'
            role = []
            if char[3] == 1: role.append("输出")
            if char[4] == 1: role.append("奶")
            cd = '✅' if char[6] == 0 else '❌'
            char_display.append(f"{char[1]}({char[2]}/{owner}):{'/'.join(role)} {cd}")
    
    print(f"\n队伍: {' + '.join(char_display)}")
    print(f"冲突分数: {best['conflict']}（越低越少冲突）")
    
    # 每人详细
    for char_id in best['chars']:
        char = next((c for c in characters if c[0] == char_id), None)
        if not char:
            continue
        
        miss_10 = miss_10_all.get(char_id, [])
        miss_9 = miss_9_all.get(char_id, [])
        
        by_boss = best['char_needs'].get(char_id, {})
        boss_sorted = sorted(by_boss.items(), key=lambda x: len(x[1]), reverse=True)
        
        owner = char[5] if char[5] else '(未设置)'
        print(f"\n👤 {char[1]}({char[2]}/{owner})")
        print(f"   缺10级: {len(miss_10)}个 | 缺9级: {len(miss_9)}个")
        print(f"   优先刷: ", end="")
        if boss_sorted:
            top_boss, top_skills = boss_sorted[0]
            skills_str = ','.join([s for s, _ in top_skills[:3]])
            print(f"【{top_boss}】的 {skills_str} 等{len(top_skills)}个")
        else:
            print("无缺失")



def optimize_teams_data():
    """返回 JSON 友好的结构化数据,供 /queue 排表页使用
    返回:
      {
        "weekly": [(name, tier), ...],
        "all_chars": [{id, name, server, owner, is_dps, is_n, is_CD}, ...],
        "teams": [{chars: [id1,id2,id3], conflict, owner_diversity, by_boss_summary}, ...]
        "picked_3": [team1, team2, team3]  # 贪心挑选 3 个不冲突的车
      }
    """
    weekly = get_weekly_bosses()
    characters = get_all_characters()

    # 准备数据结构 (与 optimize_teams 一致)
    dps_list = [(c[0], c[1], c[2], c[5]) for c in characters if c[3] == 1 and c[6] == 0]
    healer_list = [(c[0], c[1], c[2], c[5]) for c in characters if c[4] == 1 and c[6] == 0]

    # 去重
    def _dedup(lst):
        seen, out = set(), []
        for x in lst:
            if x[0] not in seen:
                out.append(x); seen.add(x[0])
        return out
    dps_list = _dedup(dps_list)
    healer_list = _dedup(healer_list)

    miss_10_all, miss_9_all, char_names = {}, {}, {}
    for char in characters:
        cid, name = char[0], char[1]
        m10, m9 = get_char_missing_skills(cid)
        miss_10_all[cid] = m10
        miss_9_all[cid] = m9
        char_names[cid] = name

    # all_drops: skill -> (boss, tier)
    seen_b = set()
    unique_bosses = []
    for b, t in weekly:
        if b not in seen_b:
            seen_b.add(b); unique_bosses.append((b, t))
    all_drops = {}
    for boss, b_tier in unique_bosses:
        for skill, s_tier in get_boss_drops(boss):
            if skill not in all_drops:
                all_drops[skill] = (boss, b_tier)

    # 枚举所有 2DPS+1H 组合
    teams = []
    for i, dps1 in enumerate(dps_list):
        for j in range(i+1, len(dps_list)):
            dps2 = dps_list[j]
            for healer in healer_list:
                ids = [dps1[0], dps2[0], healer[0]]
                if len(set(ids)) != 3: continue
                owners = [dps1[3], dps2[3], healer[3]]
                if len(set(owners)) != 3: continue
                conflict, _ = calculate_team_conflict(ids, miss_10_all, miss_9_all)
                # 计算 owner 多样性 (这里固定 3, 主要是为了排序)
                teams.append({"chars": ids, "conflict": conflict})

    teams.sort(key=lambda x: x["conflict"])

    # 贪心挑选最多 10 个不重叠的车
    picked = []
    used_chars = set()
    for t in teams:
        if any(c in used_chars for c in t["chars"]):
            continue
        picked.append(t)
        for c in t["chars"]:
            used_chars.add(c)
        if len(picked) >= 10:
            break

    return {
        "weekly": [{"name": b, "tier": int(t)} for b, t in weekly],
        "all_chars": [
            {"id": c[0], "name": c[1], "server": c[2], "owner": c[5] or "",
             "is_dps": c[3], "is_n": c[4], "is_CD": c[6]}
            for c in characters
        ],
        "teams": teams[:50],  # 前 50 个组合, 让用户选
        "picked_10": picked,
        "picked_3": picked,  # 兼容旧字段
    }


if __name__ == '__main__':
    optimize_teams()
