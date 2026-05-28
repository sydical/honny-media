#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 多图套装生成器
版本：v1.0
日期：2026-05-18
"""

from datetime import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.runninghub import RunningHubClient
from utils.image_utils import download_file

try:
    from db.db_manager import get_db_manager
except ImportError:
    get_db_manager = None


class MultiPhotoGenerator:
    """MultiPhoto 多图套装生成器"""
    
    WORKFLOW_ID = '2054941025688399873'
    WORKFLOW_TYPE = 'multiphoto'
    
    def __init__(self, api_key, db_manager=None, exif_manager=None):
        self.api_key = api_key
        self.db_manager = db_manager
        self.exif_manager = exif_manager
        self.client = RunningHubClient(api_key)
    
    def generate(self, prompt, reference_url, reference_local_path=None, output_dir=None,
                inject_exif=True, async_mode=False, **kwargs):
        """生成多图套装
        
        Args:
            async_mode: 是否异步模式（只提交不等待），适合长时间任务避免shell超时
        
        Returns:
            async_mode=True时: {'status': 'submitted', 'task_id': str, 'prompt': str}
            async_mode=False时: {'status': 'success', 'task_id': str, 'local_paths': list, ...}
        """
        from core.exif_manager import ExifManager
        
        if self.exif_manager is None:
            self.exif_manager = ExifManager()
        
        print(f"🎨 开始生成 MultiPhoto...")
        print(f"📝 提示词: {prompt[:50]}...")
        
        # 获取数据库管理器
        if self.db_manager is None and get_db_manager:
            self.db_manager = get_db_manager()
        
        cache_key = self.db_manager.make_cache_key(self.WORKFLOW_TYPE, prompt, reference_local_path)
        
        # 检查缓存
        cache = self.db_manager.get_cache(self.WORKFLOW_TYPE, prompt, reference_local_path)
        if cache and not async_mode:
            result = self._handle_cache(cache)
            if result:
                return result
        
        # 设置缓存（RUNNING状态）
        self.db_manager.set_cache(self.WORKFLOW_TYPE, prompt, reference_local_path=reference_local_path, status='RUNNING')
        
        try:
            # 提交任务
            task_id = self._submit_task(reference_url, prompt)
            
            # 更新缓存
            self.db_manager.update_cache_running(cache_key, task_id)
            
            print(f"⏳ 任务ID: {task_id}")
            
            # 异步模式：只提交不等待，返回task_id
            if async_mode:
                return {
                    'status': 'submitted',
                    'task_id': task_id,
                    'workflow_id': self.WORKFLOW_ID,
                    'prompt': prompt,
                    'reference_url': reference_url
                }
            
            # 同步模式：轮询任务状态
            print(f"⏳ 任务ID: {task_id}")
            wait_result = self.client.wait_for_task(task_id, max_wait=600)
            
            if wait_result['status'] != 'SUCCESS':
                error_msg = wait_result['result'].get('errorMessage', 'Unknown error')
                raise Exception(f"任务失败: {error_msg}")
            
            # 解析输出 - 获取所有图片URL
            image_urls = self._parse_output(wait_result)
            
            # 下载所有图片
            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images/multiphoto')
            
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            images = []
            for i, url in enumerate(image_urls):
                ext = os.path.splitext(url)[1] or '.png'
                local_path = os.path.join(output_dir, f"multiphoto_{i+1}_{timestamp}{ext}")
                download_file(url, local_path)
                print(f"💾 图片{i+1}已保存: {local_path}")
                images.append({
                    'index': i,
                    'path': local_path,
                    'url': url
                })
            
            # 删除不再需要的网格图逻辑（如果有旧的网格文件）
            
            # 注入EXIF（每张）
            shot_at = datetime.now()
            for img in images:
                try:
                    img['local_path'] = self.exif_manager.inject(img['path'], shot_at)
                    img['shot_at'] = shot_at
                    print(f"📱 EXIF注入: {img['index'] + 1}/{len(images)}")
                except Exception as e:
                    print(f"⚠️ EXIF注入失败: {e}")
            
            # 保存到数据库
            task_record = self.db_manager.get_task_by_task_id(task_id)
            if task_record:
                task_db_id = task_record['id']
            else:
                task_db_id = self.db_manager.create_task(
                    task_id, self.WORKFLOW_TYPE, prompt, reference_url, self.WORKFLOW_ID
                )
            
            set_id = self.db_manager.save_multiphoto_set(task_db_id, prompt, images)
            
            # 更新缓存为成功
            self.db_manager.update_cache_success(cache_key, set_id)
            
            # 提取所有本地路径
            local_paths = [img.get('local_path') or img.get('path') for img in images]
            
            return {
                'status': 'success',
                'task_id': task_id,
                'set_id': set_id,
                'images': images,
                'local_paths': local_paths,  # 所有本地路径
                'urls': image_urls,  # 所有Cos原始URL
                'count': len(image_urls),  # 图片数量
                'exif_injected': inject_exif
            }
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            raise
    
    def _submit_task(self, reference_url, prompt):
        """提交到RunningHub"""
        node_info_list = [
            {"nodeId": "157", "fieldName": "image", "fieldValue": reference_url}
        ]
        
        task_id = self.client.submit_task(self.WORKFLOW_ID, node_info_list)
        return task_id
    
    def _parse_output(self, wait_result):
        """解析输出 - 返回所有图片URL列表"""
        outputs = self.client.parse_output(wait_result['result'])
        
        if not outputs:
            raise Exception("未获取到输出结果")
        
        image_urls = []
        for output in outputs:
            if isinstance(output, dict):
                url = output.get('image_url') or output.get('url') or output.get('download_url')
                if url:
                    image_urls.append(url)
        
        if not image_urls:
            raise Exception("未获取到任何图片URL")
        
        print(f"📊 获取到 {len(image_urls)} 张图片")
        return image_urls
    
    def _handle_cache(self, cache):
        """处理缓存命中"""
        if cache['status'] == 'SUCCESS':
            print("✅ 命中缓存，直接返回...")
            result_id = cache.get('result_id')
            if result_id:
                results = self.db_manager.get_result_by_task_db_id(result_id)
                if results:
                    return {'status': 'success', 'cache_hit': True, 'result': results[0]}
            return {'status': 'success', 'cache_hit': True}
        
        elif cache['status'] == 'RUNNING':
            print("⏳ 任务正在生成中，等待完成...")
            task_id = cache.get('task_id')
            if task_id:
                wait_result = self.client.wait_for_task(task_id, max_wait=600)
                if wait_result['status'] == 'SUCCESS':
                    cache_result = self.db_manager.get_cache(self.WORKFLOW_TYPE, cache['prompt'], cache['reference_local_path'])
                    if cache_result and cache_result.get('result_id'):
                        results = self.db_manager.get_result_by_task_db_id(cache_result['result_id'])
                        if results:
                            return {'status': 'success', 'cache_hit': True, 'result': results[0]}
        
        return None