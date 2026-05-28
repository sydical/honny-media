#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 数据库管理模块
版本：v1.1
日期：2026-05-27
变更：扩展支持 DB 先行流程、异步轮询、stale 检测、重试机制、任务依赖链追溯
"""

import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

# 导入表结构
from .schema import get_schema_sql, get_init_data_sql


class HonnyDBManager:
    """HonnyMedia 数据库管理器"""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.expanduser('~/.openclaw/workspace-companion2/data/honny-media/honny.db')

        self.db_path = db_path
        self.conn = None

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库连接和表结构"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # 执行建表SQL
        schema_sql = get_schema_sql()
        self.conn.executescript(schema_sql)

        # 插入初始化数据
        init_sql = get_init_data_sql()
        self.conn.executescript(init_sql)

        self.conn.commit()

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()

    # ============================================================
    # 参考图管理（扩展：来源任务追溯）
    # ============================================================

    def save_reference(self, file_path, remote_url, user_id=None, source_task_id=None, original_prompt=None):
        """保存参考图记录（支持来源任务追溯）
        
        Args:
            file_path: 本地文件路径
            remote_url: RunningHub 返回的 URL
            user_id: 用户 ID
            source_task_id: 该图是哪次生成任务的产物（generation_tasks.id）
            original_prompt: 原始提示词
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO reference_images 
            (file_path, remote_url, uploaded_at, expires_at, user_id, is_active, source_task_id, original_prompt)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """, (file_path, remote_url, datetime.now(), datetime.now() + timedelta(hours=24), 
              user_id, source_task_id, original_prompt))

        ref_id = cursor.lastrowid

        # 禁用之前的参考图
        cursor.execute("""
            UPDATE reference_images
            SET is_active = 0
            WHERE id != ? AND (user_id IS ? OR user_id IS NULL)
        """, (ref_id, user_id))

        self.conn.commit()
        return ref_id

    def save_reference_task_mapping(self, reference_id, task_id, used_as_ref_for=None):
        """保存参考图 ↔ 任务映射关系（支持多对一）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO reference_task_mapping (reference_id, task_id, used_as_ref_for, created_at)
            VALUES (?, ?, ?, ?)
        """, (reference_id, task_id, used_as_ref_for, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid

    def get_reference_by_id(self, ref_id):
        """根据 ID 获取参考图"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM reference_images WHERE id = ?", (ref_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_active_reference(self, user_id=None):
        """获取当前激活的参考图"""
        cursor = self.conn.cursor()
        if user_id:
            cursor.execute("""
                SELECT * FROM reference_images
                WHERE is_active = 1 AND user_id = ?
                ORDER BY uploaded_at DESC LIMIT 1
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT * FROM reference_images
                WHERE is_active = 1
                ORDER BY uploaded_at DESC LIMIT 1
            """)

        row = cursor.fetchone()
        return dict(row) if row else None

    def update_reference_url(self, ref_id, remote_url):
        """更新参考图的远程 URL（URL 过期重新上传时调用）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE reference_images
            SET remote_url = ?, expires_at = ?
            WHERE id = ?
        """, (remote_url, datetime.now() + timedelta(hours=24), ref_id))
        self.conn.commit()

    def is_reference_url_expired(self, ref_id):
        """检查参考图 URL 是否已过期"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT expires_at FROM reference_images WHERE id = ?", (ref_id,))
        row = cursor.fetchone()
        if not row:
            return True
        expires_at = datetime.fromisoformat(row['expires_at']) if isinstance(row['expires_at'], str) else row['expires_at']
        return datetime.now() > expires_at

    def find_result_by_local_path(self, local_path):
        """根据本地路径查找生成结果（用于参考图自动追溯）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT r.*, t.id as task_db_id
            FROM generation_results r
            JOIN generation_tasks t ON r.task_id = t.id
            WHERE r.local_path = ?
        """, (local_path,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 任务管理（扩展：task_id 分离、DB 先行、重试机制）
    # ============================================================

    def create_task(self, workflow_type, prompt, reference_url=None, reference_id=None, 
                    workflow_id=None, task_id=None, status='PENDING', optimized_prompt=None):
        """创建任务记录（DB 先行：先创建，后填 task_id）
        
        Args:
            workflow_type: 工作流类型 photo/multiphoto/video
            prompt: 原始提示词
            reference_url: 参考图 URL
            reference_id: 参考图 ID
            workflow_id: 具体工作流 ID
            task_id: RunningHub task_id（可后续再填）
            status: 默认 PENDING
            optimized_prompt: 优化后的提示词（video类型会存储优化后的分镜）
        Returns:
            task_db_id: 本地数据库 ID
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO generation_tasks
            (task_id, workflow_type, prompt, optimized_prompt, reference_url, reference_id, 
             workflow_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_id, workflow_type, prompt, optimized_prompt, reference_url, reference_id, 
              workflow_id, status, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid

    def update_task_task_id(self, task_db_id, task_id):
        """更新任务的 RunningHub task_id（在 API 返回后调用）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE generation_tasks
            SET task_id = ?
            WHERE id = ?
        """, (task_id, task_db_id))
        self.conn.commit()

    def update_task_status(self, task_id, status, error_message=None, local_path=None):
        """更新任务状态
        
        注意：RUNNING 时只更新 status + started_at，不更新 task_id。
        task_id 通过 update_task_task_id() 单独管理，避免职责混淆。
        """
        cursor = self.conn.cursor()
        now = datetime.now()

        if status == 'RUNNING':
            cursor.execute("""
                UPDATE generation_tasks
                SET status = ?, started_at = ?
                WHERE id = ? OR task_id = ?
            """, (status, now, task_id, task_id))

        elif status in ('SUCCESS', 'FAILED'):
            cursor.execute("""
                UPDATE generation_tasks
                SET status = ?, completed_at = ?, error_message = ?, local_path = ?
                WHERE id = ? OR task_id = ?
            """, (status, now, error_message, local_path, task_id, task_id))

        else:
            cursor.execute("""
                UPDATE generation_tasks
                SET status = ?
                WHERE id = ? OR task_id = ?
            """, (status, task_id, task_id))

        self.conn.commit()

    def update_task_retry_count(self, task_db_id, retry_count):
        """更新任务重试次数"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE generation_tasks
            SET retry_count = ?
            WHERE id = ?
        """, (retry_count, task_db_id))
        self.conn.commit()

    def get_task_by_task_id(self, task_id):
        """根据 RunningHub 的 task_id 获取任务"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM generation_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_task_by_id(self, task_db_id):
        """根据数据库 ID 获取任务"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM generation_tasks WHERE id = ?", (task_db_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_running_tasks(self):
        """获取所有 RUNNING 状态的任务（PollingWorker 轮询用）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM generation_tasks 
            WHERE status = 'RUNNING'
            ORDER BY started_at ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_stale_running_tasks(self, threshold_time):
        """获取超过阈值时间的 RUNNING 任务（疑似 stale）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM generation_tasks 
            WHERE status = 'RUNNING' AND started_at < ?
            ORDER BY started_at ASC
        """, (threshold_time,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 任务依赖链
    # ============================================================

    def save_task_dependency(self, parent_task_id, child_task_id, dependency_type='reference_image'):
        """保存任务依赖关系"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO task_dependencies (parent_task_id, child_task_id, dependency_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (parent_task_id, child_task_id, dependency_type, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid

    def get_tasks_dependent_on(self, parent_task_id):
        """获取依赖指定上游任务的下游任务列表"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT td.*, t.*
            FROM task_dependencies td
            JOIN generation_tasks t ON td.child_task_id = t.id
            WHERE td.parent_task_id = ?
            ORDER BY td.created_at ASC
        """, (parent_task_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def mark_reference_ready(self, child_task_id):
        """标记下游任务的参考图已就绪"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE task_dependencies
            SET reference_ready = 1
            WHERE child_task_id = ?
        """, (child_task_id,))
        self.conn.commit()

    # ============================================================
    # 结果管理
    # ============================================================

    def save_result(self, task_db_id, result_type, image_url, local_path, 
                    width=None, height=None, file_size=None, exif_data=None):
        """保存生成结果"""
        cursor = self.conn.cursor()

        exif_injected = 1 if exif_data else 0
        phone_model = exif_data.get('phone_model') if exif_data else None
        gps_lat = exif_data.get('gps_lat') if exif_data else None
        gps_lon = exif_data.get('gps_lon') if exif_data else None
        shot_at = exif_data.get('shot_at') if exif_data else None

        cursor.execute("""
            INSERT INTO generation_results
            (task_id, result_type, image_url, local_path, width, height, file_size,
             exif_injected, phone_model, gps_lat, gps_lon, shot_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (task_db_id, result_type, image_url, local_path, width, height, file_size,
              exif_injected, phone_model, gps_lat, gps_lon, shot_at, datetime.now()))

        self.conn.commit()
        return cursor.lastrowid

    def save_video_result(self, task_db_id, local_path, duration=None, file_size=None):
        """保存视频生成结果"""
        return self.save_result(task_db_id, 'video', None, local_path, file_size=file_size, 
                                exif_data={'shot_at': datetime.now()})

    def save_multiphoto_set(self, task_db_id, prompt, images):
        """保存多图套装（支持每张图 prompt 追溯）"""
        cursor = self.conn.cursor()

        # 计算网格布局
        count = len(images)
        if count == 4:
            grid_layout = '2x2'
        elif count == 9:
            grid_layout = '3x3'
        else:
            grid_layout = f'1x{count}'

        set_name = prompt[:50] if len(prompt) > 50 else prompt

        cursor.execute("""
            INSERT INTO multiphoto_sets
            (task_id, set_name, grid_layout, total_count, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (task_db_id, set_name, grid_layout, count, datetime.now()))

        set_id = cursor.lastrowid

        # 保存每张图片（含 prompt）
        for i, img in enumerate(images):
            cursor.execute("""
                INSERT INTO multiphoto_items
                (set_id, index_in_grid, image_url, local_path, width, height, 
                 exif_injected, shot_at, prompt, task_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (set_id, i, img.get('image_url'), img.get('local_path'),
                  img.get('width'), img.get('height'),
                  1 if img.get('exif_injected') else 0, img.get('shot_at'),
                  img.get('prompt'), task_db_id))

        self.conn.commit()
        return set_id

    def get_result_by_task_db_id(self, task_db_id):
        """根据任务数据库 ID 获取结果"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM generation_results WHERE task_id = ?", (task_db_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 缓存管理（扩展：stale 检测）
    # ============================================================

    def make_cache_key(self, workflow_type, prompt, reference_local_path=None):
        """生成缓存键 - workflow_type + prompt + reference_local_path 共同参与哈希"""
        content = f"{workflow_type}:{prompt}:{reference_local_path or ''}"
        return hashlib.md5(content.encode()).hexdigest()

    def get_cache(self, workflow_type, prompt, reference_local_path=None):
        """获取缓存（含 stale 检测）"""
        cache_key = self.make_cache_key(workflow_type, prompt, reference_local_path)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM prompt_cache
            WHERE prompt_hash = ? AND workflow_type = ?
        """, (cache_key, workflow_type))

        row = cursor.fetchone()
        cache = dict(row) if row else None

        # stale 检测：RUNNING 状态超过 15 分钟认为已失效
        if cache and cache['status'] == 'RUNNING':
            updated_at = cache.get('updated_at')
            if updated_at:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)
                cache_age = datetime.now() - updated_at
                if cache_age > timedelta(minutes=15):
                    print(f"⚠️ 缓存 stale（RUNNING 超过 15 分钟），删除: {cache_key}")
                    self.delete_cache(cache_key)
                    return None

        return cache

    def set_cache(self, workflow_type, prompt, reference_local_path=None, 
                  status='PENDING', task_id=None, reference_url=None):
        """设置缓存"""
        cache_key = self.make_cache_key(workflow_type, prompt, reference_local_path)
        expires_at = datetime.now() + timedelta(days=30)
        now = datetime.now()

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO prompt_cache
            (prompt_hash, workflow_type, prompt, reference_url, status, task_id, 
             created_at, updated_at, expires_at, reference_local_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cache_key, workflow_type, prompt, reference_url, status, task_id,
              now, now, expires_at, reference_local_path))

        self.conn.commit()
        return cache_key

    def update_cache_success(self, cache_key, result_id=None):
        """更新缓存为成功状态"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE prompt_cache
            SET status = 'SUCCESS', result_id = ?, updated_at = ?
            WHERE prompt_hash = ?
        """, (result_id, datetime.now(), cache_key))
        self.conn.commit()

    def update_cache_running(self, cache_key, task_id):
        """更新缓存为运行中状态"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE prompt_cache
            SET status = 'RUNNING', task_id = ?, updated_at = ?
            WHERE prompt_hash = ?
        """, (task_id, datetime.now(), cache_key))
        self.conn.commit()

    def delete_cache(self, cache_key):
        """删除缓存"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM prompt_cache WHERE prompt_hash = ?", (cache_key,))
        self.conn.commit()

    def increment_cache_hit(self, cache_key):
        """增加缓存命中次数"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE prompt_cache
            SET hit_count = hit_count + 1
            WHERE prompt_hash = ?
        """, (cache_key,))
        self.conn.commit()

    # ============================================================
    # 统计和查询
    # ============================================================

    def get_stats(self, days=7):
        """获取统计信息"""
        cursor = self.conn.cursor()

        since = datetime.now() - timedelta(days=days)

        cursor.execute("""
            SELECT
                workflow_type,
                COUNT(*) as total,
                SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) as running
            FROM generation_tasks
            WHERE created_at >= ?
            GROUP BY workflow_type
        """, (since,))

        workflow_stats = [dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(hit_count) as total_hits
            FROM prompt_cache
        """)
        cache_row = cursor.fetchone()

        return {
            'workflow_stats': workflow_stats,
            'cache_total': cache_row['total'] if cache_row else 0,
            'cache_hits': cache_row['total_hits'] if cache_row else 0
        }

    def get_gallery(self, workflow_type=None, limit=50):
        """获取图片库"""
        cursor = self.conn.cursor()

        if workflow_type:
            cursor.execute("""
                SELECT
                    t.task_id,
                    r.local_path,
                    r.width,
                    r.height,
                    r.shot_at,
                    r.phone_model,
                    t.workflow_type
                FROM generation_tasks t
                LEFT JOIN generation_results r ON r.task_id = t.id
                WHERE t.workflow_type = ? AND r.local_path IS NOT NULL
                ORDER BY r.created_at DESC
                LIMIT ?
            """, (workflow_type, limit))
        else:
            cursor.execute("""
                SELECT
                    t.task_id,
                    r.local_path,
                    r.width,
                    r.height,
                    r.shot_at,
                    r.phone_model,
                    t.workflow_type
                FROM generation_tasks t
                LEFT JOIN generation_results r ON r.task_id = t.id
                WHERE r.local_path IS NOT NULL
                ORDER BY r.created_at DESC
                LIMIT ?
            """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def cleanup_expired(self, days=30):
        """清理过期数据"""
        cursor = self.conn.cursor()

        cursor.execute("""
            DELETE FROM prompt_cache
            WHERE expires_at < datetime('now', '-{} days')
        """.format(days))
        expired_cache = cursor.rowcount

        cursor.execute("""
            DELETE FROM generation_tasks
            WHERE status = 'SUCCESS'
              AND completed_at < datetime('now', '-180 days')
        """)
        expired_tasks = cursor.rowcount

        self.conn.commit()
        return {'expired_cache': expired_cache, 'expired_tasks': expired_tasks}


# 单例模式
_db_instance = None

def get_db_manager():
    """获取数据库管理器单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = HonnyDBManager()
    return _db_instance