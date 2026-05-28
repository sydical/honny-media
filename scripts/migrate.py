#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia Phase 5: 数据迁移脚本
版本：v1.1
日期：2026-05-19

将旧缓存数据迁移到新的 SQLite 数据库

旧缓存格式 (cache_index.json):
{
  "md5_hash": {
    "status": "SUCCESS|RUNNING|PENDING|FAILED",
    "task_id": "...",
    "prompt_prefix": "...",
    "reference_url": "..."
  },
  ...
}
"""

import os
import sys
import json
import hashlib
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.db_manager import HonnyDBManager


class HonnyMigrator:
    """数据迁移器"""
    
    def __init__(self):
        self.db = HonnyDBManager()
        self.stats = {
            'cache_entries': 0,
            'tasks': 0,
            'references': 0,
            'errors': []
        }
    
    def migrate_from_old_cache(self, cache_file):
        """从旧缓存文件迁移数据"""
        if not os.path.exists(cache_file):
            print(f"⚠️ 缓存文件不存在: {cache_file}")
            return
        
        print(f"📂 开始迁移: {cache_file}")
        
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        # cache_data 格式: {"md5_hash": {"status": ..., "task_id": ..., ...}}
        for cache_key, entry in cache_data.items():
            try:
                self._migrate_entry(cache_key, entry)
                self.stats['cache_entries'] += 1
            except Exception as e:
                self.stats['errors'].append(f"{cache_key}: {str(e)}")
        
        print(f"\n✅ 迁移完成!")
        print(f"   缓存条目: {self.stats['cache_entries']}")
        print(f"   任务数: {self.stats['tasks']}")
        
        if self.stats['errors']:
            print(f"   错误数: {len(self.stats['errors'])}")
            for err in self.stats['errors'][:5]:
                print(f"     - {err}")
    
    def _migrate_entry(self, cache_key, entry):
        """迁移单个缓存条目"""
        status = entry.get('status', 'UNKNOWN')
        task_id = entry.get('task_id', '')
        prompt = entry.get('prompt_prefix', '')
        reference_url = entry.get('reference_url', '')
        
        # 确定工作流类型（从prompt_prefix推断）
        workflow_type = self._detect_workflow(prompt)
        
        # 计算过期时间（30天后）
        expires_at = datetime.now() + timedelta(days=30)
        
        # 插入缓存
        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO prompt_cache
            (prompt_hash, workflow_type, prompt, reference_url, status, task_id,
             hit_count, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cache_key,
            workflow_type,
            prompt,
            reference_url,
            status,
            task_id,
            0,  # hit_count
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            expires_at.isoformat()
        ))
        
        # 如果有task_id，创建任务记录
        if task_id and not task_id.startswith('cached_'):
            cursor.execute("""
                INSERT OR IGNORE INTO generation_tasks
                (task_id, workflow_type, prompt, reference_url, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, workflow_type, prompt, reference_url, status, datetime.now().isoformat()))
            
            if cursor.rowcount > 0:
                self.stats['tasks'] += 1
        
        self.db.conn.commit()
    
    def _detect_workflow(self, prompt):
        """检测工作流类型"""
        if not prompt:
            return 'photo'
        
        prompt_lower = prompt.lower()
        
        if 'multiphoto' in prompt_lower or '视频' in prompt_lower:
            return 'multiphoto'
        if 'video' in prompt_lower or '生成视频' in prompt_lower:
            return 'video'
        return 'photo'
    
    def migrate_old_reference(self, file_path, remote_url, user_id='default'):
        """迁移旧参考图"""
        ref_id = self.db.save_reference(file_path, remote_url, user_id)
        self.stats['references'] += 1
        return ref_id
    
    def verify_migration(self):
        """验证迁移完整性"""
        print("\n📊 迁移验证:")
        print("-" * 40)
        
        cursor = self.db.conn.cursor()
        
        # 统计缓存
        cursor.execute("SELECT COUNT(*) FROM prompt_cache")
        cache_count = cursor.fetchone()[0]
        print(f"  ✅ prompt_cache: {cache_count} 条")
        
        # 统计任务
        cursor.execute("SELECT COUNT(*) FROM generation_tasks")
        task_count = cursor.fetchone()[0]
        print(f"  ✅ generation_tasks: {task_count} 条")
        
        # 统计参考图
        cursor.execute("SELECT COUNT(*) FROM reference_images")
        ref_count = cursor.fetchone()[0]
        print(f"  ✅ reference_images: {ref_count} 条")
        
        # 按工作流类型统计
        cursor.execute("""
            SELECT workflow_type, status, COUNT(*) 
            FROM prompt_cache 
            GROUP BY workflow_type, status
        """)
        print("\n  📋 按类型统计:")
        for row in cursor.fetchall():
            print(f"     - {row[0]}/{row[1]}: {row[2]}")
        
        return cache_count > 0 or task_count > 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='HonnyMedia 数据迁移工具')
    parser.add_argument('--cache-file', help='旧缓存文件路径')
    parser.add_argument('--verify', action='store_true', help='验证迁移')
    parser.add_argument('--stats', action='store_true', help='显示统计')
    
    args = parser.parse_args()
    
    migrator = HonnyMigrator()
    
    if args.cache_file:
        migrator.migrate_from_old_cache(args.cache_file)
    
    if args.verify:
        migrator.verify_migration()
    
    if args.stats:
        stats = migrator.db.get_stats()
        print("\n📊 数据库统计:")
        print("-" * 40)
        print(f"  工作流统计:")
        for ws in stats.get('workflow_stats', []):
            print(f"    {ws['workflow_type']}: {ws['success']}/{ws['total']}")
        print(f"  缓存总数: {stats['cache_total']}")
        print(f"  缓存命中: {stats['cache_hits']}")
    
    if not any([args.cache_file, args.verify, args.stats]):
        parser.print_help()


if __name__ == '__main__':
    main()