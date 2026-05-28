#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 数据库表结构定义
版本：v1.1
日期：2026-05-27
变更：新增 reference_task_mapping、task_dependencies 表；扩展多表字段以支持追溯、重试、异步模式
"""

SCHEMA_SQL = """
-- 工作流类型枚举
CREATE TABLE IF NOT EXISTS workflow_types (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT UNIQUE NOT NULL,   -- 'photo' / 'multiphoto' / 'video'
    name            TEXT NOT NULL,           -- '单人照片' / '多照片套装' / '视频生成'
    workflow_id     TEXT,                    -- 默认工作流ID
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 人物形象配置表
CREATE TABLE IF NOT EXISTS character_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,           -- 配置名称，如"默认亚洲女性"
    description     TEXT,                    -- 人物描述文本（肤色、体型、五官等）
    height          TEXT,                    -- 身高体重，如"163cm/49kg"
    prompt_template TEXT,                    -- 提示词模板，变量占位符 {user_prompt}
    default_ref_path TEXT,                   -- 默认参考图路径
    is_default      INTEGER DEFAULT 0,       -- 是否默认（0/1）
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 需求表（用户提交的需求）
CREATE TABLE IF NOT EXISTS demands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_prompt      TEXT NOT NULL,           -- 用户原始需求
    workflow_type   TEXT,                     -- photo/multiphoto/video（汇总类型）
    reference_path  TEXT,                     -- 用户提供的参考图路径
    status          TEXT DEFAULT 'PENDING',  -- PENDING/CONFIRMED/EXECUTING/SUCCESS/FAILED
    plan_status     TEXT DEFAULT 'PENDING',  -- PENDING/SENT/CONFIRMED/REJECTED
    total_tasks     INTEGER DEFAULT 0,       -- 任务总数
    completed_tasks INTEGER DEFAULT 0,       -- 已完成数
    confirm_token   TEXT,                    -- 确认码（6位随机）
    confirm_expires_at DATETIME,             -- 确认码过期时间
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME,
    confirmed_at    DATETIME,
    completed_at    DATETIME
);

-- 需求任务表（一个需求拆解为多个任务）
CREATE TABLE IF NOT EXISTS demand_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    demand_id       INTEGER NOT NULL,
    task_no         INTEGER NOT NULL,        -- 顺序号（1,2,3...）
    workflow_type   TEXT NOT NULL,           -- photo/multiphoto/video
    prompt          TEXT,                     -- 组合后最终提示词
    reference_path  TEXT,                    -- 参考图路径
    reference_url   TEXT,                    -- 参考图URL（HTTP/RunningHub）
    task_id         TEXT,                    -- RunningHub task_id
    status          TEXT DEFAULT 'QUEUED',   -- QUEUED/RUNNING/SUCCESS/FAILED
    retry_count     INTEGER DEFAULT 0,        -- 已重试次数
    max_retries     INTEGER DEFAULT 3,       -- 最大重试次数
    result_data     TEXT,                    -- 结果数据（JSON字符串）
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME,
    error_message   TEXT,
    FOREIGN KEY (demand_id) REFERENCES demands(id)
);

-- 参考图管理（扩展：来源任务追溯）
CREATE TABLE IF NOT EXISTS reference_images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT NOT NULL,           -- 本地文件路径
    remote_url      TEXT,                    -- RunningHub返回的URL
    uploaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME,                -- URL过期时间
    user_id         TEXT,
    is_active       INTEGER DEFAULT 1,
    -- 新增字段：来源任务追溯
    source_task_id  INTEGER,                 -- 该图是哪次生成任务的产物（关联 generation_tasks.id）
    original_prompt TEXT,                    -- 原始提示词
    FOREIGN KEY (source_task_id) REFERENCES generation_tasks(id)
);

