#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百战助手 - 本地命令行入口
====================
复刻 QQ 机器人命令格式，让你在本地终端直接使用百战助手所有功能。

用法:
    python main.py <操作> [参数...]

常用命令:
    列表                       列出所有角色
    查询 <服务器> <角色名>      查询角色技能
    BOSS <BOSS名>              查询BOSS掉落
    技能查询 <技能名> [等级]    查询哪些角色拥有该技能
    推荐 <角色名>              角色细化方案
    组队推荐                   2输出+1奶最优组队
    周报                       本周BOSS综合分析
    刷新CD                    重置所有CD为未打
    设置CD <角色名> <0|1>      单角色CD设置
    设置 <角色名> <owner> <dps> <n> [CD]   设置角色标签
    删除 <角色名>              删除角色
    帮助                       显示帮助
"""

import sys
import os
import io

# 强制 UTF-8 输出，Windows GBK 控制台也能正常显示
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 把当前目录加入路径，以便 import 同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bai_zhan_db as db
from import_boss_drops import import_boss_drops, query_boss_skills, query_skill_from_boss
import recommend as rec_mod
import team_optimizer as team_mod
import weekly_report as wr_mod


def ensure_db():
    """确保数据库已初始化"""
    if not os.path.exists(db.DB_PATH):
        print("数据库不存在，正在初始化...")
        db.init_db()


def cmd_list(args):
    """列表 - 列出所有角色（详细）"""
    db.list_all_chars()


def cmd_query(args):
    """查询 <服务器> <角色名>"""
    if len(args) < 2:
        print("用法: 查询 <服务器> <角色名>")
        print("示例: 查询 天鹅坪 一鉴往一")
        return
    db.print_character_skills(args[0], args[1] + "@" + args[0])


def cmd_boss(args):
    """BOSS <BOSS名>"""
    if len(args) < 1:
        print("用法: BOSS <BOSS名>")
        print("示例: BOSS 钱宗龙")
        return
    query_boss_skills(args[0])


def cmd_skill(args):
    """技能查询 <技能名> [等级]"""
    if len(args) < 1:
        print("用法: 技能查询 <技能名> [等级]")
        print("示例: 技能查询 天工机甲龙")
        print("示例: 技能查询 天工机甲龙 10级")
        return
    skill_name = args[0]
    level = args[1] if len(args) >= 2 else None
    db.query_skill_all(skill_name, level)


def cmd_recommend(args):
    """推荐 <角色名>"""
    if len(args) < 1:
        print("用法: 推荐 <角色名>")
        print("示例: 推荐 一叶之深秋")
        return
    user_input = args[0]
    conn = db.get_db()
    cursor = conn.cursor()
    if "@" in user_input:
        rows = cursor.execute("SELECT name FROM characters WHERE name=?", (user_input,)).fetchall()
    else:
        rows = cursor.execute("SELECT name FROM characters WHERE name LIKE ?", (f"%{user_input}%",)).fetchall()
    conn.close()
    if not rows:
        print(f"[X] 未找到匹配角色: {user_input}")
        return
    if len(rows) > 1:
        print(f"匹配到 {len(rows)} 个角色，使用第一个：")
        for r in rows:
            print(f"  - {r['name']}")
    wr_mod.analyze_character(rows[0]["name"])



def cmd_team(args):
    """组队推荐"""
    team_mod.optimize_teams()


def cmd_weekly(args):
    """周报 [角色名]"""
    wr_mod.analyze_all()


def cmd_reset_cd(args):
    """刷新CD - 重置所有CD为未打"""
    db.reset_all_cd()


def cmd_set_cd(args):
    """设置CD <角色名> <0|1>"""
    if len(args) < 2:
        print("用法: 设置CD <角色名> <0|1>")
        print("  0 = 本周未打, 1 = 本周已打")
        return
    name = args[0]
    cd = int(args[1])
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE characters SET is_CD=? WHERE name LIKE ?", (cd, f"%{name}%"))
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    if updated > 0:
        status = "已打" if cd == 1 else "未打"
        print(f"[OK] 已设置 [{name}] 本周CD: {status}（影响 {updated} 个角色）")
    else:
        print(f"[X] 未找到角色: {name}")


def cmd_set(args):
    """设置 <角色名> <owner> <dps> <n> [CD]"""
    if len(args) < 4:
        print("用法: 设置 <角色名> <owner> <dps> <n> [CD]")
        print("  owner: 账号归属人")
        print("  dps:   0=非输出, 1=输出")
        print("  n:     0=非奶, 1=奶")
        print("  CD:    0=本周未打, 1=本周已打（可选）")
        print("示例: 设置 一鉴往一 老宋 1 1")
        print("示例: 设置 毒里毒气 dldq 1 0 1")
        return
    name = args[0]
    owner = args[1]
    is_dps = int(args[2])
    is_n = int(args[3])
    is_cd = int(args[4]) if len(args) >= 5 else None
    db.set_role(name, owner, is_dps, is_n, is_cd)


def cmd_delete(args):
    """删除 <角色名>"""
    if len(args) < 1:
        print("用法: 删除 <角色名>")
        print("      确认删除 <角色名>")
        return
    name = args[0]
    conn = db.get_db()
    cursor = conn.cursor()
    matches = cursor.execute(
        "SELECT name, server FROM characters WHERE name LIKE ?", (f"%{name}%",)
    ).fetchall()
    conn.close()
    if not matches:
        print(f"[X] 未找到角色: {name}")
        return
    print("匹配到以下角色，请用 [确认删除 <名字>] 来确认：")
    for m in matches:
        print(f"  - {m['name']}@{m['server']}")


def cmd_confirm_delete(args):
    """确认删除 <角色名>"""
    if len(args) < 1:
        print("用法: 确认删除 <角色名>")
        return
    db.delete_character(args[0])


def cmd_add(args):
    """添加角色 - 用于测试或手动录入
    用法: 添加 <角色名> <服务器> <精力> <耐力> <owner> <dps> <n> [技能:等级,技能:等级,...]
    """
    if len(args) < 7:
        print("用法: 添加 <角色名> <服务器> <精力> <耐力> <owner> <dps> <n> [技能:等级,技能:等级,...]")
        print("示例: 添加 一鉴往一 天鹅坪 26.5 25.6 老宋 1 1 凶刃乱舞:10,剑心通明:9")
        return
    name, server, essence, stamina = args[0], args[1], args[2], args[3]
    owner, is_dps, is_n = args[4], int(args[5]), int(args[6])
    skill_str = args[7] if len(args) >= 8 else ""

    skills_data = []
    if skill_str:
        for item in skill_str.split(','):
            if ':' in item:
                s_name, s_lv = item.split(':', 1)
                skills_data.append({
                    "skill_name": s_name.strip(),
                    "skill_level": int(s_lv.strip()),
                    "attribute_type": "",
                    "is_common": False
                })

    full_name = f"{name}@{server}"
    db.add_character(full_name, server, essence, stamina, skills_data)
    db.set_role(name, owner, is_dps, is_n)


def cmd_help(args):
    """显示帮助"""
    print(__doc__)
    print("\n更多细节请查看 README.md")


def cmd_init(args):
    """初始化数据库（会自动导入 BOSS 数据）"""
    db.init_db()
    if not os.path.exists(db.DB_PATH):
        print("[X] 初始化失败")
        return
    print("\n正在导入 BOSS 掉落数据...")
    import_boss_drops()


COMMANDS = {
    "列表": cmd_list,
    "查询": cmd_query,
    "BOSS": cmd_boss,
    "技能查询": cmd_skill,
    "推荐": cmd_recommend,
    "组队推荐": cmd_team,
    "组队": cmd_team,
    "周报": cmd_weekly,
    "刷新CD": cmd_reset_cd,
    "设置CD": cmd_set_cd,
    "设置": cmd_set,
    "删除": cmd_delete,
    "确认删除": cmd_confirm_delete,
    "添加": cmd_add,
    "初始化": cmd_init,
    "帮助": cmd_help,
    "help": cmd_help,
}


def main():
    if len(sys.argv) < 2:
        cmd_help([])
        return

    op = sys.argv[1]
    args = sys.argv[2:]

    if op not in COMMANDS:
        print(f"[X] 未知命令: {op}")
        print("\n可用命令:", "、".join(COMMANDS.keys()))
        return

    if op not in ("初始化", "帮助", "help"):
        try:
            ensure_db()
        except Exception as e:
            print(f"[X] 数据库未就绪，请先运行: python main.py 初始化")
            print(f"   错误: {e}")
            return

    try:
        COMMANDS[op](args)
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception as e:
        print(f"[X] 执行出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()





