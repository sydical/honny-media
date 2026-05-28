#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 需求管理器
版本：v1.0
日期：2026-05-28
职责：需求的 CRUD + 全生命周期管理（创建/确认/拒绝/查询）
"""

import os
import sys
import json
import random
import string
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.demand_parser import DemandParser
from core.prompt_builder import PromptBuilder


def _generate_token(length=6):
    """生成随机确认码"""
    chars = string.ascii_uppercase + string.digits
    # 排除容易混淆的字符
    chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    return ''.join(random.choice(chars) for _ in range(length))


class DemandManager:
    """需求管理器"""

    def __init__(self, db_manager=None):
        if db_manager is None:
            from db.db_manager import get_db_manager
            self.db = get_db_manager()
        else:
            self.db = db_manager

        self.parser = DemandParser()
        self.prompt_builder = PromptBuilder(self.db)

    # ==================== 核心 API ====================

    def create_demand(self, raw_prompt, reference_path=None, character_profile_id=None):
        """创建需求（解析后生成方案，等待确认）

        Args:
            raw_prompt: 用户原始需求
            reference_path: 参考图路径（可选）
            character_profile_id: 人物形象配置ID（可选）

        Returns:
            dict: { demand_id, confirm_token, plan_summary }
        """
        # 1. 解析需求，拆解任务
        raw_tasks = self.parser.parse(raw_prompt, reference_path)

        # 2. 构建任务方案（拼接提示词 + 解析参考图URL）
        tasks_plan = []
        prev_result = None
        for i, raw_task in enumerate(raw_tasks, 1):
            task_no = i
            result = self.prompt_builder.build(
                user_prompt=raw_task['prompt'],
                character_profile_id=character_profile_id,
                reference_path=raw_task.get('reference_path'),
                task_no=task_no,
                prev_task_result=prev_result,
            )
            tasks_plan.append({
                'task_no': task_no,
                'workflow_type': raw_task['workflow_type'],
                'prompt': result['final_prompt'],
                'reference_url': result['reference_url'],
                'reference_path': result['reference_path'],
                'character_profile': result['character_profile'],
                'is_ref_generator': raw_task.get('is_ref_generator', False),
                'status': 'QUEUED',
            })

            # 如果当前任务是参考图生成任务，保存结果路径供下一任务使用
            if raw_task.get('is_ref_generator'):
                # 预分配一个占位结果（实际在执行时更新）
                prev_result = {'local_path': None}

        # 3. 生成确认码
        confirm_token = _generate_token()
        confirm_expires = datetime.now() + timedelta(minutes=30)

        # 4. 保存到 demands 表
        workflow_types = list(set(t['workflow_type'] for t in tasks_plan))
        summary_type = '+'.join(workflow_types) if len(workflow_types) > 1 else workflow_types[0]

        conn = self.db.conn
        cur = conn.execute('''
            INSERT INTO demands (raw_prompt, workflow_type, reference_path, status, plan_status,
                               total_tasks, confirm_token, confirm_expires_at, created_at)
            VALUES (?, ?, ?, 'PENDING', 'PENDING', ?, ?, ?, ?)
        ''', (raw_prompt, summary_type, reference_path, len(tasks_plan),
              confirm_token, confirm_expires.isoformat(), datetime.now().isoformat()))
        demand_id = cur.lastrowid
        conn.commit()

        # 5. 保存到 demand_tasks 表
        for task in tasks_plan:
            conn.execute('''
                INSERT INTO demand_tasks (demand_id, task_no, workflow_type, prompt,
                                         reference_path, reference_url, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (demand_id, task['task_no'], task['workflow_type'], task['prompt'],
                  task['reference_path'], task['reference_url'], 'QUEUED'))
        conn.commit()

        # 6. 生成方案摘要
        profile = tasks_plan[0].get('character_profile') or {}
        plan_summary = self.prompt_builder.format_card(tasks_plan, profile)

        return {
            'demand_id': demand_id,
            'confirm_token': confirm_token,
            'plan_summary': plan_summary,
            'tasks_plan': tasks_plan,
            'expires_minutes': 30,
        }

    def confirm(self, confirm_token):
        """用户确认执行

        Args:
            confirm_token: 确认码

        Returns:
            dict: { success, demand_id, message }
        """
        conn = self.db.conn

        # 查询 demand
        cur = conn.execute(
            'SELECT * FROM demands WHERE confirm_token=? AND plan_status=?',
            (confirm_token, 'PENDING')
        )
        demand = cur.fetchone()

        if not demand:
            return {'success': False, 'message': '确认码无效或已过期'}

        demand = dict(demand)

        # 检查是否过期
        expires_at = demand.get('confirm_expires_at')
        if expires_at:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if datetime.now() > expires_at:
                return {'success': False, 'message': '确认码已过期，请重新提交需求'}

        # 检查是否已确认过
        if demand['plan_status'] == 'CONFIRMED':
            return {'success': False, 'message': '该需求已确认过，请勿重复确认'}

        # 更新状态：PENDING → CONFIRMED → EXECUTING
        conn.execute(
            'UPDATE demands SET plan_status=?, status=?, confirmed_at=?, updated_at=? WHERE id=?',
            ('CONFIRMED', 'EXECUTING', datetime.now().isoformat(), datetime.now().isoformat(), demand['id'])
        )
        conn.commit()

        return {
            'success': True,
            'demand_id': demand['id'],
            'message': f'需求已确认，开始执行（{demand["total_tasks"]}个任务）',
        }

    def reject(self, confirm_token):
        """用户拒绝方案

        Args:
            confirm_token: 确认码

        Returns:
            dict: { success, message }
        """
        conn = self.db.conn

        cur = conn.execute(
            'SELECT * FROM demands WHERE confirm_token=? AND plan_status=?',
            (confirm_token, 'PENDING')
        )
        demand = cur.fetchone()

        if not demand:
            return {'success': False, 'message': '确认码无效或方案已过期'}

        demand = dict(demand)

        conn.execute(
            'UPDATE demands SET plan_status=?, status=?, updated_at=? WHERE id=?',
            ('REJECTED', 'FAILED', datetime.now().isoformat(), demand['id'])
        )
        conn.commit()

        return {
            'success': True,
            'message': '方案已拒绝，需求已取消',
        }

    def get_demand(self, demand_id):
        """获取需求详情"""
        conn = self.db.conn
        cur = conn.execute('SELECT * FROM demands WHERE id=?', (demand_id,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def get_demand_tasks(self, demand_id):
        """获取需求的所有任务"""
        conn = self.db.conn
        cur = conn.execute(
            'SELECT * FROM demand_tasks WHERE demand_id=? ORDER BY task_no',
            (demand_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_progress(self, demand_id):
        """获取需求进度"""
        demand = self.get_demand(demand_id)
        if not demand:
            return None, []
        tasks = self.get_demand_tasks(demand_id)
        return demand, tasks

    def get_pending_demands(self):
        """获取所有待执行需求（plan_status=CONFIRMED）"""
        conn = self.db.conn
        cur = conn.execute(
            "SELECT * FROM demands WHERE plan_status='CONFIRMED' AND status='EXECUTING' ORDER BY confirmed_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_next_queued_task(self):
        """获取下一个待执行任务（按 demand_id ASC, task_no ASC）"""
        conn = self.db.conn

        # 找 CONFIRMED 状态下最早的任务
        cur = conn.execute('''
            SELECT dt.*, d.id as demand_id, d.status as demand_status, d.plan_status
            FROM demand_tasks dt
            JOIN demands d ON dt.demand_id = d.id
            WHERE d.plan_status = 'CONFIRMED'
              AND d.status = 'EXECUTING'
              AND dt.status = 'QUEUED'
            ORDER BY d.id ASC, dt.task_no ASC
            LIMIT 1
        ''')
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def update_task_status(self, task_id, status, result_data=None, error_message=None):
        """更新任务状态"""
        conn = self.db.conn

        completed_at = datetime.now().isoformat() if status in ('SUCCESS', 'FAILED') else None

        if result_data:
            result_json = json.dumps(result_data, ensure_ascii=False)
        else:
            result_json = None

        conn.execute('''
            UPDATE demand_tasks
            SET status=?, completed_at=?, result_data=?, error_message=?
            WHERE id=?
        ''', (status, completed_at, result_json, error_message, task_id))
        conn.commit()

        # 如果是 SUCCESS，更新 demand 进度
        if status == 'SUCCESS':
            self._update_demand_progress_by_task(task_id)

    def update_task_retry(self, task_id):
        """任务失败，重试计数+1"""
        conn = self.db.conn
        conn.execute(
            'UPDATE demand_tasks SET retry_count=retry_count+1 WHERE id=?',
            (task_id,)
        )
        conn.commit()

    def set_task_task_id(self, task_id, runninghub_task_id):
        """更新 RunningHub task_id"""
        conn = self.db.conn
        conn.execute(
            'UPDATE demand_tasks SET task_id=? WHERE id=?',
            (runninghub_task_id, task_id)
        )
        conn.commit()

    def get_demand_by_task_id(self, task_id):
        """根据 RunningHub task_id 查找 demand"""
        conn = self.db.conn
        cur = conn.execute('''
            SELECT d.* FROM demands d
            JOIN demand_tasks dt ON d.id = dt.demand_id
            WHERE dt.task_id = ?
        ''', (task_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_prev_task_result(self, demand_id, task_no):
        """获取前序任务的结果（用于参考图引用）"""
        if task_no <= 1:
            return None

        conn = self.db.conn
        cur = conn.execute('''
            SELECT dt.* FROM demand_tasks
            WHERE demand_id=? AND task_no=? AND status='SUCCESS'
        ''', (demand_id, task_no - 1))
        row = cur.fetchone()
        if not row:
            return None

        result = dict(row)
        if result.get('result_data'):
            try:
                result['result_data'] = json.loads(result['result_data'])
            except Exception:
                pass
        return result

    def _update_demand_progress_by_task(self, task_id):
        """根据任务完成情况更新 demand 进度"""
        conn = self.db.conn

        # 找到该任务所属的 demand
        cur = conn.execute(
            'SELECT demand_id FROM demand_tasks WHERE id=?', (task_id,)
        )
        row = cur.fetchone()
        if not row:
            return
        demand_id = row[0]

        # 统计完成数
        cur = conn.execute(
            "SELECT COUNT(*) FROM demand_tasks WHERE demand_id=? AND status='SUCCESS'",
            (demand_id,)
        )
        completed = cur.fetchone()[0]

        # 查总数
        cur = conn.execute(
            'SELECT total_tasks FROM demands WHERE id=?', (demand_id,)
        )
        total = cur.fetchone()[0]

        # 更新进度
        if completed >= total:
            new_status = 'SUCCESS'
            completed_at = datetime.now().isoformat()
        else:
            new_status = 'EXECUTING'
            completed_at = None

        conn.execute('''
            UPDATE demands SET completed_tasks=?, status=?, completed_at=?, updated_at=? WHERE id=?
        ''', (completed, new_status, completed_at, datetime.now().isoformat(), demand_id))
        conn.commit()

    def format_progress(self, demand_id):
        """格式化进度消息"""
        demand, tasks = self.get_progress(demand_id)
        if not demand:
            return '未知需求'

        lines = [f"📋 需求 {demand_id} 进度：\n"]

        for task in tasks:
            status_emoji = {
                'QUEUED': '⏳',
                'RUNNING': '🔄',
                'SUCCESS': '✅',
                'FAILED': '❌',
            }.get(task['status'], '❓')

            lines.append(
                f"[{task['task_no']}/{len(tasks)}] {task['workflow_type']} → {task['status']} {status_emoji}"
            )

            if task['status'] == 'FAILED' and task.get('error_message'):
                lines.append(f"   错误：{task['error_message']}")

        if demand['status'] == 'SUCCESS':
            lines.append(f"\n🎉 全部完成！")

        return '\n'.join(lines)


if __name__ == '__main__':
    from db.db_manager import HonnyDBManager
    db = HonnyDBManager()
    mgr = DemandManager(db)

    print("=== 测试创建需求 ===")
    result = mgr.create_demand("生成一套4图，时尚穿搭")
    print(f"demand_id: {result['demand_id']}")
    print(f"confirm_token: {result['confirm_token']}")
    print(f"plan_summary:\n{result['plan_summary']}")

    print("\n=== 测试确认 ===")
    confirm_result = mgr.confirm(result['confirm_token'])
    print(f"confirm: {confirm_result}")

    print("\n=== 测试进度查询 ===")
    progress = mgr.format_progress(result['demand_id'])
    print(progress)

    print("\n=== 测试拒绝 ===")
    result2 = mgr.create_demand("生成视频")
    reject_result = mgr.reject(result2['confirm_token'])
    print(f"reject: {reject_result}")