-- 参考图 ↔ 生成任务 的映射关系（多对一）
CREATE TABLE IF NOT EXISTS reference_task_mapping (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id    INTEGER NOT NULL,        -- 参考图ID (reference_images.id)
    task_id         INTEGER NOT NULL,        -- 生成该图的任务ID (generation_tasks.id)
    used_as_ref_for TEXT,                    -- 被谁引用：'photo' / 'multiphoto' / 'video'
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reference_id) REFERENCES reference_images(id),
    FOREIGN KEY (task_id) REFERENCES generation_tasks(id)
);

-- 任务记录（扩展：重试机制 + 本地路径 + 优化提示词）
CREATE TABLE IF NOT EXISTS generation_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT UNIQUE NOT NULL,    -- RunningHub任务ID（API返回的远程ID）
    workflow_type   TEXT NOT NULL,           -- 'photo' / 'multiphoto' / 'video'
    prompt          TEXT NOT NULL,
    optimized_prompt TEXT,                   -- 优化后的分镜提示词（video类型重试时使用）
    reference_id    INTEGER,
    reference_url   TEXT NOT NULL,           -- 参考图URL（冗余存储）
    workflow_id     TEXT,                    -- 具体工作流ID
    status          TEXT DEFAULT 'PENDING',  -- PENDING / RUNNING / SUCCESS / FAILED
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    completed_at    DATETIME,
    error_message   TEXT,
    -- 新增字段
    retry_count     INTEGER DEFAULT 0,       -- 已重试次数
    max_retries     INTEGER DEFAULT 3,       -- 最大重试次数
    local_path      TEXT,                    -- 本地路径（冗余存储，方便追溯）
    FOREIGN KEY (workflow_type) REFERENCES workflow_types(code),
    FOREIGN KEY (reference_id) REFERENCES reference_images(id)
);

-- 任务依赖链（下游等待上游）
CREATE TABLE IF NOT EXISTS task_dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_task_id  INTEGER NOT NULL,        -- 上游任务（如 Photo 生成了参考图）
    child_task_id   INTEGER NOT NULL,        -- 下游任务（如 Video 引用了该图）
    dependency_type TEXT DEFAULT 'reference_image',
    reference_ready INTEGER DEFAULT 0,       -- 参考图是否就绪（0=未就绪，1=已就绪）
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_task_id) REFERENCES generation_tasks(id),
    FOREIGN KEY (child_task_id) REFERENCES generation_tasks(id)
);

-- 生成结果（共用）
CREATE TABLE IF NOT EXISTS generation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    result_type     TEXT NOT NULL,           -- 'image' / 'video'
    -- 媒体信息
    image_url       TEXT,                    -- RunningHub返回URL
    local_path      TEXT,                    -- 本地保存路径
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,
    duration        INTEGER,                 -- 视频时长(秒)，图片为NULL
    -- EXIF信息
    exif_injected   INTEGER DEFAULT 0,
    phone_model     TEXT,
    gps_lat         REAL,
    gps_lon         REAL,
    shot_at         DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES generation_tasks(id)
);

-- 多图套装（multiphoto专用）
CREATE TABLE IF NOT EXISTS multiphoto_sets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    set_name        TEXT,                    -- '卧室纯欲风4宫格'
    grid_layout     TEXT,                    -- '2x2' / '3x3' / '1x4'
    total_count     INTEGER,                 -- 图片数量
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES generation_tasks(id)
);

-- 多图套装子项（扩展：prompt 追溯）
CREATE TABLE IF NOT EXISTS multiphoto_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id          INTEGER NOT NULL,
    index_in_grid   INTEGER,                 -- 0,1,2,3 表示位置
    image_url       TEXT,
    local_path      TEXT,
    width           INTEGER,
    height          INTEGER,
    exif_injected   INTEGER DEFAULT 0,
    shot_at         DATETIME,
    -- 新增字段
    prompt          TEXT,                    -- 该张图的提示词
    task_id         INTEGER,                -- 关联的任务ID
    FOREIGN KEY (set_id) REFERENCES multiphoto_sets(id),
    FOREIGN KEY (task_id) REFERENCES generation_tasks(id)
);

