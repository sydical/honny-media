#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia PollingWorker - 后台守护线程
版本：v1.0
日期：2026-05-27

职责：
1. 轮询所有 RUNNING 状态的任务，检查是否完成
2. 处理 stale RUNNING 任务（超过阈值未完成，强制重试或标记失败）
3. 任务完成后保存结果、通知下游依赖、更新缓存
4. 支持重试机制（可重试错误最多 3 次）
"""

import threading
import time
from datetime import datetime, timedelta
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.runninghub import RunningHubClient
from utils.image_utils import download_file, get_image_size, get_file_size


class PollingWorker:
    """后台轮询守护线程"""

    STALE_THRESHOLD_MINUTES = 15  # 超过 15 分钟认为 stale
    RETRY_DELAYS = [30, 60, 120]  # 重试间隔（秒）
    MAX_RETRIES = 3

    def __init__(self, api_key, db_manager=None, poll_interval=30):
        """
        Args:
            api_key: RunningHub API Key
            db_manager: 数据库管理器（可选，默认单例）
            poll_interval: 轮询间隔（秒）
        """
        self.api_key = api_key
        self.client = RunningHubClient(api_key)

        if db_manager is None:
            from db.db_manager import get_db_manager
            self.db_manager = get_db_manager()
        else:
            self.db_manager = db_manager

        self.poll_interval = poll_interval
        self.running = False
        self.thread = None

    def start(self):
        """启动守护线程"""
        if self.running:
            print("⚠️ PollingWorker 已在运行")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="PollingWorker")
        self.thread.start()
        print(f"🔄 PollingWorker 已启动（轮询间隔 {self.poll_interval}s）")

    def stop(self):
        """停止守护线程"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
            print("🔄 PollingWorker 已停止")

    def _run(self):
        """轮询主循环"""
        while self.running:
            try:
                # 1. 处理 stale RUNNING 任务
                self._poll_stale_tasks()

                # 2. 轮询所有 RUNNING 任务
                self._poll_running_tasks()

            except Exception as e:
                print(f"⚠️ PollingWorker 轮询异常: {e}")

            time.sleep(self.poll_interval)

    def _poll_stale_tasks(self):
        """处理 stale RUNNING 任务"""
        threshold_time = datetime.now() - timedelta(minutes=self.STALE_THRESHOLD_MINUTES)
        stale_tasks = self.db_manager.get_stale_running_tasks(threshold_time)

        for task in stale_tasks:
            print(f"⚠️ 检测到 stale 任务: {task['task_id']} ({task['workflow_type']}), "
                  f"已运行 {(datetime.now() - task['started_at']).total_seconds()/60:.1f} 分钟")

            # 删除 stale 缓存，允许重新提交
            cache_key = self.db_manager.make_cache_key(
                task['workflow_type'], task['prompt'], task.get('reference_local_path')
            )
            self.db_manager.delete_cache(cache_key)

            # 判断是否可重试
            retry_count = task.get('retry_count', 0)
            if retry_count < self.MAX_RETRIES:
                self._retry_task(task)
            else:
                self.db_manager.update_task_status(
                    task['task_id'], 'FAILED', 
                    error_message=f'stale timeout, exceeded max retries ({self.MAX_RETRIES})'
                )

    def _poll_running_tasks(self):
        """轮询所有 RUNNING 状态的任务"""
        running_tasks = self.db_manager.get_running_tasks()

        if running_tasks:
            print(f"📡 轮询 {len(running_tasks)} 个 RUNNING 任务...")

        for task in running_tasks:
            try:
                # 检查任务是否真的在跑（可能已经是 stale 但还没被清理）
                started_at = task.get('started_at')
                if started_at:
                    if isinstance(started_at, str):
                        started_at = datetime.fromisoformat(started_at)
                    age = datetime.now() - started_at
                    if age > timedelta(minutes=self.STALE_THRESHOLD_MINUTES):
                        # 跳过，_poll_stale_tasks 会处理
                        continue

                result = self.client.wait_for_task(task['task_id'], max_wait=60)

                if result['status'] == 'SUCCESS':
                    self._handle_success(task, result)
                else:
                    self._handle_failure(task, result.get('errorMessage', 'unknown error'))

            except Exception as e:
                error_msg = str(e)
                print(f"❌ 轮询任务 {task['task_id']} 异常: {error_msg}")

                # 判断是否是可重试错误
                if self._is_retryable_error(error_msg):
                    retry_count = task.get('retry_count', 0)
                    if retry_count < self.MAX_RETRIES:
                        self._retry_task(task)
                    else:
                        self.db_manager.update_task_status(
                            task['task_id'], 'FAILED', 
                            error_message=f'max retries exceeded: {error_msg}'
                        )
                else:
                    self.db_manager.update_task_status(
                        task['task_id'], 'FAILED', 
                        error_message=f'polling error: {error_msg}'
                    )

    def _handle_success(self, task, result):
        """处理任务成功"""
        try:
            outputs = self.client.parse_output(result['result'])

            if not outputs:
                self.db_manager.update_task_status(
                    task['task_id'], 'FAILED', 
                    error_message='no output from task'
                )
                return

            workflow_type = task['workflow_type']
            task_db_id = task['id']

            if workflow_type == 'video':
                video_url = outputs[0].get('video_url') or outputs[0].get('url')
                if not video_url:
                    video_url = outputs[0].get('download_url')

                self._save_video_result(task, video_url)

            elif workflow_type == 'multiphoto':
                self._save_multiphoto_result(task, outputs)

            else:  # photo
                image_url = self._extract_image_url(outputs[0])
                self._save_photo_result(task, image_url)

            # 更新任务状态为 SUCCESS
            self.db_manager.update_task_status(task['task_id'], 'SUCCESS')

            # 更新缓存
            cache_key = self.db_manager.make_cache_key(
                task['workflow_type'], task['prompt'], task.get('reference_local_path')
            )
            # 获取 result_id（从刚才的保存结果中获取）
            results = self.db_manager.get_result_by_task_db_id(task_db_id)
            result_id = results[0]['id'] if results else None
            self.db_manager.update_cache_success(cache_key, result_id)

            # 通知下游依赖任务
            self._notify_dependent_tasks(task_db_id)

            print(f"✅ 任务完成: {task['task_id']} ({workflow_type})")

        except Exception as e:
            print(f"❌ 处理任务结果异常: {e}")
            self.db_manager.update_task_status(
                task['task_id'], 'FAILED', 
                error_message=f'handle success error: {str(e)}'
            )

    def _handle_failure(self, task, error_message):
        """处理任务失败"""
        print(f"❌ 任务失败: {task['task_id']} - {error_message}")

        retry_count = task.get('retry_count', 0)
        if self._is_retryable_error(error_message) and retry_count < self.MAX_RETRIES:
            self._retry_task(task)
        else:
            self.db_manager.update_task_status(
                task['task_id'], 'FAILED', 
                error_message=error_message
            )

    def _retry_task(self, task):
        """重试任务"""
        retry_count = task.get('retry_count', 0) + 1
        task_db_id = task['id']
        workflow_type = task['workflow_type']

        print(f"🔄 重试任务: {task['task_id']} (第 {retry_count}/{self.MAX_RETRIES} 次)")

        # 计算重试延迟
        delay = self.RETRY_DELAYS[min(retry_count - 1, len(self.RETRY_DELAYS) - 1)]
        print(f"⏳ 等待 {delay} 秒后重试...")
        time.sleep(delay)

        # 获取工作流 ID
        from utils.workflow_ids import WORKFLOW_IDS
        workflow_id = WORKFLOW_IDS.get(workflow_type)
        if not workflow_id:
            print(f"❌ 未知工作流类型: {workflow_type}")
            return

        # 重新获取参考图 URL（可能已过期）
        reference_url = task.get('reference_url')
        if task.get('reference_id'):
            ref = self.db_manager.get_reference_by_id(task['reference_id'])
            if ref and self.db_manager.is_reference_url_expired(ref['id']):
                print(f"🔄 参考图 URL 已过期，重新上传...")
                from core.reference_manager import ReferenceManager
                ref_manager = ReferenceManager(self.api_key, self.db_manager)
                reference_url = ref_manager.upload(ref['file_path'])
                self.db_manager.update_reference_url(ref['id'], reference_url)

        # 重新构建 node_info_list
        prompt = task.get('prompt')
        node_info_list = self._build_node_info(workflow_type, reference_url, prompt, task)

        try:
            new_task_id = self.client.submit_task(workflow_id, node_info_list)

            # 更新 DB 记录
            self.db_manager.update_task_task_id(task_db_id, new_task_id)
            self.db_manager.update_task_retry_count(task_db_id, retry_count)
            self.db_manager.update_task_status(new_task_id, 'RUNNING')

            # 更新缓存
            cache_key = self.db_manager.make_cache_key(
                task['workflow_type'], task['prompt'], task.get('reference_local_path')
            )
            self.db_manager.update_cache_running(cache_key, new_task_id)

            print(f"✅ 任务已重新提交: {new_task_id}")

        except Exception as e:
            print(f"❌ 重试提交失败: {e}")
            self.db_manager.update_task_status(
                task['task_id'], 'FAILED', 
                error_message=f'retry submit failed: {str(e)}'
            )

    def _build_node_info(self, workflow_type, reference_url, prompt, task=None):
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
            from generators.video_generator import VideoGenerator
            optimized_prompt = prompt
            if task:
                # 如果有原始 task，获取优化后的 prompt
                optimized_prompt = task.get('optimized_prompt', prompt)
            duration = 8  # 默认 8 秒
            return [
                {"nodeId": "13", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "36", "fieldName": "text", "fieldValue": optimized_prompt or prompt},
                {"nodeId": "15", "fieldName": "value", "fieldValue": str(duration)}
            ]
        elif workflow_type == 'prompt_photo':
            return [
                {"nodeId": "1", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "8", "fieldName": "text", "fieldValue": prompt}
            ]
        return []

    def _extract_image_url(self, output):
        """从输出中提取图片 URL"""
        return output.get('url') or output.get('image_url') or output.get('download_url')

    def _save_photo_result(self, task, image_url):
        """保存 Photo 结果到本地和数据库"""
        output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images')
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_id = task['task_id']
        local_path = os.path.join(output_dir, f"honny_{task_id}_{timestamp}.jpg")

        download_file(image_url, local_path)

        # 注入 EXIF
        from core.exif_manager import ExifManager
        exif_mgr = ExifManager()
        shot_at = datetime.now()
        local_path = exif_mgr.inject(local_path, shot_at)

        # 获取图片信息
        width, height = get_image_size(local_path)
        file_size = get_file_size(local_path)

        exif_data = {
            'phone_model': exif_mgr.phone_model,
            'gps_lat': exif_mgr.gps_coords[0],
            'gps_lon': exif_mgr.gps_coords[1],
            'shot_at': shot_at
        }

        # 保存到数据库
        result_id = self.db_manager.save_result(
            task['id'], 'image', image_url, local_path,
            width, height, file_size, exif_data
        )

        # 更新任务的本地路径
        self.db_manager.update_task_status(task['task_id'], 'RUNNING', local_path=local_path)

        print(f"💾 Photo 已保存: {local_path}")

    def _save_video_result(self, task, video_url):
        """保存 Video 结果到本地和数据库"""
        output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/videos')
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_id = task['task_id']
        local_path = os.path.join(output_dir, f"video_{task_id}_{timestamp}.mp4")

        download_file(video_url, local_path)

        file_size = get_file_size(local_path)

        result_id = self.db_manager.save_video_result(
            task['id'], local_path, duration=8, file_size=file_size
        )

        print(f"💾 Video 已保存: {local_path}")

    def _save_multiphoto_result(self, task, outputs):
        """保存 MultiPhoto 结果到本地和数据库"""
        output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images/multiphoto')
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        images = []
        for i, output in enumerate(outputs):
            url = self._extract_image_url(output)
            if not url:
                continue

            ext = os.path.splitext(url)[1] or '.png'
            task_id = task['task_id']
            local_path = os.path.join(output_dir, f"multiphoto_{i+1}_{task_id}_{timestamp}{ext}")
            download_file(url, local_path)

            # 注入 EXIF
            from core.exif_manager import ExifManager
            exif_mgr = ExifManager()
            shot_at = datetime.now()
            try:
                local_path = exif_mgr.inject(local_path, shot_at)
            except Exception as e:
                print(f"⚠️ EXIF 注入失败: {e}")

            width, height = get_image_size(local_path)

            images.append({
                'image_url': url,
                'local_path': local_path,
                'width': width,
                'height': height,
                'shot_at': shot_at,
                'exif_injected': True,
                'prompt': task.get('prompt', '')  # 复用 task 的 prompt
            })

        if images:
            set_id = self.db_manager.save_multiphoto_set(task['id'], task['prompt'], images)
            print(f"💾 MultiPhoto 已保存 {len(images)} 张，set_id={set_id}")

    def _notify_dependent_tasks(self, completed_task_id):
        """通知依赖该任务的下游任务"""
        dependents = self.db_manager.get_tasks_dependent_on(completed_task_id)

        for dep in dependents:
            self.db_manager.mark_reference_ready(dep['id'])
            print(f"📬 已通知下游任务 {dep['child_task_id']}，参考图已就绪")

    def _is_retryable_error(self, error_message):
        """判断错误是否可重试"""
        retryable_patterns = [
            'timeout', 'TIMEOUT', 'timed out',
            'rate limit', 'RATE_LIMIT', '429',
            'connection', 'CONNECTION', 'network',
            'internal error', 'INTERNAL_ERROR', '500',
            'service unavailable', '503',
            'CACHE_HIT_RUNNING',
        ]
        for pattern in retryable_patterns:
            if pattern in error_message:
                return True
        return False


