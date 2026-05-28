#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 需求队列执行器
版本：v1.0
日期：2026-05-28
职责：单线程顺序执行 demand_tasks，一个完成再提交下一个
"""

import os
import sys
import time
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.demand_manager import DemandManager
from core.notifier import HonnyNotifier
from utils.runninghub import RunningHubClient
from utils.image_utils import center_crop


# 最大重试次数
MAX_RETRIES = 3

# 轮询间隔（秒）
POLL_INTERVAL = 15

# RunningHub 最大等待时间（秒）
MAX_WAIT_SECONDS = 1200


class DemandQueueWorker:
    """单线程顺序执行引擎"""

    def __init__(self, api_key=None, db_manager=None, poll_interval=POLL_INTERVAL):
        if api_key is None:
            api_key = self._load_api_key()

        self.api_key = api_key
        self.poll_interval = poll_interval
        self.demand_manager = DemandManager(db_manager)
        self.notifier = HonnyNotifier()
        self.client = RunningHubClient(self.api_key)

        self._running = False
        self._thread = None
        self._stop_event = threading.Event()

    def _load_api_key(self):
        """从环境变量或 .env 加载 API Key"""
        api_key = os.environ.get('RUNNINGHUB_API_KEY')
        if api_key:
            return api_key

        env_path = os.path.expanduser('~/.openclaw/workspace-companion2/.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith('RUNNINGHUB_API_KEY='):
                        return line.split('=', 1)[1].strip()
        raise ValueError("未找到 RUNNINGHUB_API_KEY")

    def start(self):
        """启动 Worker（后台线程）"""
        if self._running:
            print("⚠️ DemandQueueWorker 已在运行")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"🚀 DemandQueueWorker 已启动（poll_interval={self.poll_interval}s）")

    def stop(self):
        """停止 Worker"""
        if not self._running:
            return

        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("🛑 DemandQueueWorker 已停止")

    def _run_loop(self):
        """主循环"""
        while not self._stop_event.is_set():
            try:
                self._process_next()
            except Exception as e:
                print(f"⚠️ 处理任务时出错: {e}")

            # 等待下一个轮询周期
            self._stop_event.wait(timeout=self.poll_interval)

    def _process_next(self):
        """处理下一个待执行任务"""
        # 获取最早 pending 的任务
        task = self.demand_manager.get_next_queued_task()
        if not task:
            return

        demand_id = task['demand_id']
        task_no = task['task_no']
        workflow_type = task['workflow_type']
        prompt = task['prompt']
        reference_url = task['reference_url']
        task_id_db = task['id']

        print(f"\n📋 [{demand_id}/{task_no}] 开始执行 {workflow_type}")
        print(f"   提示词：{prompt[:60]}...")
        print(f"   参考图：{reference_url}")

        # 更新状态为 RUNNING
        self.demand_manager.update_task_status(task_id_db, 'RUNNING')
        self._notify_progress(demand_id, task_no, 'RUNNING')

        try:
            # 获取前序任务结果（用于 video 引用 photo 的输出）
            prev_result = None
            if task_no > 1:
                prev_result = self.demand_manager.get_prev_task_result(demand_id, task_no)
                if prev_result and prev_result.get('result_data'):
                    prev_local = prev_result['result_data'].get('local_path')
                    if prev_local and prev_local.startswith('/root/.openclaw/'):
                        relative = prev_local[len('/root/.openclaw/'):]
                        reference_url = f"{self._get_http_base()}/{relative}"

            # 提交到 RunningHub
            result = self._submit_and_wait(
                workflow_type, prompt, reference_url, task_id_db
            )

            # 成功
            self._on_success(demand_id, task_no, task_id_db, workflow_type, result)
            self._notify_progress(demand_id, task_no, 'SUCCESS', result)

        except Exception as e:
            error_msg = str(e)
            print(f"❌ [{demand_id}/{task_no}] {workflow_type} 失败: {error_msg}")

            # 失败处理
            self.demand_manager.update_task_status(task_id_db, 'FAILED', error_message=error_msg)
            self.demand_manager.update_task_retry(task_id_db)

            # 检查是否可重试
            task = self.demand_manager.get_demand_tasks(demand_id)[task_no - 1]
            if task['retry_count'] < MAX_RETRIES:
                # 重置为 QUEUED，等待下次循环重试
                self.demand_manager.update_task_status(task_id_db, 'QUEUED')
                print(f"   🔄 将重试（{task['retry_count'] + 1}/{MAX_RETRIES}）")
            else:
                print(f"   ⛔ 超过最大重试次数，标记为失败")
                self._notify_progress(demand_id, task_no, 'FAILED', None, error_msg)
                # demand 也标记为失败
                self._mark_demand_failed(demand_id)

    def _submit_and_wait(self, workflow_type, prompt, reference_url, task_id_db):
        """提交任务到 RunningHub 并等待完成"""
        from core.workflow_dispatcher import WORKFLOW_IDS
        from core.reference_manager import ReferenceManager

        workflow_id = WORKFLOW_IDS.get(workflow_type)
        if not workflow_id:
            raise Exception(f"未知工作流类型: {workflow_type}")

        # 构建 node_info_list
        if workflow_type == 'photo':
            node_info = [
                {"nodeId": "1", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "8", "fieldName": "text", "fieldValue": prompt}
            ]
        elif workflow_type == 'multiphoto':
            node_info = [
                {"nodeId": "157", "fieldName": "image", "fieldValue": reference_url}
            ]
        elif workflow_type == 'video':
            node_info = [
                {"nodeId": "13", "fieldName": "image", "fieldValue": reference_url},
                {"nodeId": "36", "fieldName": "text", "fieldValue": prompt},
                {"nodeId": "15", "fieldName": "value", "fieldValue": "8"}
            ]
        else:
            raise Exception(f"不支持的工作流: {workflow_type}")

        # 提交任务
        print(f"   📤 提交到 RunningHub...")
        rh_task_id = self.client.submit_task(workflow_id, node_info)

        # 更新 db 中的 task_id
        self.demand_manager.set_task_task_id(task_id_db, rh_task_id)
        print(f"   🆔 RunningHub task_id: {rh_task_id}")

        # 轮询等待
        print(f"   ⏳ 等待完成...")
        wait_result = self.client.wait_for_task(rh_task_id, max_wait=MAX_WAIT_SECONDS)

        if wait_result['status'] != 'SUCCESS':
            raise Exception(f"任务失败: {wait_result.get('result', {}).get('errorMessage', 'Unknown')}")

        # 解析输出
        outputs = wait_result.get('result', {}).get('results', [])
        if not outputs:
            raise Exception("未获取到输出结果")

        # 提取结果
        return self._parse_output(workflow_type, outputs, rh_task_id)

    def _parse_output(self, workflow_type, outputs, rh_task_id):
        """解析 RunningHub 输出"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if workflow_type == 'photo':
            url = outputs[0].get('url') or outputs[0].get('image_url') or outputs[0].get('download_url', '')
            if not url:
                raise Exception("未获取到图片 URL")

            # 下载到本地
            output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images')
            os.makedirs(output_dir, exist_ok=True)
            local_path = os.path.join(output_dir, f"honny_{rh_task_id}_{timestamp}.jpg")

            self._download_file(url, local_path)

            return {
                'type': 'image',
                'url': url,
                'local_path': local_path,
            }

        elif workflow_type == 'multiphoto':
            # 多图输出
            output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/images/multiphoto')
            os.makedirs(output_dir, exist_ok=True)

            images = []
            for i, output in enumerate(outputs):
                url = output.get('url') or output.get('image_url') or output.get('download_url', '')
                if not url:
                    continue

                ext = os.path.splitext(url)[1] or '.png'
                local_path = os.path.join(output_dir, f"multiphoto_{i+1}_{rh_task_id}_{timestamp}{ext}")
                self._download_file(url, local_path)

                # 等比裁切为 720×1280
                try:
                    local_path = center_crop(local_path, width=720, height=1280)
                except Exception as e:
                    print(f"   ⚠️ 裁切失败: {e}")

                images.append({
                    'index': i + 1,
                    'url': url,
                    'local_path': local_path,
                })

            return {
                'type': 'multiphoto',
                'images': images,
                'local_paths': [img['local_path'] for img in images],
            }

        elif workflow_type == 'video':
            url = outputs[0].get('video_url') or outputs[0].get('url') or outputs[0].get('download_url', '')
            if not url:
                raise Exception("未获取到视频 URL")

            output_dir = os.path.expanduser('~/.openclaw/workspace-companion2/data/videos')
            os.makedirs(output_dir, exist_ok=True)
            local_path = os.path.join(output_dir, f"video_{rh_task_id}_{timestamp}.mp4")

            self._download_file(url, local_path)

            return {
                'type': 'video',
                'url': url,
                'local_path': local_path,
                'duration': 8,
            }

        raise Exception(f"未知工作流类型: {workflow_type}")

    def _download_file(self, url, output_path):
        """下载文件"""
        import requests
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(r.content)
        print(f"   ✅ 已保存：{output_path}")

    def _get_http_base(self):
        """获取本地 HTTP 服务器地址"""
        from core.reference_manager import ReferenceManager
        return ReferenceManager.LOCAL_HTTP_BASE

    def _on_success(self, demand_id, task_no, task_id_db, workflow_type, result):
        """任务成功回调"""
        self.demand_manager.update_task_status(task_id_db, 'SUCCESS', result_data=result)

        # 检查是否所有任务都完成
        demand, tasks = self.demand_manager.get_progress(demand_id)
        if demand['status'] == 'SUCCESS':
            print(f"\n🎉 需求 {demand_id} 全部完成！")
            self._notify_complete(demand_id, result)

    def _mark_demand_failed(self, demand_id):
        """标记 demand 为失败"""
        conn = self.demand_manager.db.conn
        conn.execute(
            "UPDATE demands SET status='FAILED', updated_at=? WHERE id=?",
            (datetime.now().isoformat(), demand_id)
        )
        conn.commit()

    # ==================== 通知相关 ====================

    def _notify_progress(self, demand_id, task_no, status, result=None, error_msg=None):
        """推送进度通知"""
        demand, tasks = self.demand_manager.get_progress(demand_id)
        total = len(tasks)

        status_text = {
            'RUNNING': '执行中',
            'SUCCESS': '完成',
            'FAILED': '失败',
        }.get(status, status)

        if status == 'RUNNING':
            msg = f"📋 [{task_no}/{total}] {tasks[task_no-1]['workflow_type']} → {status_text} ⏳"
        elif status == 'SUCCESS':
            msg = f"✅ [{task_no}/{total}] {tasks[task_no-1]['workflow_type']} → {status_text}"
            # 加上结果链接
            if result and result.get('local_path'):
                url = self._local_to_http(result['local_path'])
                if url:
                    msg += f"\n🔗 {url}"
            # 如果还有后续任务
            if task_no < total:
                next_task = tasks[task_no]
                msg += f"\n⏳ 下一步：{next_task['workflow_type']} 执行中..."
        elif status == 'FAILED':
            msg = f"❌ [{task_no}/{total}] {tasks[task_no-1]['workflow_type']} → {status_text}"
            if error_msg:
                msg += f"\n原因：{error_msg}"

        self.notifier.send(msg)

    def _notify_complete(self, demand_id, final_result):
        """推送完成通知"""
        demand, tasks = self.demand_manager.get_progress(demand_id)

        lines = [f"🎉 需求 {demand_id} 全部完成！\n"]

        for task in tasks:
            emoji = {'photo': '📸', 'multiphoto': '🖼️', 'video': '🎬'}.get(task['workflow_type'], '📋')
            lines.append(f"{emoji} {task['workflow_type']} → SUCCESS")

            # 加上结果链接
            result_data = task.get('result_data')
            if result_data:
                try:
                    import json
                    result_data = json.loads(result_data)
                except Exception:
                    pass
                local_path = result_data.get('local_path') if isinstance(result_data, dict) else None
                if local_path:
                    url = self._local_to_http(local_path)
                    if url:
                        lines.append(f"   🔗 {url}")

        self.notifier.send('\n'.join(lines))

    def _local_to_http(self, local_path):
        """将本地路径转为 HTTP URL"""
        if local_path and local_path.startswith('/root/.openclaw/'):
            relative = local_path[len('/root/.openclaw/'):]
            return f"{self._get_http_base()}/{relative}"
        return None


# ==================== 入口 ====================

def start_worker(api_key=None, poll_interval=POLL_INTERVAL):
    """启动 Worker"""
    worker = DemandQueueWorker(api_key=api_key, poll_interval=poll_interval)
    worker.start()
    return worker


if __name__ == '__main__':
    import signal

    worker = start_worker()

    # 优雅退出
    def signal_handler(signum, frame):
        print("\n🛑 收到退出信号...")
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 主线程阻塞
    print("📋 DemandQueueWorker 运行中，按 Ctrl+C 退出")
    while True:
        time.sleep(1)