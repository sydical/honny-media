#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 飞书交互命令处理器
版本：v1.0
日期：2026-05-28
职责：解析飞书用户消息，触发需求确认/拒绝/进度查询等操作
"""

import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.demand_manager import DemandManager


FEISHU_USER_ID = "ou_dee9a369b1a5b47ffaf349a005001284"


class FeishuCommandHandler:
    """飞书命令处理器"""

    # 命令模式（按优先级排序）
    COMMAND_PATTERNS = [
        # 确认指令：确认 / 确认ABC123 / confirmABC123
        (r'^确认(\w{6})$', 'confirm'),
        (r'^确认$', 'confirm_prompt'),  # 单独"确认"需要二次确认
        (r'^confirm(\w{6})$', 'confirm'),
        # 拒绝指令
        (r'^拒绝$', 'reject'),
        (r'^reject$', 'reject'),
        (r'^取消$', 'cancel'),
        # 进度查询
        (r'^进度$', 'progress'),
        (r'^status$', 'progress'),
        # 帮助
        (r'^帮助$', 'help'),
        (r'^help$', 'help'),
    ]

    def __init__(self, db_manager=None):
        self.demand_manager = DemandManager(db_manager)

    def handle(self, text: str, user_id: str = None):
        """处理用户消息，返回响应消息

        Args:
            text: 用户发送的原始文本
            user_id: 用户 ID（用于权限校验，可选）

        Returns:
            str: 回复文本
        """
        text = text.strip()

        # 忽略空消息
        if not text:
            return None

        # 忽略纯数字（可能是确认码太长被截断等）
        if text.isdigit():
            return "⚠️ 未识别命令。回复【帮助】查看可用命令。"

        # 尝试匹配命令
        for pattern, cmd in self.COMMAND_PATTERNS:
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                token = m.group(1) if m.lastindex else None
                return self._dispatch(cmd, token, user_id)

        # 未匹配到任何命令，检查是否像确认码
        if len(text) == 6 and text.isalnum():
            return self._dispatch('confirm', text, user_id)

        return None  # 未识别，不回复

    def _dispatch(self, cmd: str, token: str = None, user_id: str = None):
        """分发命令"""
        if cmd == 'confirm':
            return self._cmd_confirm(token)
        elif cmd == 'confirm_prompt':
            return "📋 请回复您的确认码（6位），例如：【确认ABC123】"
        elif cmd == 'reject':
            return self._cmd_reject(token)
        elif cmd == 'cancel':
            return "ℹ️ 取消操作请回复您的确认码，例如：【拒绝】后输入确认码"
        elif cmd == 'progress':
            return self._cmd_progress(user_id)
        elif cmd == 'help':
            return self._cmd_help()
        return "⚠️ 未知命令"

    def _cmd_confirm(self, token: str):
        """确认执行"""
        if not token:
            return "⚠️ 请输入确认码，例如：【确认ABC123】"

        result = self.demand_manager.confirm(token)
        if result['success']:
            demand_id = result['demand_id']
            demand, tasks = self.demand_manager.get_progress(demand_id)
            total = len(tasks)
            return (
                f"✅ 需求 {demand_id} 已确认，开始执行！\n"
                f"📋 共 {total} 个任务，后台执行中...\n"
                f"⏳ 完成后自动通知，请稍候"
            )
        else:
            return f"❌ 确认失败：{result['message']}"

    def _cmd_reject(self, token: str):
        """拒绝方案"""
        if not token:
            return "⚠️ 请输入确认码，例如：【拒绝ABC123】"

        result = self.demand_manager.reject(token)
        if result['success']:
            return "✅ 方案已拒绝，需求已取消。"
        else:
            return f"❌ 拒绝失败：{result['message']}"

    def _cmd_progress(self, user_id: str = None):
        """查询进度"""
        # 查找最新的 EXECUTING 需求
        conn = self.demand_manager.db.conn
        cur = conn.execute(
            "SELECT id FROM demands WHERE plan_status='CONFIRMED' ORDER BY confirmed_at DESC LIMIT 1"
        )
        row = cur.fetchone()

        if not row:
            return "ℹ️ 当前没有正在执行的需求。"

        demand_id = row[0]
        return self.demand_manager.format_progress(demand_id)

    def _cmd_help(self):
        """帮助"""
        return (
            "📖 HonnyMedia 命令帮助\n\n"
            "【生成需求】\n"
            "  直接发送文字需求即可，"
            "例如：生成一套4图，时尚穿搭\n\n"
            "【确认执行】\n"
            "  收到确认码后，回复：【确认ABC123】\n\n"
            "【拒绝方案】\n"
            "  回复：【拒绝ABC123】\n\n"
            "【查询进度】\n"
            "  回复：【进度】\n\n"
            "【获取帮助】\n"
            "  回复：【帮助】"
        )


def format_confirm_card(demand_id: int, confirm_token: str, plan_summary: str, expires_minutes: int = 30):
    """格式化飞书确认卡片内容

    Args:
        demand_id: 需求ID
        confirm_token: 确认码
        plan_summary: 方案摘要（已格式化）
        expires_minutes: 有效期（分钟）

    Returns:
        str: 飞书卡片文本
    """
    lines = [
        "📋 执行方案已生成",
        "─" * 30,
        plan_summary,
        "─" * 30,
        f"✅ 确认码：【{confirm_token}】",
        f"⏱️ 有效期：{expires_minutes} 分钟",
        "",
        "回复【确认" + confirm_token + "】执行",
        "回复【拒绝" + confirm_token + "】取消",
    ]
    return '\n'.join(lines)


def format_progress_card(demand_id: int, tasks: list, status: str):
    """格式化飞书进度卡片

    Args:
        demand_id: 需求ID
        tasks: 任务列表
        status: demand 整体状态

    Returns:
        str: 飞书卡片文本
    """
    lines = [f"📋 需求 {demand_id} 进度：\n"]

    for task in tasks:
        emoji = {'QUEUED': '⏳', 'RUNNING': '🔄', 'SUCCESS': '✅', 'FAILED': '❌'}.get(task['status'], '?')
        lines.append(f"[{task['task_no']}/{len(tasks)}] {task['workflow_type']} → {task['status']} {emoji}")

        if task['status'] == 'FAILED' and task.get('error_message'):
            lines.append(f"   原因：{task['error_message']}")

        # 加上结果链接
        if task['status'] == 'SUCCESS' and task.get('result_data'):
            try:
                import json
                result_data = json.loads(task['result_data'])
            except Exception:
                result_data = task.get('result_data')
            if isinstance(result_data, dict):
                local_path = result_data.get('local_path')
                if local_path and local_path.startswith('/root/.openclaw/'):
                    url = local_path.replace('/root/.openclaw/', 'http://43.163.99.99/')
                    lines.append(f"   🔗 {url}")

    if status == 'SUCCESS':
        lines.append(f"\n🎉 全部完成！")
    elif status == 'FAILED':
        lines.append(f"\n❌ 需求执行失败")

    return '\n'.join(lines)


if __name__ == '__main__':
    handler = FeishuCommandHandler()

    # 测试用例
    test_cases = [
        "确认ABC123",
        "拒绝ABC123",
        "进度",
        "帮助",
        "生成一套4图",
    ]

    print("=== 命令处理测试 ===\n")
    for text in test_cases:
        result = handler.handle(text)
        print(f"输入：「{text}」")
        if result:
            print(f"回复：{result}")
        else:
            print(f"回复：（无响应）")
        print()