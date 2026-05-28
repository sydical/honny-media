#!/usr/bin/env python3
import sys, sqlite3, os

sys.path.insert(0, '/root/.openclaw/skills/honny-media')

db_path = os.path.expanduser('~/.openclaw/workspace-companion2/data/honny-media/honny.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

caches = conn.execute("SELECT cache_key, workflow_type, status, task_id, created_at FROM cache WHERE workflow_type = 'video' ORDER BY created_at DESC LIMIT 10").fetchall()
print("Cache entries:")
for c in caches:
    print(dict(c))

# Also check generate_tasks
tasks = conn.execute("SELECT id, workflow_type, status, task_id, created_at FROM generate_tasks WHERE workflow_type = 'video' ORDER BY created_at DESC LIMIT 5").fetchall()
print("\nGenerate tasks:")
for t in tasks:
    print(dict(t))