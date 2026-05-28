#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 需求解析器
版本：v1.0
日期：2026-05-28
职责：解析用户需求，拆解为可执行任务列表（不执行）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.workflow_dispatcher import detect_workflow, WORKFLOW_IDS


WORKFLOW_KEYWORDS = {
    'video': ['视频', '生成视频', '做视频', '拍视频', 'wanvideo', 'wan video'],
    'multiphoto': ['套装', '4图', '4宫格', '宫格', '多图', '套图', '四图', '多张照片', '套图'],
}


class DemandParser:
    """解析用户需求，拆解为可执行任务列表"""

    def parse(self, raw_prompt, reference_path=None):
        """解析需求，返回任务列表

        Args:
            raw_prompt: 用户原始需求（自然语言）
            reference_path: 用户提供的参考图路径（可选）

        Returns:
            List[dict]: 任务列表，每个任务含：
                workflow_type, prompt, reference_path
        """
        prompt_lower = raw_prompt.lower()

        # 检测工作流类型
        workflow = self._detect_workflow(prompt_lower)

        tasks = []

        if workflow == 'video':
            if not reference_path:
                # 无参考图 → 拆分为 photo + video（photo 先生成参考图）
                tasks.append({
                    'workflow_type': 'photo',
                    'prompt': raw_prompt,
                    'reference_path': reference_path,
                    'is_ref_generator': True,  # 标记为参考图生成任务
                })
                # video 依赖 photo 完成后，拿 photo 的结果作为参考图
                tasks.append({
                    'workflow_type': 'video',
                    'prompt': raw_prompt,
                    'reference_path': None,  # 等 photo 完成后自动填充
                    'depends_on_prev': True,
                })
            else:
                # 有参考图 → 1个 video 任务
                tasks.append({
                    'workflow_type': 'video',
                    'prompt': raw_prompt,
                    'reference_path': reference_path,
                })
        elif workflow == 'multiphoto':
            tasks.append({
                'workflow_type': 'multiphoto',
                'prompt': raw_prompt,
                'reference_path': reference_path,
            })
        else:
            # 默认 photo
            tasks.append({
                'workflow_type': 'photo',
                'prompt': raw_prompt,
                'reference_path': reference_path,
            })

        return tasks

    def _detect_workflow(self, prompt_lower):
        """检测工作流类型"""
        # 优先检查命令前缀
        if prompt_lower.startswith('/video'):
            return 'video'
        elif prompt_lower.startswith('/multiphoto'):
            return 'multiphoto'
        elif prompt_lower.startswith('/photo'):
            return 'photo'

        # 检查关键词
        for kw in WORKFLOW_KEYWORDS['video']:
            if kw in prompt_lower:
                return 'video'

        for kw in WORKFLOW_KEYWORDS['multiphoto']:
            if kw in prompt_lower:
                return 'multiphoto'

        # 默认 photo
        return 'photo'

    def get_summary(self, tasks):
        """生成任务摘要（用于确认卡片）"""
        lines = []
        for i, task in enumerate(tasks, 1):
            emoji = {
                'photo': '📸',
                'multiphoto': '🖼️',
                'video': '🎬',
            }.get(task['workflow_type'], '📋')

            ref_info = ''
            if task.get('reference_path'):
                ref_name = os.path.basename(task['reference_path'])
                ref_info = f'\n   参考图：{ref_name}'
            elif task.get('depends_on_prev'):
                ref_info = '\n   参考图：待上游任务生成'

            lines.append(f"{emoji} 任务{i}：{task['workflow_type']}{ref_info}")

        return '\n'.join(lines)


if __name__ == '__main__':
    parser = DemandParser()

    # 测试用例
    test_cases = [
        ("生成一张照片，时尚穿搭", None),
        ("生成一套4图，时尚穿搭", None),
        ("生成视频，时尚模特走秀", None),
        ("生成4图后做视频", None),
        ("生成照片", "/root/photo.jpg"),
    ]

    for prompt, ref_path in test_cases:
        tasks = parser.parse(prompt, ref_path)
        print(f"\n📝 需求：{prompt}")
        if ref_path:
            print(f"   参考图：{ref_path}")
        for i, t in enumerate(tasks, 1):
            print(f"   任务{i}：{t['workflow_type']} - is_ref_gen={t.get('is_ref_generator', False)}")
        print(f"   摘要：\n{parser.get_summary(tasks)}")