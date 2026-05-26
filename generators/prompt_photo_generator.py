#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 分镜生图器 v3（去除网格切割）
根据多段分镜提示词生成人物一致性多场景多视角图片

版本：v3.0
日期：2026-05-24

核心逻辑：
- 工作流返回多个URL → 每URL直接下载，每张独立完整
- 工作流返回单个URL → 每URL直接下载，每张独立完整
- 不再检测网格，不再切割
"""

from datetime import datetime
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.runninghub import RunningHubClient
from utils.image_utils import download_file, get_file_size
from prompts.prompt_photo_template import format_prompt_photo

try:
    from db.db_manager import get_db_manager
except ImportError:
    get_db_manager = None


class PromptPhotoGenerator:
    """分镜生图器 v3 - 多场景多视角一致性图片生成"""
    
    WORKFLOW_ID = '2050291848673021954'
    WORKFLOW_TYPE = 'prompt_photo'
    
    def __init__(self, api_key, db_manager=None, exif_manager=None):
        self.api_key = api_key
        self.db_manager = db_manager
        self.exif_manager = exif_manager
        self.client = RunningHubClient(api_key)
    
    def generate(self, prompt, reference_url, reference_local_path=None, output_dir=None, 
                inject_exif=True, async_mode=False, use_template=True, verbose=True, **kwargs):
        """
        生成多场景分镜图片
        
        Args:
            prompt: 分镜提示词，支持多段格式
            reference_url: 参考图COS URL
            reference_local_path: 参考图本地路径
            output_dir: 输出目录
            inject_exif: 是否注入EXIF
            async_mode: 异步模式
            use_template: 是否使用三段式模板重组（默认开启）
            verbose: 是否打印格式化后的提示词（默认开启）
        
        Returns:
            dict: 生成结果，包含各分镜图路径
        """
        from core.exif_manager import ExifManager
        
        if self.exif_manager is None:
            self.exif_manager = ExifManager()
        
        print(f"🎬 开始生成分镜图片...")
        print(f"📝 原始提示词长度: {len(prompt)} 字符")
        
        # --- 三段式模板重组 ---
        if use_template:
            formatted = format_prompt_photo(prompt)
            if verbose:
                print(f"📋 提示词已重组（三段式结构）：")
                for line in formatted.split('\n'):
                    print(f"   {line}")
            prompt = formatted
            print(f"📝 重组后提示词长度: {len(prompt)} 字符")
        
        if self.db_manager is None and get_db_manager:
            self.db_manager = get_db_manager()
        
        # 解析分镜数量和内容
        shots = self._parse_shots(prompt)
        num_shots = len(shots)
        print(f"📊 检测到 {num_shots} 个分镜")
        
        cache_key = self.db_manager.make_cache_key(self.WORKFLOW_TYPE, prompt, reference_local_path)
        
        # 检查缓存
        cache = self.db_manager.get_cache(self.WORKFLOW_TYPE, prompt, reference_local_path)
        if cache:
            result = self._handle_cache(cache)
            if result:
                return result
        
        # 设置缓存为RUNNING状态
        self.db_manager.set_cache(
            self.WORKFLOW_TYPE, prompt, 
            reference_local_path=reference_local_path, 
            status='RUNNING'
        )
        
        try:
            # 格式化分镜提示词
            formatted_prompt = self._format_prompt(shots)
            
            # 提交任务
            task_id = self._submit_task(reference_url, formatted_prompt)
            self.db_manager.update_cache_running(cache_key, task_id)
            
            print(f"⏳ 任务ID: {task_id}")
            
            if async_mode:
                return {
                    'status': 'submitted',
                    'task_id': task_id,
                    'workflow_id': self.WORKFLOW_ID,
                    'num_shots': num_shots,
                    'shots': shots
                }
            
            # 同步等待
            wait_result = self.client.wait_for_task(task_id, max_wait=600)
            
            if wait_result['status'] != 'SUCCESS':
                error_msg = wait_result['result'].get('errorMessage', 'Unknown error')
                raise Exception(f"任务失败: {error_msg}")
            
            # 解析输出
            urls = self._parse_output(wait_result)
            
            # 确定输出目录
            if output_dir is None:
                output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images/prompt_photo')
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = os.path.join(output_dir, f"session_{timestamp}")
            os.makedirs(session_dir, exist_ok=True)
            
            shot_at = datetime.now()
            final_paths = []
            
            for i, url in enumerate(urls):
                index = i  # 从0开始
                ext = os.path.splitext(url.split('?')[0])[1] or '.jpg'
                local = os.path.join(session_dir, f"shot_{index}_{timestamp}{ext}")
                download_file(url, local)
                
                if inject_exif:
                    local = self.exif_manager.inject(local, shot_at)
                
                shot = shots[i] if i < len(shots) else f"分镜{i+1}"
                final_paths.append({
                    'index': index,
                    'prompt': shot,
                    'url': url,
                    'local_path': local
                })
                
                print(f"📸 [{index}] {os.path.basename(local)}")
            
            print(f"✂️ 获得 {len(final_paths)} 张分镜图")
            
            # 保存到数据库
            task_record = self.db_manager.get_task_by_task_id(task_id)
            if task_record:
                task_db_id = task_record['id']
            else:
                task_db_id = self.db_manager.create_task(
                    task_id, self.WORKFLOW_TYPE, prompt, reference_url, self.WORKFLOW_ID
                )
            
            for info in final_paths:
                file_size = get_file_size(info['local_path'])
                self.db_manager.save_result(
                    task_db_id, 'image', info['url'], info['local_path'],
                    width=0, height=0, file_size=file_size
                )
            
            self.db_manager.update_cache_success(cache_key, task_db_id)
            
            return {
                'status': 'success',
                'task_id': task_id,
                'num_shots': len(final_paths),
                'shots': shots,
                'shot_paths': final_paths,
                'shot_at': shot_at
            }
            
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            raise
    
    def _parse_shots(self, prompt):
        """解析分镜提示词
        
        支持多种格式：
        1. 格式化格式：分镜1提示词\n内容\n质量层\n\n分镜2提示词\n内容\n...
        2. 冒号格式：分镜1：内容\n分镜2：内容
        3. 数字点格式：1. 内容\n2. 内容
        4. 空行分隔：无标记时按空行分割
        5. 单段提示词：直接作为整体提示词
        """
        if not prompt or not prompt.strip():
            return []
        
        # 质量层说明行（跳过）
        quality_pattern = re.compile(
            r'^(电影级面光|24mm主摄|超级高清|暖调通透|--no|iPhone原生|大师作品|顶级画质|浅景深|柔和光影)'
        )
        
        # 1. 尝试格式化分割器：分镜N提示词\n 格式
        blocks = re.split(r'分镜(\d+)提示词\s*\n', prompt)
        if len(blocks) > 2:
            # blocks[0]='', blocks[1]='1', blocks[2]=content1, blocks[3]='2', blocks[4]=content2...
            shots = []
            i = 1
            while i < len(blocks) - 1:
                shot_index = blocks[i]
                shot_content = blocks[i + 1]
                lines = [l.strip() for l in shot_content.split('\n') if l.strip()]
                shot_parts = []
                for line in lines:
                    if not line:
                        continue
                    if quality_pattern.match(line):
                        continue
                    shot_parts.append(line)
                    if len(shot_parts) >= 2:
                        break
                if shot_parts:
                    shots.append(' '.join(shot_parts))
                i += 2
            if shots:
                return shots
        
        # 2. 尝试冒号格式：分镜1：xxx 或 【分镜1】xxx
        marker_colon = re.compile(
            r'^(分镜\s*\d+\s*[:：]?\s*|【?分镜\s*\d+】?\s*[:：]?\s*)',
            re.IGNORECASE
        )
        
        # 3. 尝试数字点格式：1. xxx 或 1：xxx
        marker_num = re.compile(r'^(\d+)\s*[:：.]\s*')
        
        lines = prompt.split('\n')
        shots = []
        current_shot = []
        
        for line in lines:
            line = line.strip()
            if not line:
                # 空行分隔两个分镜
                if current_shot:
                    joined = ' '.join(current_shot)
                    if joined:
                        shots.append(joined)
                    current_shot = []
                continue
            
            # 跳过质量层
            if quality_pattern.match(line):
                continue
            
            # 检测分镜标记
            is_marker = False
            if marker_colon.match(line):
                # 去掉分镜标记前缀
                line = marker_colon.sub('', line)
                is_marker = True
            elif marker_num.match(line):
                # 去掉数字标记前缀
                line = marker_num.sub('', line)
                is_marker = True
            
            # 如果是新的分镜标记且当前已有内容，保存之前的
            if is_marker and current_shot:
                joined = ' '.join(current_shot)
                if joined:
                    shots.append(joined)
                current_shot = []
            
            current_shot.append(line)
        
        # 保存最后一个分镜
        if current_shot:
            joined = ' '.join(current_shot)
            if joined:
                shots.append(joined)
        
        return [s for s in shots if s]
    
    def _format_prompt(self, shots):
        header = f"根据下面{len(shots)}段连续性的分镜提示词生成图片\n"
        body = '\n'.join([f"分镜{i+1}提示词\n{shot}" for i, shot in enumerate(shots)])
        return header + body
    
    def _submit_task(self, reference_url, prompt):
        node_info_list = [
            {"nodeId": "342", "fieldName": "image", "fieldValue": reference_url},
            {"nodeId": "366", "fieldName": "prompt", "fieldValue": prompt}
        ]
        return self.client.submit_task(self.WORKFLOW_ID, node_info_list)
    
    def _parse_output(self, wait_result):
        """解析输出，返回URL列表"""
        outputs = self.client.parse_output(wait_result['result'])
        
        if not outputs:
            raise Exception("未获取到输出结果")
        
        print(f"📊 工作流返回 {len(outputs)} 条结果")
        
        urls = []
        for o in outputs:
            if isinstance(o, dict):
                url = o.get('url') or o.get('image_url') or o.get('download_url')
                if url:
                    urls.append(url)
        
        if not urls:
            raise Exception("未获取到任何图片URL")
        
        print(f"📊 {len(urls)} 张独立图片，直接使用")
        return urls
    
    def _handle_cache(self, cache):
        if cache['status'] == 'SUCCESS':
            print("✅ 命中缓存，直接返回...")
            result_id = cache.get('result_id')
            shots_data = []
            if result_id:
                results = self.db_manager.get_result_by_task_db_id(result_id)
                if results:
                    for r in results:
                        shots_data.append({
                            'index': len(shots_data) + 1,
                            'prompt': cache.get('prompt', ''),
                            'url': r.get('url', ''),
                            'local_path': r.get('local_path', '')
                        })
                    return {
                        'status': 'success',
                        'cache_hit': True,
                        'shot_paths': shots_data,
                        'num_shots': len(shots_data),
                        'shots': cache.get('prompt', '').split('\n'),
                    }
            return {'status': 'success', 'cache_hit': True}
        
        elif cache['status'] == 'RUNNING':
            print("⏳ 任务正在生成中，等待完成...")
            task_id = cache.get('task_id')
            if task_id:
                wait_result = self.client.wait_for_task(task_id, max_wait=600)
                if wait_result['status'] == 'SUCCESS':
                    cache_result = self.db_manager.get_cache(
                        self.WORKFLOW_TYPE, 
                        cache['prompt'], 
                        cache.get('reference_local_path')
                    )
                    if cache_result and cache_result.get('result_id'):
                        results = self.db_manager.get_result_by_task_db_id(cache_result['result_id'])
                        if results:
                            shots_data = [{
                                'index': i + 1,
                                'prompt': cache.get('prompt', ''),
                                'url': r.get('url', ''),
                                'local_path': r.get('local_path', '')
                            } for i, r in enumerate(results)]
                            return {
                                'status': 'success',
                                'cache_hit': True,
                                'shot_paths': shots_data,
                                'num_shots': len(shots_data),
                                'shots': cache.get('prompt', '').split('\n'),
                            }
        
        return None