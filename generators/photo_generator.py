#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 照片生成器
版本：v1.0
日期：2026-05-18
"""

from datetime import datetime
import os
import sys

# 添加项目路径（兼容相对和绝对导入）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.runninghub import RunningHubClient
from utils.image_utils import download_file, get_image_size, get_file_size

# 获取数据库管理器
try:
    from db.db_manager import get_db_manager
except ImportError:
    get_db_manager = None


class PhotoGenerator:
    """Photo 单图生成器"""
    
    WORKFLOW_ID = '2047002838944980993'
    WORKFLOW_TYPE = 'photo'
    
    def __init__(self, api_key, db_manager=None, exif_manager=None):
        self.api_key = api_key
        self.db_manager = db_manager
        self.exif_manager = exif_manager
        self.client = RunningHubClient(api_key)
    
    def generate(self, prompt, reference_url, reference_local_path=None, output_dir=None, inject_exif=True, **kwargs):
        """生成单张图片"""
        from core.exif_manager import ExifManager
        
        if self.exif_manager is None:
            self.exif_manager = ExifManager()
        
        print(f"🎨 开始生成 Photo...")
        print(f"📝 提示词: {prompt[:50]}...")
        
        # 获取数据库管理器
        if self.db_manager is None and get_db_manager:
            self.db_manager = get_db_manager()
        
        cache_key = self.db_manager.make_cache_key(self.WORKFLOW_TYPE, prompt, reference_local_path)
        
        # 检查缓存
        cache = self.db_manager.get_cache(self.WORKFLOW_TYPE, prompt, reference_local_path)
        if cache:
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
            
            # 轮询任务状态
            print(f"⏳ 任务ID: {task_id}")
            wait_result = self.client.wait_for_task(task_id, max_wait=300)
            
            if wait_result['status'] != 'SUCCESS':
                error_msg = wait_result['result'].get('errorMessage', 'Unknown error')
                raise Exception(f"任务失败: {error_msg}")
            
            # 解析输出
            image_url = self._parse_output(wait_result)
            
            # 保存到本地
            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images')
            
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            local_path = os.path.join(output_dir, f"honny_{timestamp}.jpg")
            
            download_file(image_url, local_path)
            print(f"💾 图片已保存: {local_path}")
            
            # 注入EXIF
            shot_at = datetime.now()
            exif_data = None
            if inject_exif:
                local_path = self.exif_manager.inject(local_path, shot_at)
                exif_data = {
                    'phone_model': self.exif_manager.phone_model,
                    'gps_lat': self.exif_manager.gps_coords[0],
                    'gps_lon': self.exif_manager.gps_coords[1],
                    'shot_at': shot_at
                }
                print(f"📱 EXIF注入完成")
            
            # 获取图片信息
            width, height = get_image_size(local_path)
            file_size = get_file_size(local_path)
            
            # 保存到数据库
            task_record = self.db_manager.get_task_by_task_id(task_id)
            if task_record:
                task_db_id = task_record['id']
            else:
                task_db_id = self.db_manager.create_task(
                    task_id, self.WORKFLOW_TYPE, prompt, reference_url, self.WORKFLOW_ID
                )
            
            result_id = self.db_manager.save_result(
                task_db_id, 'image', image_url, local_path,
                width, height, file_size, exif_data
            )
            
            # 更新缓存为成功
            self.db_manager.update_cache_success(cache_key, result_id)
            
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
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            raise
    
    def _submit_task(self, reference_url, prompt):
        """提交到RunningHub"""
        node_info_list = [
            {"nodeId": "1", "fieldName": "image", "fieldValue": reference_url},
            {"nodeId": "8", "fieldName": "text", "fieldValue": prompt}
        ]
        
        task_id = self.client.submit_task(self.WORKFLOW_ID, node_info_list)
        return task_id
    
    def _parse_output(self, wait_result):
        """解析输出"""
        outputs = self.client.parse_output(wait_result['result'])
        
        if not outputs:
            raise Exception("未获取到输出结果")
        
        # 输出格式: [{'url': '...', 'nodeId': '15', 'outputType': 'png'}]
        image_url = None
        for output in outputs:
            if isinstance(output, dict):
                # 尝试多种可能的URL字段
                image_url = output.get('url') or output.get('image_url') or output.get('download_url')
                if image_url:
                    break
        
        if not image_url:
            raise Exception("未获取到图片URL")
        
        return image_url
    
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
                wait_result = self.client.wait_for_task(task_id, max_wait=300)
                if wait_result['status'] == 'SUCCESS':
                    cache_result = self.db_manager.get_cache(self.WORKFLOW_TYPE, cache['prompt'], cache['reference_local_path'])
                    if cache_result and cache_result.get('result_id'):
                        results = self.db_manager.get_result_by_task_db_id(cache_result['result_id'])
                        if results:
                            return {'status': 'success', 'cache_hit': True, 'result': results[0]}
        
        return None