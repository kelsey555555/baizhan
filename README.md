# 百战助手 - Baizhan Assistant

剑网3百战异闻录助手，Web 可视化界面，支持角色管理、BOSS 技能查询、组队推荐、周报分析等功能。

## 功能

- **角色管理** — 添加/编辑角色，按 BOSS 分类配置技能（重数、不可学）
- **BOSS 技能库** — 展示所有 BOSS 及技能掉落（效果、调息时间）
- **本周 BOSS 管理** — 配置本周 BOSS 列表
- **技能查询** — 按技能名、等级搜索
- **组队推荐** — 根据角色技能自动推荐最优组队
- **周报分析** — 每周 BOSS 完成情况统计
- **排表** — 拖拽排表，支持保存恢复
- **出货记录** — 掉落物品管理

## 快速开始

### 本地运行

```bash
pip install flask
cd web
python app.py
```

浏览器访问 http://127.0.0.1:5000

### 部署到 Vercel

1. 将项目推送到 GitHub
2. 在 Vercel 中导入仓库
3. 框架选择 **Other**，构建命令留空
4. 部署即可

Vercel 自动使用 `vercel.json` 和 `api/index.py` 配置。

**注意**：Vercel 使用 `/tmp` 临时存储，冷启动时会重新导入 BOSS 数据，用户数据会丢失。

## 项目结构

```
api/index.py        -- Vercel 部署入口
vercel.json         -- Vercel 配置
requirements.txt    -- Python 依赖
data/               -- 数据文件
  boss_drops.json   -- BOSS 掉落数据
  schema.sql        -- 数据库建表
scripts/            -- 核心脚本
  bai_zhan_db.py    -- 数据库操作
  import_boss_drops.py -- 导入 BOSS 数据
  main.py           -- CLI 入口
  recommend.py      -- 推荐算法
  team_optimizer.py -- 组队优化
  weekly_report.py  -- 周报分析
web/                -- Web 界面
  app.py            -- Flask 主程序
  templates/        -- HTML 模板
  static/           -- 静态资源
README.md
'

