#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 推送通知模块 V2
生成完成后自动推送消息给用户

两种推送方式：
1. openclaw session send（实时推送，默认开启）
2. 写入通知队列（Agent主动查询）

使用方式：
    from honny_media import HonnyMedia
    
    # 方式1：开启自动推送（默认）
    honny = HonnyMedia()
    honny.auto_notify = True  # 或 generate(..., auto_notify=True)
    result = honny.generate("韩系穿搭", reference_path="avatar.jpg")
    # 生成完成后自动推送结果给用户
    
    # 方式2：手动调用
    from core.notifier import notify_complete
    notify_complete(result)
"""

import os
import sys
import json
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


class HonnyNotifier:
    """HonnyMedia 推送通知器"""
    
    DEFAULT_SESSION = "agent:companion"
    QUEUE_DIR = "/root/.openclaw/workspace-companion2/data/honny-media"
    NOTIFY_PREFIX = "notify_queue_"
    NOTIFY_SUFFIX = ".json"
    MAX_KEEP_DAYS = 1  # 超过1天的通知自动清理
    
    def __init__(self, target_session: str = None):
        self.target_session = target_session or self.DEFAULT_SESSION
        self.workspace = os.path.expanduser("~/.openclaw/workspace-companion2")
        self._ensure_queue_dir()
    
    def _ensure_queue_dir(self):
        os.makedirs(self.QUEUE_DIR, exist_ok=True)
    
    def _get_notify_path(self, timestamp: str) -> str:
        return os.path.join(self.QUEUE_DIR, f"{self.NOTIFY_PREFIX}{timestamp}{self.NOTIFY_SUFFIX}")
    
    def send_text(self, message: str, session: str = None, async_send: bool = True) -> bool:
        """发送文本消息
        
        Args:
            message: 消息内容
            session: 目标session（默认 agent:companion）
            async_send: 是否异步发送（默认True，避免阻塞）
        """
        target = session or self.target_session
        
        def _do_send():
            try:
                proc = subprocess.run(
                    ["openclaw", "session", "send", "--session", target, "--message", message],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    cwd=self.workspace
                )
                if proc.returncode == 0:
                    print(f"✅ 消息已发送: {message[:50]}...")
                else:
                    print(f"⚠️ 发送失败: {proc.stderr[:100]}")
            except subprocess.TimeoutExpired:
                print(f"⚠️ 发送超时")
            except Exception as e:
                print(f"⚠️ 发送异常: {e}")
        
        if async_send:
            threading.Thread(target=_do_send, daemon=True).start()
            return True
        else:
            _do_send()
            return True
    
    def queue_notification(self, notification: Dict[str, Any]) -> str:
        """写入通知队列（带自动清理）"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        notify_file = self._get_notify_path(timestamp)
        
        notification['created_at'] = datetime.now().isoformat()
        notification['notify_id'] = timestamp
        
        with open(notify_file, 'w', encoding='utf-8') as f:
            json.dump(notification, f, ensure_ascii=False, indent=2)
        
        # 顺便清理过期通知
        self._cleanup_expired()
        
        return notify_file
    
    def _cleanup_expired(self):
        """清理超过 MAX_KEEP_DAYS 的通知"""
        try:
            now = datetime.now()
            for fname in os.listdir(self.QUEUE_DIR):
                if not fname.startswith(self.NOTIFY_PREFIX) or not fname.endswith(self.NOTIFY_SUFFIX):
                    continue
                fpath = os.path.join(self.QUEUE_DIR, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if (now - mtime) > timedelta(days=self.MAX_KEEP_DAYS):
                        os.remove(fpath)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ 清理通知失败: {e}")
    
    def notify_photo_complete(self, result: Dict[str, Any]) -> bool:
        """通知Photo生成完成"""
        local_path = result.get('local_path')
        image_url = result.get('image_url')
        
        self.queue_notification({
            'type': 'photo_complete',
            'workflow_type': 'photo',
            'local_path': local_path,
            'image_url': image_url,
            'message': f"✅ Photo生成完成！{os.path.basename(local_path) if local_path else ''}"
        })
        
        msg = f"✅ Photo生成完成！"
        if local_path:
            msg += f"\n📁 {os.path.basename(local_path)}"
        if image_url:
            msg += f"\n🔗 {image_url[:80]}..."
        
        return self.send_text(msg)
    
    def notify_multiphoto_complete(self, result: Dict[str, Any]) -> bool:
        """通知MultiPhoto生成完成"""
        count = result.get('count', 0)
        local_paths = result.get('local_paths', [])
        urls = result.get('urls', [])
        
        self.queue_notification({
            'type': 'multiphoto_complete',
            'workflow_type': 'multiphoto',
            'count': count,
            'local_paths': local_paths,
            'urls': urls,
            'message': f"✅ MultiPhoto生成完成！({count}张)"
        })
        
        msg = f"✅ MultiPhoto生成完成！({count}张)"
        if local_paths:
            msg += f"\n📁 {os.path.basename(local_paths[0])}"
        if urls:
            msg += f"\n🔗 {urls[0][:80]}..."
        
        return self.send_text(msg)
    
    def notify_video_complete(self, result: Dict[str, Any]) -> bool:
        """通知Video生成完成"""
        local_path = result.get('local_path')
        duration = result.get('duration', 0)
        file_size = result.get('file_size', 0)
        
        self.queue_notification({
            'type': 'video_complete',
            'workflow_type': 'video',
            'local_path': local_path,
            'duration': duration,
            'file_size': file_size,
            'message': f"✅ Video生成完成！({duration}s, {self._format_size(file_size)})"
        })
        
        msg = f"✅ Video生成完成！"
        if local_path:
            msg += f"\n📁 {os.path.basename(local_path)}"
        msg += f"\n⏱️ {duration}s | 📦 {self._format_size(file_size)}"
        
        return self.send_text(msg)
    
    def notify_error(self, workflow_type: str, error: str, task_id: str = None) -> bool:
        """通知生成失败"""
        msg = f"❌ {workflow_type}生成失败"
        if task_id:
            msg += f" (task_id: {task_id})"
        msg += f"\n错误: {error[:100]}"
        
        self.queue_notification({
            'type': 'error',
            'workflow_type': workflow_type,
            'task_id': task_id,
            'error': error,
            'message': msg
        })
        
        return self.send_text(msg)
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f}MB"


