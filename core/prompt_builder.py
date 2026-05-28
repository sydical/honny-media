#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 提示词构造器
版本：v1.0
日期：2026-05-28
职责：将用户提示词与默认人物形象配置拼接，生成完整的最终提示词
"""

import os


# 默认人物形象配置（当数据库无数据时使用）
DEFAULT_CHARACTER_PROFILE = {
    "name": "默认亚洲女性",
    "description": "中国28岁美女，曼妙身姿，曲线玲珑，凹凸有致，皮肤细腻，精致妆容",
    "height": "163cm/49kg，三围86/62/86cm，腿长98cm，腰臀比0.72，紧致健身沙漏身材，蜜桃臀，纤细长腿",
    "prompt_template": "{description} {height} {user_prompt}",
    "default_ref_path": "/root/.openclaw/workspace-companion2/avatar.jpg",
    "is_default": 1,
}


class PromptBuilder:
    """提示词构造器：拼接用户提示词 + 人物形象配置 + 参考图"""

    def __init__(self, db_manager=None):
        self.db = db_manager
        self._default_profile = None

    def build(self, user_prompt, character_profile_id=None, reference_path=None, task_no=None, prev_task_result=None):
        """构造最终提示词和参考图 URL

        Args:
            user_prompt: 用户原始需求
            character_profile_id: 人物形象配置ID（None则用默认）
            reference_path: 用户指定的参考图路径（可选）
            task_no: 当前任务序号（用于判断是否引用前序任务的输出）
            prev_task_result: 前序任务的结果数据（dict，含 local_path）

        Returns:
            dict: {
                'final_prompt': str,
                'reference_url': str,
                'reference_path': str,
                'character_profile': dict,
                'workflow_type': str
            }
        """
        # 1. 加载人物形象配置
        profile = self._load_profile(character_profile_id)

        # 2. 组合最终提示词
        final_prompt = self._merge_prompt(user_prompt, profile)

        # 3. 解析参考图 URL
        reference_url, reference_path = self._resolve_reference(
            reference_path, profile, task_no, prev_task_result
        )

        return {
            'final_prompt': final_prompt,
            'reference_url': reference_url,
            'reference_path': reference_path,
            'character_profile': profile,
        }

    def _load_profile(self, profile_id=None):
        """加载人物形象配置"""
        # 优先用数据库中的配置
        if self.db:
            profile = self._load_profile_from_db(profile_id)
            if profile:
                return profile

        # 降级到硬编码默认配置
        return self._get_default_profile()

    def _load_profile_from_db(self, profile_id=None):
        """从数据库加载配置"""
        if not self.db:
            return None

        try:
            conn = self.db.conn
            if profile_id:
                cur = conn.execute(
                    'SELECT * FROM character_profiles WHERE id=?', (profile_id,)
                )
            else:
                cur = conn.execute(
                    'SELECT * FROM character_profiles WHERE is_default=1 LIMIT 1'
                )
            row = cur.fetchone()
            if row:
                return dict(row)
        except Exception as e:
            print(f"⚠️ 加载人物形象配置失败: {e}")

        return None

    def _get_default_profile(self):
        """获取硬编码默认配置"""
        if self._default_profile is None:
            self._default_profile = DEFAULT_CHARACTER_PROFILE.copy()
        return self._default_profile

    def _merge_prompt(self, user_prompt, profile):
        """拼接用户提示词和人物形象配置"""
        template = profile.get('prompt_template', '{user_prompt}')

        # 如果模板只含 {user_prompt}，直接返回用户原始 prompt
        if template.strip() == '{user_prompt}':
            return user_prompt

        # 填充模板变量
        final = template.replace('{description}', profile.get('description', ''))
        final = final.replace('{height}', profile.get('height', ''))
        final = final.replace('{user_prompt}', user_prompt)

        # 清理多余空格和换行
        final = ' '.join(final.split())

        return final

    def _resolve_reference(self, reference_path, profile, task_no=None, prev_task_result=None):
        """解析参考图 URL

        策略：
        1. 显式传入了 reference_path → 使用它
        2. task_no > 1（后续任务）且有 prev_task_result → 使用前序任务生成的图
        3. 否则使用默认 avatar.jpg
        """
        from core.reference_manager import ReferenceManager

        # Case 1: 显式指定的参考图
        if reference_path and os.path.exists(reference_path):
            # 转换为 HTTP URL（如果本地路径在 /root/.openclaw/ 下）
            if reference_path.startswith('/root/.openclaw/'):
                relative = reference_path[len('/root/.openclaw/'):]
                http_base = ReferenceManager.LOCAL_HTTP_BASE
                url = f"{http_base}/{relative}"
            else:
                url = reference_path  # 外部路径，不做转换
            return url, reference_path

        # Case 2: 后续任务，引用前序任务的输出
        if task_no and task_no > 1 and prev_task_result:
            result_path = prev_task_result.get('local_path')
            if result_path and os.path.exists(result_path):
                if result_path.startswith('/root/.openclaw/'):
                    relative = result_path[len('/root/.openclaw/'):]
                    http_base = ReferenceManager.LOCAL_HTTP_BASE
                    url = f"{http_base}/{relative}"
                else:
                    url = result_path
                return url, result_path

        # Case 3: 默认 avatar.jpg
        default_ref = profile.get('default_ref_path')
        if not default_ref:
            default_ref = DEFAULT_CHARACTER_PROFILE['default_ref_path']

        if os.path.exists(default_ref):
            if default_ref.startswith('/root/.openclaw/'):
                relative = default_ref[len('/root/.openclaw/'):]
                http_base = ReferenceManager.LOCAL_HTTP_BASE
                url = f"{http_base}/{relative}"
            else:
                url = default_ref
            return url, default_ref

        # Fallback: 直接返回原路径
        return default_ref, default_ref

    def format_card(self, tasks_plan, character_profile):
        """格式化确认卡片内容（纯文本）"""
        lines = ["📋 执行方案已生成\n"]

        # 人物形象摘要
        profile_name = character_profile.get('name', '未知')
        profile_desc = character_profile.get('description', '')
        profile_height = character_profile.get('height', '')
        if profile_desc:
            # 取前50字
            short_desc = profile_desc[:50] + '...' if len(profile_desc) > 50 else profile_desc
            lines.append(f"👤 人物：{profile_name}")
            lines.append(f"   {short_desc}")
        if profile_height:
            lines.append(f"   体型：{profile_height}")

        lines.append("")

        # 任务列表
        for i, task in enumerate(tasks_plan, 1):
            emoji = {'photo': '📸', 'multiphoto': '🖼️', 'video': '🎬'}.get(task['workflow_type'], '📋')
            lines.append(f"{emoji} 任务{i}：{task['workflow_type']}")

            # 提示词（截断显示）
            prompt = task.get('prompt', task.get('final_prompt', ''))
            short_prompt = prompt[:80] + '...' if len(prompt) > 80 else prompt
            lines.append(f"   提示词：{short_prompt}")

            # 参考图
            ref_url = task.get('reference_url', '')
            if ref_url:
                ref_name = os.path.basename(ref_url) if '/' in ref_url else ref_url
                lines.append(f"   参考图：{ref_name}")

            lines.append("")

        return '\n'.join(lines)


if __name__ == '__main__':
    from db.db_manager import HonnyDBManager
    db = HonnyDBManager()
    builder = PromptBuilder(db)

    # 测试
    test_prompt = "生成一套4图，时尚穿搭，优雅气质"

    # Case 1: 无参考图，用默认avatar
    result = builder.build(test_prompt)
    print("=== Case 1: 无参考图 ===")
    print(f"最终提示词：{result['final_prompt'][:100]}...")
    print(f"参考图URL：{result['reference_url']}")
    print(f"人物配置：{result['character_profile']['name']}")

    print()

    # Case 2: 有参考图
    result2 = builder.build(test_prompt, reference_path='/root/photo.jpg')
    print("=== Case 2: 有参考图 ===")
    print(f"参考图URL：{result2['reference_url']}")

    print()

    # Case 3: task_no=2，引用前序结果
    result3 = builder.build(
        "做视频",
        task_no=2,
        prev_task_result={'local_path': '/root/.openclaw/workspace-companion2/data/images/honny_001.jpg'}
    )
    print("=== Case 3: task_no=2 引用前序 ===")
    print(f"参考图URL：{result3['reference_url']}")