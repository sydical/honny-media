#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 工作流分发器
版本：v1.1
日期：2026-05-27
变更：DB 先行流程 + async_mode 支持
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

# 工作流 ID 映射
WORKFLOW_IDS = {
    'photo': '2047002838944980993',
    'multiphoto': '2054941025688399873',
    'video': '2048133528671490050',
    'prompt_photo': '2050291848673021954',
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
    
    # 默认 photo
    return 'photo'


class WorkflowDispatcher:
    """工作流分发器 - DB 先行流程"""

    def __init__(self, api_key, db_manager=None):
        self.api_key = api_key

        # 获取数据库管理器
        if db_manager is None:
            from db.db_manager import get_db_manager
            self.db_manager = get_db_manager()
        else:
            self.db_manager = db_manager

        self.reference_manager = ReferenceManager(api_key, self.db_manager)
        self.exif_manager = ExifManager()

    def dispatch(self, prompt, reference_path=None, workflow_type=None, 
                 async_mode=False, output_dir=None, inject_exif=True, **kwargs):
        """分发工作流（DB 先行流程）

        流程：
        1. 检测工作流类型
        2. 获取/上传参考图 URL（可能建立来源任务映射）
        3. 检查缓存（含 stale 检测）
        4. 先创建任务记录（PENDING），再提交到 API
        5. 用 API 返回的 task_id 更新 DB 记录（RUNNING）
        6. 异步模式：返回 task_id，由 PollingWorker 接管
           同步模式：内部轮询等待

        Args:
            async_mode: 是否异步模式（只提交不等待，适合长时间任务）
        """
        # 1. 检测工作流类型
        if workflow_type is None:
            workflow_type = detect_workflow(prompt)

        # 2. 获取参考图 URL
        reference_url = self._get_reference_url(reference_path)
        reference_local_path = reference_path

        # 3. 检查缓存（含 stale 检测，RUNNING > 15min 会自动删除）
        cache = self.db_manager.get_cache(workflow_type, prompt, reference_local_path)
        if cache:
            result = self._handle_cache_hit(cache, reference_local_path)
            if result:
                return result

        # 4. Video 类型先计算 optimized_prompt（用于存入 DB）
        optimized_prompt = None
        if workflow_type == 'video':
            duration = kwargs.get('duration', 8)
            optimized_prompt = self._optimize_prompt(prompt, duration)

        # 5. 先在 DB 创建任务记录（PENDING，无 task_id）
        task_db_id = self.db_manager.create_task(
            workflow_type=workflow_type,
            prompt=prompt,
            optimized_prompt=optimized_prompt,
            reference_url=reference_url,
            status='PENDING'
        )

        # 6. 构建 node_info_list 并提交到 RunningHub
        node_info_list = self._build_node_info(workflow_type, reference_url, prompt, optimized_prompt, **kwargs)
        workflow_id = WORKFLOW_IDS.get(workflow_type)

        from utils.runninghub import RunningHubClient
        client = RunningHubClient(self.api_key)
        task_id = client.submit_task(workflow_id, node_info_list)

        # 6. 立即更新 DB（此时 task_id 才已知）
        self.db_manager.update_task_task_id(task_db_id, task_id)
        self.db_manager.update_task_status(task_id, 'RUNNING')

        # 7. 设置缓存（RUNNING 状态）
        cache_key = self.db_manager.set_cache(
            workflow_type, prompt, 
            reference_local_path=reference_local_path,
            status='RUNNING', 
            task_id=task_id,
            reference_url=reference_url
        )

        # 8. 异步模式：返回 task_id，PollingWorker 接管
        if async_mode:
            return {
                'status': 'submitted',
                'task_id': task_id,
                'task_db_id': task_db_id,
                'workflow_type': workflow_type,
                'workflow_id': workflow_id,
                'prompt': prompt,
                'reference_url': reference_url
            }

        # 9. 同步模式：轮询等待（向后兼容）
        return self._wait_for_result_sync(
            task_id, task_db_id, workflow_type, 
            reference_local_path, cache_key, output_dir, inject_exif, **kwargs
        )

    def _build_node_info(self, workflow_type, reference_url, prompt, optimized_prompt=None, **kwargs):
        """构建提交到 RunningHub 的 node_info_list"""
        if workflow_type == 'photo':
            return [
                {"nodeId": "1", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "8", "fieldName": "text", "fieldValue": prompt}
            ]
        elif workflow_type == 'multiphoto':
            return [
                {"nodeId": "157", "fieldName": "image", "fieldValue": reference_url}
            ]
        elif workflow_type == 'video':
            duration = kwargs.get('duration', 8)
            # 优先使用已优化好的 optimized_prompt（从 dispatch 传入）
            final_prompt = optimized_prompt if optimized_prompt else self._optimize_prompt(prompt, duration)
            return [
                {"nodeId": "13", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "36", "fieldName": "text", "fieldValue": final_prompt},
                {"nodeId": "15", "fieldName": "value", "fieldValue": str(duration)}
            ]
        elif workflow_type == 'prompt_photo':
            return [
                {"nodeId": "1", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "8", "fieldName": "text", "fieldValue": prompt}
            ]
        return []

    def _optimize_prompt(self, prompt, duration=8):
        """优化分镜提示词 - 电影级 3 秒镜头拆分"""
        from generators.video_generator import VideoGenerator
        gen = VideoGenerator(self.api_key, self.db_manager, self.exif_manager)
        return gen._optimize_prompt(prompt, duration)

    def _wait_for_result_sync(self, task_id, task_db_id, workflow_type, 
                              reference_local_path, cache_key, output_dir, inject_exif, **kwargs):
        """同步模式：轮询等待任务结果（向后兼容）"""
        from utils.runninghub import RunningHubClient
        client = RunningHubClient(self.api_key)

        max_wait = 1200  # 20 分钟
        if workflow_type == 'multiphoto':
            max_wait = 600  # 10 分钟

        wait_result = client.wait_for_task(task_id, max_wait=max_wait)

        if wait_result['status'] != 'SUCCESS':
            error_msg = wait_result['result'].get('errorMessage', 'Unknown error')
            self.db_manager.update_task_status(task_id, 'FAILED', error_message=error_msg)
            raise Exception(f"任务失败: {error_msg}")

        # 解析输出并保存
        outputs = client.parse_output(wait_result['result'])
        return self._save_result(outputs, task_id, task_db_id, workflow_type, 
                                 reference_local_path, output_dir, inject_exif, cache_key)

    def _save_result(self, outputs, task_id, task_db_id, workflow_type, 
                     reference_local_path, output_dir, inject_exif, cache_key):
        """保存结果到本地和数据库"""
        if not outputs:
            raise Exception("未获取到输出结果")

        if workflow_type == 'video':
            from utils.image_utils import download_file, get_file_size
            from core.exif_manager import ExifManager

            video_url = outputs[0].get('video_url') or outputs[0].get('url') or outputs[0].get('download_url')
            if not video_url:
                raise Exception("未获取到视频 URL")

            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/videos')
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            local_path = os.path.join(output_dir, f"video_{task_id}_{timestamp}.mp4")

            download_file(video_url, local_path)
            file_size = get_file_size(local_path)

            result_id = self.db_manager.save_video_result(
                task_db_id, local_path, duration=8, file_size=file_size
            )

            self.db_manager.update_cache_success(cache_key, result_id)
            self.db_manager.update_task_status(task_db_id, 'SUCCESS', local_path=local_path)

            return {
                'status': 'success',
                'task_id': task_id,
                'local_path': local_path,
                'duration': 8,
                'file_size': file_size
            }

        elif workflow_type == 'multiphoto':
            from utils.image_utils import download_file, center_crop, get_image_size
            from core.exif_manager import ExifManager

            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images/multiphoto')
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shot_at = datetime.now()

            images = []
            for i, output in enumerate(outputs):
                url = output.get('url') or output.get('image_url') or output.get('download_url')
                if not url:
                    continue

                ext = os.path.splitext(url)[1] or '.png'
                local_path = os.path.join(output_dir, f"multiphoto_{i+1}_{task_id}_{timestamp}{ext}")
                download_file(url, local_path)

                # ✅ 等比裁切到 720×1280
                local_path = center_crop(local_path, width=720, height=1280)

                # 注入 EXIF
                if inject_exif:
                    try:
                        local_path = self.exif_manager.inject(local_path, shot_at)
                    except Exception as e:
                        print(f"⚠️ EXIF 注入失败: {e}")

                width, height = get_image_size(local_path)

                images.append({
                    'image_url': url,
                    'local_path': local_path,
                    'width': width,
                    'height': height,
                    'shot_at': shot_at,
                    'exif_injected': inject_exif,
                    'prompt': ''  # 复用 task prompt
                })

            if images:
                set_id = self.db_manager.save_multiphoto_set(task_db_id, '', images)
                self.db_manager.update_cache_success(cache_key, set_id)
                self.db_manager.update_task_status(task_db_id, 'SUCCESS')

                return {
                    'status': 'success',
                    'task_id': task_id,
                    'set_id': set_id,
                    'images': images,
                    'local_paths': [img['local_path'] for img in images],
                    'count': len(images)
                }

        else:  # photo / prompt_photo
            from utils.image_utils import download_file, get_image_size, get_file_size
            from core.exif_manager import ExifManager

            image_url = outputs[0].get('url') or outputs[0].get('image_url') or outputs[0].get('download_url')
            if not image_url:
                raise Exception("未获取到图片 URL")

            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images')
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            local_path = os.path.join(output_dir, f"honny_{task_id}_{timestamp}.jpg")

            download_file(image_url, local_path)

            shot_at = datetime.now()
            if inject_exif:
                local_path = self.exif_manager.inject(local_path, shot_at)

            width, height = get_image_size(local_path)
            file_size = get_file_size(local_path)

            exif_data = {
                'phone_model': self.exif_manager.phone_model,
                'gps_lat': self.exif_manager.gps_coords[0],
                'gps_lon': self.exif_manager.gps_coords[1],
                'shot_at': shot_at
            }

            result_id = self.db_manager.save_result(
                task_db_id, 'image', image_url, local_path,
                width, height, file_size, exif_data
            )

            self.db_manager.update_cache_success(cache_key, result_id)
            self.db_manager.update_task_status(task_db_id, 'SUCCESS', local_path=local_path)

            return {
                'status': 'success',
                'task_id': task_id,
                'image_url': image_url,
                'local_path': local_path,
                'width': width,
                'height': height,
                'exif_injected': inject_exif,
                'shot_at': shot_at
            }

    def _get_reference_url(self, reference_path):
        """获取参考图 URL（支持自动追溯来源任务）"""
        if reference_path:
            # 上传新的参考图（可能建立来源任务映射）
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

    def _handle_cache_hit(self, cache, reference_local_path=None):
        """处理缓存命中（含 stale 检测后的正常返回）"""
        if cache['status'] == 'SUCCESS':
            # 增加命中次数
            self.db_manager.increment_cache_hit(cache['prompt_hash'])

            result_id = cache.get('result_id')
            if result_id:
                results = self.db_manager.get_result_by_task_db_id(result_id)
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
            # stale 检测已在上层 get_cache() 中处理
            # 正常情况下这里不会收到 stale RUNNING（已删除）
            raise Exception('CACHE_HIT_RUNNING', '任务正在生成中，请稍后')

        elif cache['status'] == 'FAILED':
            # 删除失败的缓存，重新提交
            self.db_manager.delete_cache(cache['prompt_hash'])
            return None

        return None


# 导入 datetime
from datetime import datetime

# 导入 os
import os