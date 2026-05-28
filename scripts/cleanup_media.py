#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 清理脚本
版本：v1.0
日期：2026-05-27

功能：
- 删除 30 天前生成的本地图片/视频文件
- 同步清理 DB 中的过期记录（按正确顺序）
- 支持 cron 每日调度

用法：
    python3 scripts/cleanup_media.py              # 清理 30 天前
    python3 scripts/cleanup_media.py --days 7    # 清理 7 天前

Cron 配置（每天早上 3 点执行）：
    0 3 * * * cd /root/.openclaw/skills/honny-media && python3 scripts/cleanup_media.py >> /var/log/honny-cleanup.log 2>&1
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.db_manager import HonnyDBManager


class MediaCleaner:
    """媒体文件与数据库清理器"""

    IMAGE_DIR = os.path.expanduser('~/.openclaw/workspace-companion2/data/images')
    VIDEO_DIR = os.path.expanduser('~/.openclaw/workspace-companion2/data/videos')

    def __init__(self, db_manager=None):
        self.db = db_manager or HonnyDBManager()
        self.stats = {
            'files_deleted': 0,
            'cache_deleted': 0,
            'results_deleted': 0,
            'tasks_deleted': 0,
            'multiphoto_items_deleted': 0,
            'multiphoto_sets_deleted': 0,
            'reference_images_deleted': 0,
        }

    def cleanup(self, days=30):
        """清理 30 天前的数据和文件
        
        删除顺序：
        1. 查询 DB，获取要删除的文件路径
        2. 删除本地文件
        3. 按依赖关系删除 DB 记录（multiphoto_items → multiphoto_sets → results → tasks → cache → reference_images）
        """
        cutoff = datetime.now() - timedelta(days=days)
        print(f"🧹 开始清理 {days} 天前的数据...")

        # Step 1: 查询要删除的文件路径
        file_paths = self._get_files_to_delete(cutoff)

        # Step 2: 删除本地文件
        self._delete_local_files(file_paths)

        # Step 3: 删除 DB 记录（按依赖关系顺序）
        self._delete_db_records(cutoff)

        print(f"\n✅ 清理完成:")
        print(f"   📁 本地文件: {self.stats['files_deleted']}")
        print(f"   💾 缓存记录: {self.stats['cache_deleted']}")
        print(f"   📊 结果记录: {self.stats['results_deleted']}")
        print(f"   📋 任务记录: {self.stats['tasks_deleted']}")
        print(f"   🖼️  多图套装子项: {self.stats['multiphoto_items_deleted']}")
        print(f"   🖼️  多图套装: {self.stats['multiphoto_sets_deleted']}")
        print(f"   🖼️  参考图: {self.stats['reference_images_deleted']}")

        return self.stats

    def _get_files_to_delete(self, cutoff):
        """获取要删除的文件路径列表"""
        cursor = self.db.conn.cursor()

        # 从 generation_results 获取
        cursor.execute("""
            SELECT local_path FROM generation_results 
            WHERE created_at < ? AND local_path IS NOT NULL
        """, (cutoff,))
        paths = [row['local_path'] for row in cursor.fetchall()]

        # 从 multiphoto_items 获取
        cursor.execute("""
            SELECT local_path FROM multiphoto_items 
            WHERE set_id IN (
                SELECT id FROM multiphoto_sets WHERE created_at < ?
            ) AND local_path IS NOT NULL
        """, (cutoff,))
        paths.extend([row['local_path'] for row in cursor.fetchall()])

        return [p for p in paths if p and os.path.exists(p)]

    def _delete_local_files(self, file_paths):
        """删除本地文件"""
        print(f"\n📁 删除本地文件 ({len(file_paths)} 个)...")

        for path in file_paths:
            try:
                os.remove(path)
                self.stats['files_deleted'] += 1
                # 打印被删除的文件（截断路径）
                short_path = path.replace(os.path.expanduser('~'), '~')
                print(f"   🗑️ {short_path}")
            except Exception as e:
                print(f"   ⚠️ 删除失败: {path} - {e}")

    def _delete_db_records(self, cutoff):
        """按依赖关系顺序删除 DB 记录"""
        cursor = self.db.conn.cursor()

        # 3a. 删除 multiphoto_items（依赖 multiphoto_sets）
        cursor.execute("""
            DELETE FROM multiphoto_items 
            WHERE set_id IN (
                SELECT id FROM multiphoto_sets WHERE created_at < ?
            )
        """, (cutoff,))
        self.stats['multiphoto_items_deleted'] = cursor.rowcount

        # 3b. 删除 multiphoto_sets
        cursor.execute("DELETE FROM multiphoto_sets WHERE created_at < ?", (cutoff,))
        self.stats['multiphoto_sets_deleted'] = cursor.rowcount

        # 3c. 删除 generation_results
        cursor.execute("DELETE FROM generation_results WHERE created_at < ?", (cutoff,))
        self.stats['results_deleted'] = cursor.rowcount

        # 3d. 删除 generation_tasks（保留 PENDING/RUNNING）
        cursor.execute("""
            DELETE FROM generation_tasks 
            WHERE created_at < ? AND status IN ('SUCCESS', 'FAILED')
        """, (cutoff,))
        self.stats['tasks_deleted'] = cursor.rowcount

        # 3e. 删除 prompt_cache
        cursor.execute("DELETE FROM prompt_cache WHERE created_at < ?", (cutoff,))
        self.stats['cache_deleted'] = cursor.rowcount

        # 3f. 删除 reference_images（只删非激活的过期参考图）
        cursor.execute("""
            DELETE FROM reference_images 
            WHERE uploaded_at < ? AND is_active = 0
        """, (cutoff,))
        self.stats['reference_images_deleted'] = cursor.rowcount

        self.db.conn.commit()

    def dry_run(self, days=30):
        """预览要删除的内容（不实际删除）"""
        cutoff = datetime.now() - timedelta(days=days)
        cursor = self.db.conn.cursor()

        print(f"🔍 预览清理内容（保留 {days} 天）...\n")

        # 统计各表
        tables = {
            'prompt_cache': "SELECT COUNT(*) FROM prompt_cache WHERE created_at < ?",
            'generation_results': "SELECT COUNT(*) FROM generation_results WHERE created_at < ?",
            'generation_tasks': "SELECT COUNT(*) FROM generation_tasks WHERE created_at < ? AND status IN ('SUCCESS', 'FAILED')",
            'multiphoto_items': """
                SELECT COUNT(*) FROM multiphoto_items 
                WHERE set_id IN (SELECT id FROM multiphoto_sets WHERE created_at < ?)
            """,
            'multiphoto_sets': "SELECT COUNT(*) FROM multiphoto_sets WHERE created_at < ?",
            'reference_images': "SELECT COUNT(*) FROM reference_images WHERE uploaded_at < ? AND is_active = 0",
        }

        for table, sql in tables.items():
            cursor.execute(sql, (cutoff,))
            count = cursor.fetchone()[0]
            print(f"   {table}: {count} 条")

        # 统计文件
        file_paths = self._get_files_to_delete(cutoff)
        total_size = sum(os.path.getsize(p) for p in file_paths if os.path.exists(p))
        print(f"\n   本地文件: {len(file_paths)} 个 (共 {self._format_size(total_size)})")

        print(f"\n💡 实际删除请运行: python3 scripts/cleanup_media.py --days {days}")

        return {'tables': tables, 'files_count': len(file_paths), 'files_size': total_size}

    def _format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description='HonnyMedia 清理脚本')
    parser.add_argument('--days', type=int, default=30, help='保留天数（默认 30）')
    parser.add_argument('--dry-run', action='store_true', help='仅预览不删除')
    parser.add_argument('--verbose', action='store_true', help='显示详细信息')
    args = parser.parse_args()

    cleaner = MediaCleaner()

    if args.dry_run:
        cleaner.dry_run(args.days)
    else:
        if args.verbose:
            print(f"🧹 保留天数: {args.days} 天")
            print(f"🧹 截止时间: {datetime.now() - timedelta(days=args.days)}\n")

        cleaner.cleanup(args.days)


if __name__ == '__main__':
    main()