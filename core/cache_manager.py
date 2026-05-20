#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 缓存管理模块
版本：v1.0
日期：2026-05-18
"""

import os
import sys
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.db_manager import get_db_manager


class CacheManager:
    """缓存管理器 - 封装缓存相关操作"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager or get_db_manager()
    
    def make_cache_key(self, workflow_type, prompt, reference_url):
        """生成缓存键"""
        content = f"{workflow_type}:{prompt}:{reference_url}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, workflow_type, prompt, reference_url):
        """获取缓存"""
        return self.db.get_cache(workflow_type, prompt, reference_url)
    
    def set(self, workflow_type, prompt, reference_url, status='PENDING', task_id=None):
        """设置缓存"""
        return self.db.set_cache(workflow_type, prompt, reference_url, status, task_id)
    
    def update_success(self, cache_key, result_id=None):
        """更新缓存为成功"""
        self.db.update_cache_success(cache_key, result_id)
    
    def update_running(self, cache_key, task_id):
        """更新缓存为运行中"""
        self.db.update_cache_running(cache_key, task_id)
    
    def delete(self, cache_key):
        """删除缓存"""
        self.db.delete_cache(cache_key)
    
    def increment_hit(self, cache_key):
        """增加命中次数"""
        self.db.increment_cache_hit(cache_key)
    
    def get_or_wait(self, workflow_type, prompt, reference_url, api_key, max_wait=300):
        """获取缓存或等待任务完成
        
        Args:
            workflow_type: 工作流类型
            prompt: 提示词
            reference_url: 参考图URL
            api_key: API密钥（用于等待）
            max_wait: 最大等待时间（秒）
        
        Returns:
            tuple: (hit_cache, wait_result)
                - hit_cache: 缓存命中返回结果
                - wait_result: 等待完成后的结果（如果需要等待）
        """
        cache = self.get(workflow_type, prompt, reference_url)
        
        if not cache:
            return None, None
        
        if cache['status'] == 'SUCCESS':
            return cache, None
        
        if cache['status'] == 'RUNNING':
            task_id = cache.get('task_id')
            if not task_id:
                self.delete(self.make_cache_key(workflow_type, prompt, reference_url))
                return None, None
            
            # 等待任务完成
            from utils.runninghub import RunningHubClient
            client = RunningHubClient(api_key)
            
            wait_result = client.wait_for_task(task_id, max_wait=max_wait)
            return None, wait_result
        
        if cache['status'] == 'FAILED':
            # 删除失败的缓存
            cache_key = self.make_cache_key(workflow_type, prompt, reference_url)
            self.delete(cache_key)
            return None, None
        
        return None, None
    
    def cleanup_expired(self, days=30):
        """清理过期缓存"""
        return self.db.cleanup_expired(days)
    
    def get_stats(self):
        """获取缓存统计"""
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            SELECT 
                workflow_type,
                COUNT(*) as total,
                SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(hit_count) as total_hits
            FROM prompt_cache
            GROUP BY workflow_type
        """)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def main():
    """缓存管理CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='HonnyMedia 缓存管理')
    subparsers = parser.add_subparsers(dest='command')
    
    # stats 子命令
    stats_parser = subparsers.add_parser('stats', help='查看缓存统计')
    
    # cleanup 子命令
    cleanup_parser = subparsers.add_parser('cleanup', help='清理过期缓存')
    cleanup_parser.add_argument('--days', type=int, default=30, help='过期天数')
    
    args = parser.parse_args()
    
    cache_mgr = CacheManager()
    
    if args.command == 'stats':
        stats = cache_mgr.get_stats()
        print("\n📊 缓存统计:")
        print("-" * 60)
        for s in stats:
            print(f"  {s['workflow_type']}: {s['success']}/{s['total']} 成功, {s['total_hits']} 次命中")
        print("-" * 60)
    
    elif args.command == 'cleanup':
        result = cache_mgr.cleanup_expired(args.days)
        print(f"\n🧹 清理完成: 删除 {result['expired_cache']} 条过期缓存")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()