# ============================================================
# 便捷启动函数
# ============================================================

_worker_instance = None

def start_worker(api_key=None, db_manager=None, poll_interval=30):
    """启动 PollingWorker 单例"""
    global _worker_instance

    if _worker_instance and _worker_instance.running:
        print("⚠️ PollingWorker 已运行，不再重复启动")
        return _worker_instance

    if api_key is None:
        # 从环境变量或配置文件获取
        api_key = os.environ.get('RUNNINGHUB_API_KEY')
        if not api_key:
            workspace_env = os.path.expanduser('~/.openclaw/workspace-companion2/.env')
            if os.path.exists(workspace_env):
                with open(workspace_env) as f:
                    for line in f:
                        if line.startswith('RUNNINGHUB_API_KEY='):
                            api_key = line.split('=')[1].strip()
                            break

    if not api_key:
        raise ValueError("未找到 RUNNINGHUB_API_KEY")

    _worker_instance = PollingWorker(api_key, db_manager, poll_interval)
    _worker_instance.start()
    return _worker_instance

def stop_worker():
    """停止 PollingWorker 单例"""
    global _worker_instance
    if _worker_instance:
        _worker_instance.stop()
        _worker_instance = None

def get_worker():
    """获取 PollingWorker 单例（如未启动则启动）"""
    global _worker_instance
    if _worker_instance is None:
        return start_worker()
    return _worker_instance