# ===== 全局函数 =====

_notifier: Optional[HonnyNotifier] = None

def get_notifier() -> HonnyNotifier:
    """获取通知器单例"""
    global _notifier
    if _notifier is None:
        _notifier = HonnyNotifier()
    return _notifier

def notify_complete(result: Dict[str, Any]) -> bool:
    """通知生成完成（自动识别类型）"""
    notifier = get_notifier()
    workflow_type = result.get('workflow_type', 'unknown')
    
    handlers = {
        'photo': notifier.notify_photo_complete,
        'multiphoto': notifier.notify_multiphoto_complete,
        'video': notifier.notify_video_complete,
    }
    
    handler = handlers.get(workflow_type)
    if handler:
        return handler(result)
    else:
        return notifier.send_text(f"✅ 生成完成: {workflow_type}")

def notify_error(workflow_type: str, error: str, task_id: str = None) -> bool:
    """通知生成失败"""
    return get_notifier().notify_error(workflow_type, error, task_id)

def get_pending_notifications() -> List[Dict[str, Any]]:
    """获取待处理通知（自动清理过期）"""
    notifier = get_notifier()
    notifier._cleanup_expired()
    
    notify_files = sorted([
        f for f in os.listdir(notifier.QUEUE_DIR)
        if f.startswith(notifier.NOTIFY_PREFIX) and f.endswith(notifier.NOTIFY_SUFFIX)
    ], reverse=True)
    
    notifications = []
    for fname in notify_files[:10]:
        fpath = os.path.join(notifier.QUEUE_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                notifications.append(json.load(f))
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON解析失败 {fname}: {e}")
        except Exception as e:
            print(f"⚠️ 读取通知失败 {fname}: {e}")
    
    return notifications

def clear_notification(notify_id: str) -> bool:
    """删除指定通知"""
    notifier = get_notifier()
    notify_file = notifier._get_notify_path(notify_id)
    if os.path.exists(notify_file):
        os.remove(notify_file)
        return True
    return False


if __name__ == "__main__":
    # 测试
    notifier = get_notifier()
    notifier.send_text("🔔 HonnyMedia V2 通知测试")