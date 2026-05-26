#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 工作流分发器
版本：v1.0
日期：2026-05-18
"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.reference_manager import ReferenceManager
from core.exif_manager import ExifManager


WORKFLOW_KEYWORDS = {
    'video': ['视频', '生成视频', '做视频', '拍视频'],
    'multiphoto': ['套装', '4图', '4宫格', '宫格', '多图', '套图', '四图', '多张照片', '套图'],
    'prompt_photo': ['分镜', '多场景', '多视角', 'prompt-photo'],
}


def detect_workflow(prompt):
    """检测工作流类型"""
    prompt_lower = prompt.lower()
    
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
    
    for kw in WORKFLOW_KEYWORDS.get('prompt_photo', []):
        if kw in prompt_lower:
            return 'prompt_photo'
    
    # 默认photo
    return 'photo'


class WorkflowDispatcher:
    """工作流分发器"""
    
    # 工作流ID映射
    WORKFLOW_IDS = {
        'photo': '2047002838944980993',
        'multiphoto': '2054941025688399873',
        'video': '2048133528671490050',
        'prompt_photo': '2050291848673021954',
    }
    
    def __init__(self, api_key, db_manager):
        self.api_key = api_key
        self.db_manager = db_manager
        self.reference_manager = ReferenceManager(api_key, db_manager)
        self.exif_manager = ExifManager()
    
    def dispatch(self, prompt, reference_path=None, workflow_type=None, **kwargs):
        """分发工作流"""
        # 1. 检测工作流类型
        if workflow_type is None:
            workflow_type = detect_workflow(prompt)
        
        # 2. 获取/上传参考图
        reference_url = self._get_reference_url(reference_path)
        
        # 3. 检查缓存（workflow_type + prompt + reference_local_path）
        cache = self.db_manager.get_cache(workflow_type, prompt, reference_local_path=reference_path)
        if cache:
            result = self._handle_cache_hit(cache)
            if result:
                return result

        # 4. 设置缓存为 RUNNING 状态，防止并发重复提交
        cache_key = self.db_manager.make_cache_key(workflow_type, prompt, reference_local_path=reference_path)
        
        # 5. 根据工作流类型生成分发
        if workflow_type == 'photo':
            from generators.photo_generator import PhotoGenerator
            generator = PhotoGenerator(self.api_key, self.db_manager, self.exif_manager)
            return generator.generate(prompt, reference_url, reference_local_path=reference_path, **kwargs)
        
        elif workflow_type == 'multiphoto':
            from generators.multiphoto_generator import MultiPhotoGenerator
            generator = MultiPhotoGenerator(self.api_key, self.db_manager, self.exif_manager)
            return generator.generate(prompt, reference_url, reference_local_path=reference_path, **kwargs)
        
        elif workflow_type == 'video':
            from generators.video_generator import VideoGenerator
            generator = VideoGenerator(self.api_key, self.db_manager, self.exif_manager)
            return generator.generate(prompt, reference_url, reference_local_path=reference_path, **kwargs)
        
        elif workflow_type == 'prompt_photo':
            from generators.prompt_photo_generator import PromptPhotoGenerator
            generator = PromptPhotoGenerator(self.api_key, self.db_manager, self.exif_manager)
            return generator.generate(prompt, reference_url, reference_local_path=reference_path, **kwargs)
        
        raise ValueError(f"未知的工作流类型: {workflow_type}")
    
    def _get_reference_url(self, reference_path):
        """获取参考图URL"""
        if reference_path:
            # 上传新的参考图
            return self.reference_manager.upload(reference_path)
        
        # 使用当前激活的参考图
        active_url = self.reference_manager.get_active_reference_url()
        if active_url:
            return active_url
        
        # 如果没有，查找默认的
        default_path = self._find_default_reference()
        if default_path:
            return self.reference_manager.upload(default_path)
        
        raise ValueError("未找到参考图，请提供 --ref 参数或先上传参考图")
    
    def _find_default_reference(self):
        """查找默认参考图"""
        possible_paths = [
            '~/.openclaw/workspace-companion2/data/images/gym_clara_outfit.jpg',
            '~/.openclaw/workspace-companion2/data/images/avatar.jpg',
            '~/.openclaw/workspace-companion2/data/images/fuzhou_yantai_outfit.jpg',
        ]
        
        for path in possible_paths:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                return expanded
        
        return None
    
    def _handle_cache_hit(self, cache):
        """处理缓存命中"""
        if cache['status'] == 'SUCCESS':
            # 增加命中次数
            self.db_manager.increment_cache_hit(cache['prompt_hash'])
            
            # 返回缓存的结果
            result_id = cache.get('result_id')
            if result_id:
                from db.db_manager import HonnyDBManager
                db = HonnyDBManager()
                results = db.get_result_by_task_db_id(result_id)
                if results:
                    return {
                        'status': 'success',
                        'cache_hit': True,
                        'result': results[0]
                    }
            
            return {
                'status': 'success',
                'cache_hit': True,
                'result': cache
            }
        
        elif cache['status'] == 'RUNNING':
            # 检查任务是否真的还在跑，如果超过一定时间认为是 stale
            task_id = cache.get('task_id')
            if task_id and task_id.startswith('cached_'):
                # 本地缓存的任务已经过期，删除并继续
                self.db_manager.delete_cache(cache['prompt_hash'])
                return None
            raise Exception('CACHE_HIT_RUNNING', '任务正在生成中，请稍后')
        
        elif cache['status'] == 'FAILED':
            # 删除失败的缓存，重新提交
            self.db_manager.delete_cache(cache['prompt_hash'])
            return None
        
        return None


# 导入os以便使用
import os