-- 缓存表（共用，扩展：支持 stale 检测）
CREATE TABLE IF NOT EXISTS prompt_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash     TEXT UNIQUE NOT NULL,    -- MD5(prompt+reference_local_path)
    workflow_type   TEXT NOT NULL,           -- 区分类型
    prompt          TEXT NOT NULL,
    reference_url   TEXT,
    reference_local_path TEXT,               -- 本地路径（参与缓存键）
    status          TEXT DEFAULT 'PENDING',  -- PENDING / RUNNING / SUCCESS / FAILED
    task_id         TEXT,                    -- RunningHub task_id
    result_id       INTEGER,
    hit_count       INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME,
    expires_at      DATETIME,                -- 30天后过期
    stale_checked_at DATETIME,               -- 上次 stale 检查时间
    FOREIGN KEY (workflow_type) REFERENCES workflow_types(code)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON generation_tasks(workflow_type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON generation_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_task_id ON generation_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON generation_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_started ON generation_tasks(started_at);
CREATE INDEX IF NOT EXISTS idx_results_local ON generation_results(local_path);
CREATE INDEX IF NOT EXISTS idx_results_task ON generation_results(task_id);
CREATE INDEX IF NOT EXISTS idx_cache_type_hash ON prompt_cache(workflow_type, prompt_hash);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON prompt_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_status ON prompt_cache(status);
CREATE INDEX IF NOT EXISTS idx_multiphoto_task ON multiphoto_sets(task_id);
CREATE INDEX IF NOT EXISTS idx_multiphoto_items_set ON multiphoto_items(set_id);
CREATE INDEX IF NOT EXISTS idx_reference_active ON reference_images(is_active);
CREATE INDEX IF NOT EXISTS idx_ref_mapping_ref ON reference_task_mapping(reference_id);
CREATE INDEX IF NOT EXISTS idx_ref_mapping_task ON reference_task_mapping(task_id);
CREATE INDEX IF NOT EXISTS idx_task_dep_parent ON task_dependencies(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_task_dep_child ON task_dependencies(child_task_id);
CREATE INDEX IF NOT EXISTS idx_demands_status ON demands(status);
CREATE INDEX IF NOT EXISTS idx_demands_plan_status ON demands(plan_status);
CREATE INDEX IF NOT EXISTS idx_demands_confirm_token ON demands(confirm_token);
CREATE INDEX IF NOT EXISTS idx_demand_tasks_demand ON demand_tasks(demand_id);
CREATE INDEX IF NOT EXISTS idx_demand_tasks_status ON demand_tasks(status);
CREATE INDEX IF NOT EXISTS idx_character_profile_default ON character_profiles(is_default);
"""

# 初始化数据
INIT_DATA_SQL = """
-- 插入工作流类型（如果不存在）
INSERT OR IGNORE INTO workflow_types (code, name, workflow_id) VALUES
    ('photo', '单人照片', '2047002838944980993'),
    ('multiphoto', '多照片套装', '2054941025688399873'),
    ('video', '视频生成', '2048133528671490050');

-- 初始化默认人物形象配置
INSERT OR IGNORE INTO character_profiles (id, name, description, height, prompt_template, default_ref_path, is_default) VALUES
    (1, '默认亚洲女性', '中国28岁美女，曼妙身姿，曲线玲珑，凹凸有致，皮肤细腻，精致妆容',
     '163cm/49kg，三围86/62/86cm，腿长98cm，腰臀比0.72，紧致健身沙漏身材，蜜桃臀，纤细长腿',
     '{description} {height} {user_prompt}',
     '/root/.openclaw/workspace-companion2/data/images/avatar.jpg',
     1);
"""

def get_schema_sql():
    """获取完整的建表SQL"""
    return SCHEMA_SQL

def get_init_data_sql():
    """获取初始化数据SQL"""
    return INIT_DATA_SQL