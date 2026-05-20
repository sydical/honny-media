#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 视频生成器
版本：v1.0
日期：2026-05-18
"""

from datetime import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.runninghub import RunningHubClient
from utils.image_utils import download_file, get_file_size

try:
    from db.db_manager import get_db_manager
except ImportError:
    get_db_manager = None


class VideoGenerator:
    """Video 视频生成器"""
    
    WORKFLOW_ID = '2048133528671490050'
    WORKFLOW_TYPE = 'video'
    
    def __init__(self, api_key, db_manager=None, exif_manager=None):
        self.api_key = api_key
        self.db_manager = db_manager
        self.exif_manager = exif_manager
        self.client = RunningHubClient(api_key)
    
    def generate(self, prompt, reference_url, reference_local_path=None, output_dir=None, duration=8, async_mode=False, **kwargs):
        """生成视频
        
        Args:
            prompt: 分镜提示词
            reference_url: 参考图COS URL
            reference_local_path: 参考图本地路径
            output_dir: 输出目录
            duration: 视频时长（秒），默认8秒
            async_mode: 是否异步模式（只提交不等待），适合长时间任务避免shell超时
        
        Returns:
            async_mode=True时: {'status': 'submitted', 'task_id': str}
            async_mode=False时: {'status': 'success', 'task_id': str, 'local_path': str, ...}
        """
        print(f"🎬 开始生成 Video...")
        print(f"📝 分镜: {prompt[:50]}...")
        
        # 获取数据库管理器
        if self.db_manager is None and get_db_manager:
            self.db_manager = get_db_manager()
        
        cache_key = self.db_manager.make_cache_key(self.WORKFLOW_TYPE, prompt, reference_local_path)
        
        # 检查缓存（只用 workflow_type + prompt，不含 reference_url）
        cache = self.db_manager.get_cache(self.WORKFLOW_TYPE, prompt, reference_local_path)
        if cache and not async_mode:
            result = self._handle_cache(cache)
            if result:
                return result
        
        # 设置缓存为 RUNNING 状态
        self.db_manager.set_cache(self.WORKFLOW_TYPE, prompt, reference_local_path=reference_local_path, status='RUNNING')
        
        try:
            # 优化提示词为电影级分镜格式
            optimized_prompt = self._optimize_prompt(prompt, duration)
            print(f"📝 优化后分镜: {optimized_prompt[:80]}...")

            task_id = self._submit_task(reference_url, optimized_prompt, duration)
            
            # 更新缓存
            self.db_manager.update_cache_running(cache_key, task_id)
            
            print(f"⏳ 任务ID: {task_id}")
            
            # 异步模式：只提交不等待，返回task_id
            if async_mode:
                return {
                    'status': 'submitted',
                    'task_id': task_id,
                    'workflow_id': self.WORKFLOW_ID,
                    'optimized_prompt': optimized_prompt,
                    'duration': duration
                }
            
            # 同步模式：轮询等待
            wait_result = self.client.wait_for_task(task_id, max_wait=1200, poll_interval=30)
            
            if wait_result['status'] != 'SUCCESS':
                error_msg = wait_result['result'].get('errorMessage', 'Unknown error')
                raise Exception(f"任务失败: {error_msg}")
            
            # 解析输出
            video_url = self._parse_output(wait_result)
            
            # 下载视频
            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/videos')
            
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            local_path = os.path.join(output_dir, f"video_{timestamp}.mp4")
            
            download_file(video_url, local_path)
            print(f"💾 视频已保存: {local_path}")
            
            # 获取视频信息
            file_size = get_file_size(local_path)
            
            # 保存到数据库（视频不注入EXIF）
            task_record = self.db_manager.get_task_by_task_id(task_id)
            if task_record:
                task_db_id = task_record['id']
            else:
                task_db_id = self.db_manager.create_task(
                    task_id, self.WORKFLOW_TYPE, prompt, reference_url, self.WORKFLOW_ID
                )
            
            result_id = self.db_manager.save_video_result(
                task_db_id, local_path, duration=duration, file_size=file_size
            )
            
            # 更新缓存为成功
            self.db_manager.update_cache_success(cache_key, result_id)
            
            return {
                'status': 'success',
                'task_id': task_id,
                'local_path': local_path,
                'duration': duration,
                'file_size': file_size
            }
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            raise
    

    # 电影级分镜固定参数
    FILM_PARAMS = (
        "8K超清、2.35:1宽银幕、胶片质感、物理光影、柔焦景深、"
        "低饱和院线调色、平缓丝滑运镜、无抖动无畸变"
    )

    def _optimize_prompt(self, prompt, duration=8):
        """优化分镜提示词 - 电影级3秒镜头拆分"""
        # 如果用户提示词已经包含完整分镜结构，直接使用
        if '【' in prompt and '秒】' in prompt and '镜头' in prompt:
            return prompt

        # 计算镜头数量（每3秒一个镜头）
        num_shots = max(1, duration // 3)

        # 将提示词按句子或换行符分割成语义单元
        segments = []
        # 优先按换行分割
        if '\n' in prompt:
            segments = [s.strip() for s in prompt.split('\n') if s.strip()]
        else:
            # 按中英文标点分割
            for sep in ['。', '，', ',', ';', '；']:
                if sep in prompt:
                    parts = [s.strip() for s in prompt.split(sep) if s.strip()]
                    for part in parts:
                        if len(part) > 30:
                            # 按顿号分割长句
                            sub_parts = [s.strip() for s in part.split('、') if s.strip()]
                            segments.extend(sub_parts)
                        else:
                            segments.append(part)
                    break
        
        # 如果分割后只有一个段落，且段落很长，则按逗号再次分割
        if len(segments) == 1 and len(segments[0]) > 40:
            sub_parts = [s.strip() for s in segments[0].split('，') if s.strip()]
            if len(sub_parts) > 1:
                segments = sub_parts
        
        if not segments:
            segments = [prompt.strip()]

        # 运镜方式列表（轮换使用）
        camera_moves = ['横移', '推进', '俯扫', '定格', '拉远', '聚焦']

        optimized_shots = []
        for i in range(num_shots):
            # 为每个镜头分配语义内容
            if i < len(segments):
                content = segments[i]
            else:
                # 如果段落不够，循环使用最后一段
                content = segments[-1] if segments else prompt

            # 轮换运镜方式
            camera = camera_moves[i % len(camera_moves)]

            # 构建镜头描述
            shot = (
                f"{i+1}.【3秒】{content}，"
                f"{camera}镜头，{self.FILM_PARAMS}"
            )
            optimized_shots.append(shot)

        # 组装最终提示词
        header = "电影级3秒分镜头脚本\n"
        return header + "\n".join(optimized_shots)
    def _submit_task(self, reference_url, prompt, duration=8):
        """提交到RunningHub"""
        node_info_list = [
            {"nodeId": "13", "fieldName": "image", "fieldValue": reference_url},
            {"nodeId": "36", "fieldName": "text", "fieldValue": prompt},
            {"nodeId": "15", "fieldName": "value", "fieldValue": str(duration)}
        ]
        
        task_id = self.client.submit_task(self.WORKFLOW_ID, node_info_list)
        return task_id
    
    def _parse_output(self, wait_result):
        """解析输出"""
        outputs = self.client.parse_output(wait_result['result'])
        
        if not outputs:
            raise Exception("未获取到输出结果")
        
        video_url = None
        for output in outputs:
            if isinstance(output, dict):
                video_url = output.get('video_url') or output.get('url') or output.get('download_url')
                if video_url:
                    break
        
        if not video_url:
            raise Exception("未获取到视频URL")
        
        return video_url
    
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