#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 数据库表结构定义
版本：v1.0
日期：2026-05-18
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

-- 参考图管理
CREATE TABLE IF NOT EXISTS reference_images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT NOT NULL,           -- 本地文件路径
    remote_url      TEXT,                    -- RunningHub返回的URL
    uploaded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME,                -- URL过期时间
    user_id         TEXT,
    is_active       INTEGER DEFAULT 1
);

-- 任务记录（共用）
CREATE TABLE IF NOT EXISTS generation_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT UNIQUE NOT NULL,    -- RunningHub任务ID
    workflow_type   TEXT NOT NULL,            -- 'photo' / 'multiphoto' / 'video'
    prompt          TEXT NOT NULL,
    optimized_prompt TEXT,
    reference_id    INTEGER,
    reference_url   TEXT NOT NULL,           -- 参考图URL（冗余存储）
    workflow_id     TEXT,                    -- 具体工作流ID
    status          TEXT DEFAULT 'PENDING',  -- PENDING / RUNNING / SUCCESS / FAILED
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    completed_at    DATETIME,
    error_message   TEXT,
    FOREIGN KEY (workflow_type) REFERENCES workflow_types(code),
    FOREIGN KEY (reference_id) REFERENCES reference_images(id)
);

-- 生成结果（共用）
CREATE TABLE IF NOT EXISTS generation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    result_type     TEXT NOT NULL,            -- 'image' / 'video'
    -- 媒体信息
    image_url       TEXT,                     -- RunningHub返回URL
    local_path      TEXT,                     -- 本地保存路径
    width           INTEGER,
    height          INTEGER,
    file_size       INTEGER,
    duration        INTEGER,                  -- 视频时长(秒)，图片为NULL
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
    set_name        TEXT,                     -- '卧室纯欲风4宫格'
    grid_layout     TEXT,                     -- '2x2' / '3x3' / '1x4'
    total_count     INTEGER,                  -- 图片数量
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES generation_tasks(id)
);

-- 多图套装子项
CREATE TABLE IF NOT EXISTS multiphoto_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id          INTEGER NOT NULL,
    index_in_grid   INTEGER,                  -- 0,1,2,3 表示位置
    image_url       TEXT,
    local_path      TEXT,
    width           INTEGER,
    height          INTEGER,
    exif_injected   INTEGER DEFAULT 0,
    shot_at         DATETIME,
    FOREIGN KEY (set_id) REFERENCES multiphoto_sets(id)
);

-- 缓存表（共用）
CREATE TABLE IF NOT EXISTS prompt_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_hash     TEXT UNIQUE NOT NULL,    -- MD5(prompt+reference_url)
    workflow_type   TEXT NOT NULL,            -- 区分类型
    prompt          TEXT NOT NULL,
    reference_url   TEXT NOT NULL,
    status          TEXT DEFAULT 'PENDING',  -- PENDING / RUNNING / SUCCESS / FAILED
    task_id         TEXT,
    result_id       INTEGER,
    hit_count       INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME,
    expires_at      DATETIME,                -- 30天后过期
    FOREIGN KEY (workflow_type) REFERENCES workflow_types(code)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_tasks_type_status ON generation_tasks(workflow_type, status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON generation_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_task_id ON generation_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_results_local ON generation_results(local_path);
CREATE INDEX IF NOT EXISTS idx_results_task ON generation_results(task_id);
CREATE INDEX IF NOT EXISTS idx_cache_type_hash ON prompt_cache(workflow_type, prompt_hash);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON prompt_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_multiphoto_task ON multiphoto_sets(task_id);
CREATE INDEX IF NOT EXISTS idx_multiphoto_items_set ON multiphoto_items(set_id);
CREATE INDEX IF NOT EXISTS idx_reference_active ON reference_images(is_active);
"""

# 初始化数据
INIT_DATA_SQL = """
-- 插入工作流类型（如果不存在）
INSERT OR IGNORE INTO workflow_types (code, name, workflow_id) VALUES
    ('photo', '单人照片', '2047002838944980993'),
    ('multiphoto', '多照片套装', '2054941025688399873'),
    ('video', '视频生成', '2048133528671490050');
"""

def get_schema_sql():
    """获取完整的建表SQL"""
    return SCHEMA_SQL

def get_init_data_sql():
    """获取初始化数据SQL"""
    return INIT_DATA_SQL