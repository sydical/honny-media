#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 数据库迁移脚本
版本：v1.0
日期：2026-05-18
"""

import os
import sqlite3
from datetime import datetime


MIGRATIONS = [
    {
        'version': 1,
        'description': '初始化数据库结构',
        'sql': '''
            -- 这是初始版本的SQL，详见 schema.py
            -- 迁移时直接使用 schema.py 中的 SCHEMA_SQL
        '''
    }
]


class MigrationManager:
    """数据库迁移管理器"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
    
    def connect(self):
        """连接数据库"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
    
    def get_current_version(self):
        """获取当前版本"""
        cursor = self.conn.cursor()
        
        # 检查是否有 version 表
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='schema_version'
        """)
        
        if not cursor.fetchone():
            return 0
        
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row['version'] if row else 0
    
    def set_version(self, version):
        """设置版本"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (?, ?)
        """, (version, datetime.now().isoformat()))
        self.conn.commit()
    
    def run_migrations(self):
        """运行迁移"""
        current_version = self.get_current_version()
        
        print(f"📦 当前数据库版本: {current_version}")
        print(f"📦 目标版本: {len(MIGRATIONS)}")
        
        if current_version >= len(MIGRATIONS):
            print("✅ 数据库已是最新版本")
            return
        
        print("🔄 开始迁移...")
        
        for migration in MIGRATIONS:
            if migration['version'] <= current_version:
                continue
            
            print(f"\n📝 执行迁移 v{migration['version']}: {migration['description']}")
            
            # 执行迁移SQL（如果需要）
            if migration['sql'].strip():
                self.conn.executescript(migration['sql'])
            
            # 更新版本
            self.set_version(migration['version'])
            print(f"✅ 迁移 v{migration['version']} 完成")
        
        print("\n✅ 所有迁移完成")


def migrate(db_path=None):
    """执行迁移"""
    if db_path is None:
        db_path = os.path.expanduser('~/.openclaw/workspace-companion2/data/honny-media/honny.db')
    
    print(f"🔧 开始迁移数据库: {db_path}")
    
    # 确保目录存在
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # 连接数据库
    manager = MigrationManager(db_path)
    manager.connect()
    
    try:
        manager.run_migrations()
    finally:
        manager.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='HonnyMedia 数据库迁移')
    parser.add_argument('--db', help='数据库路径')
    
    args = parser.parse_args()
    migrate(args.db)