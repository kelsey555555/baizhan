-- 百战技能数据库 schema
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    server TEXT,
    region TEXT,
    essence REAL,  -- 精力
    stamina REAL,  -- 耐力
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_dps INTEGER DEFAULT 0,  -- 是否输出
    is_n INTEGER DEFAULT 0,  -- 是否奶
    owner TEXT DEFAULT '',  -- 账号主人
    is_CD INTEGER DEFAULT 0,  -- 本周是否已打过(0=未打, 1=已打)
    UNIQUE(name, server)
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    skill_name TEXT NOT NULL,
    skill_level INTEGER NOT NULL,  -- 8, 9, 10
    attribute_type TEXT,  -- 红破/黄破/蓝破/绿破/紫破/白破/黑破
    is_common BOOLEAN DEFAULT 0,  -- 是否为常用技能
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    UNIQUE(character_id, skill_name)
);

-- BOSS掉落表（来源JX3BOX）
CREATE TABLE IF NOT EXISTS boss_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    boss_name TEXT NOT NULL,
    color TEXT,  -- 红色/黄色/蓝色/绿色/紫色/黑色/无颜色
    cooldown TEXT,  -- 调息时间
    effect TEXT,  -- 效果描述
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_name, boss_name)
);

CREATE INDEX IF NOT EXISTS idx_skills_character ON skills(character_id);
CREATE INDEX IF NOT EXISTS idx_skills_level ON skills(skill_level);
CREATE INDEX IF NOT EXISTS idx_skills_attribute ON skills(attribute_type);
CREATE INDEX IF NOT EXISTS idx_boss_drops_skill ON boss_drops(skill_name);
CREATE INDEX IF NOT EXISTS idx_boss_drops_boss ON boss_drops(boss_name);


-- BOSS info (extended data, manually managed or from jx3box)
CREATE TABLE IF NOT EXISTS boss_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boss_name TEXT UNIQUE NOT NULL,
    boss_number INTEGER,             -- 1-100
    map_name TEXT,                  -- 出现地图
    map_url TEXT,                   -- 地图链接
    level INTEGER,                  -- 推荐等级
    refresh_time TEXT,              -- 刷新时间描述
    route TEXT,                     -- 推荐路线
    is_weekly INTEGER DEFAULT 0,    -- 是否本周BOSS
    week_number TEXT,               -- 第几周(YYYY-WW)
    notes TEXT,
    updated_at TEXT
);

-- Skill info (extended data)
CREATE TABLE IF NOT EXISTS skill_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT UNIQUE NOT NULL,
    color TEXT,
    cooldown TEXT,
    effect TEXT,
    category TEXT,                  -- 分类：伤害/治疗/控制/召唤/增益/减益
    is_common INTEGER DEFAULT 0,    -- 是否常用技能
    notes TEXT,
    updated_at TEXT
);


-- 出货待分赃记录
CREATE TABLE IF NOT EXISTS loot_drops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    car_number INTEGER,              -- 第几车 (1-based, 可空)
    boss_name TEXT NOT NULL,         -- BOSS 名
    boss_tier INTEGER,               -- 9 或 10 阶
    skill_name TEXT NOT NULL,        -- 技能名
    skill_tier INTEGER,              -- 9 或 10 重
    char_id INTEGER,                 -- 谁拿到了 (可空: 待定)
    obtained_at TEXT DEFAULT (date('now', 'localtime')),
    distributed INTEGER DEFAULT 0,   -- 0 待分, 1 已分
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (char_id) REFERENCES characters(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_loot_dist ON loot_drops(distributed);
CREATE INDEX IF NOT EXISTS idx_loot_boss ON loot_drops(boss_name);
CREATE INDEX IF NOT EXISTS idx_loot_char ON loot_drops(char_id);
