#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia RunningHub API 封装
版本：v1.0
日期：2026-05-18
"""

import os
import time
import requests
from datetime import datetime


class RunningHubClient:
    """RunningHub API 客户端"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://www.runninghub.cn"
        self.query_url = f"{self.base_url}/openapi/v2/query"
    
    def get_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
    
    def submit_task(self, workflow_id, node_info_list, instance_type='default', use_personal_queue='false'):
        """提交任务到 RunningHub"""
        run_url = f"{self.base_url}/openapi/v2/run/ai-app/{workflow_id}"
        
        payload = {
            "nodeInfoList": node_info_list,
            "instanceType": instance_type,
            "usePersonalQueue": use_personal_queue
        }
        
        for attempt in range(3):
            try:
                response = requests.post(
                    run_url, 
                    headers=self.get_headers(), 
                    json=payload, 
                    timeout=30
                )
                
                result = response.json()
                
                # 检查并发限制
                if result.get('errorCode') == '421':
                    print(f"⏳ 队列已满，10秒后重试 ({attempt + 1}/3)...")
                    time.sleep(10)
                    continue
                
                # 获取task_id
                task_id = result.get('taskId') or result.get('data', {}).get('taskId', '')
                if not task_id:
                    error_msg = result.get('errorMessage') or result.get('message') or 'Unknown error'
                    raise Exception(f"提交失败: {error_msg}")
                
                return task_id
                
            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    print(f"⚠️ 请求异常，5秒后重试: {e}")
                    time.sleep(5)
                    continue
                raise
        
        raise Exception("提交失败，已达最大重试次数")
    
    def query_task(self, task_id):
        """查询任务状态"""
        payload = {'taskId': task_id}
        
        try:
            response = requests.post(
                self.query_url, 
                headers=self.get_headers(), 
                json=payload, 
                timeout=30
            )
            
            return response.json()
            
        except Exception as e:
            return {'status': 'ERROR', 'error': str(e)}
    
    def wait_for_task(self, task_id, max_wait=1200, poll_interval=30):
        """等待任务完成
        
        Args:
            task_id: 任务ID
            max_wait: 最大等待时间（秒），默认20分钟，适合视频生成等长时间任务
            poll_interval: 轮询间隔（秒），默认30秒，降低网络开销避免超时
        """
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                return {'status': 'TIMEOUT', 'elapsed': elapsed}
            
            result = self.query_task(task_id)
            status = result.get('status', result.get('data', {}).get('status', 'UNKNOWN'))
            
            print(f"⏳ 任务状态: {status} (已等待 {int(elapsed)}s)")
            
            if status in ('SUCCESS', 'FAILED', 'ERROR', 'TIMEOUT'):
                return {
                    'status': status,
                    'elapsed': elapsed,
                    'result': result
                }
            
            time.sleep(poll_interval)
    
    def parse_output(self, result):
        """解析任务输出"""
        # 尝试从 data.outputs 获取
        outputs = result.get('data', {}).get('outputs', [])
        
        if not outputs:
            outputs = result.get('data', {}).get('results', [])
        
        # 也支持直接返回的 results（不在 data 里）
        if not outputs and 'results' in result:
            outputs = result['results']
        
        if not outputs and 'outputs' in result:
            outputs = result['outputs']
        
        return outputs