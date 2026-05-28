#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 主入口模块
版本：v1.2
日期：2026-05-27
变更：DB 先行流程 + async_mode 支持 + PollingWorker 后台守护
"""

import os
import sys

# 确保可以导入子模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入核心模块（使用绝对导入）
from db.db_manager import HonnyDBManager, get_db_manager
from db.schema import get_schema_sql, get_init_data_sql
from core.workflow_dispatcher import WorkflowDispatcher, detect_workflow
from core.reference_manager import ReferenceManager
from core.exif_manager import ExifManager, GPS_COORDS, IPHONE_16_PRO
from core.cache_manager import CacheManager
from utils.runninghub import RunningHubClient
from utils.image_utils import download_file, split_grid_image, get_image_size, get_file_size
from core.notifier import HonnyNotifier, notify_complete

# 延迟导入 PhotoToVideoPipeline（避免循环依赖）
def _get_photo_to_video_pipeline():
    try:
        from scripts.photo_to_video_pipeline import PhotoToVideoPipeline
        return PhotoToVideoPipeline
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))
        from photo_to_video_pipeline import PhotoToVideoPipeline
        return PhotoToVideoPipeline


def __getattr__(name):
    if name == 'PhotoToVideoPipeline':
        return _get_photo_to_video_pipeline()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class HonnyMedia:
    """HonnyMedia 主类 - 统一媒体生成工具"""

    def __init__(self, api_key=None, db_manager=None, start_worker=False, poll_interval=30):
        """初始化

        Args:
            api_key: RunningHub API密钥（可选，从环境变量或 .env 读取）
            db_manager: 数据库管理器（可选）
            start_worker: 是否启动后台 PollingWorker（默认 False）
            poll_interval: 轮询间隔（秒），默认 30
        """
        # 获取 API Key
        if api_key is None:
            api_key = self._get_api_key()

        if not api_key:
            raise ValueError("未找到 RUNNINGHUB_API_KEY，请配置环境变量或 .env 文件")

        self.api_key = api_key
        self.db_manager = db_manager or get_db_manager()
        self.dispatcher = WorkflowDispatcher(self.api_key, self.db_manager)
        self.exif_manager = ExifManager()
        self.notifier = HonnyNotifier()
        self._auto_notify = True
        self._worker = None

        # 可选：启动后台 PollingWorker
        if start_worker:
            self.start_worker(poll_interval=poll_interval)

    def _get_api_key(self):
        """从环境变量或配置文件获取 API Key"""
        api_key = os.environ.get('RUNNINGHUB_API_KEY')

        if not api_key:
            workspace_env = os.path.expanduser('~/.openclaw/workspace-companion2/.env')
            if os.path.exists(workspace_env):
                with open(workspace_env) as f:
                    for line in f:
                        if line.startswith('RUNNINGHUB_API_KEY='):
                            api_key = line.split('=')[1].strip()
                            break

        return api_key

    def start_worker(self, poll_interval=30):
        """启动后台 PollingWorker 守护线程"""
        if self._worker and self._worker.running:
            print("⚠️ PollingWorker 已在运行")
            return self._worker

        from workers.polling_worker import start_worker as _start_worker
        self._worker = _start_worker(
            api_key=self.api_key,
            db_manager=self.db_manager,
            poll_interval=poll_interval
        )
        return self._worker

    def stop_worker(self):
        """停止后台 PollingWorker"""
        if self._worker:
            from workers.polling_worker import stop_worker as _stop_worker
            _stop_worker()
            self._worker = None

    def generate(self, prompt, reference_path=None, workflow=None, notify=False, auto_notify=False, 
                 async_mode=False, **kwargs):
        """生成媒体内容

        Args:
            prompt: 提示词/描述
            reference_path: 参考图路径（可选）
            workflow: 工作流类型 ('photo', 'multiphoto', 'video', None=自动识别)
            notify: 是否推送通知（当次生成后推送）
            auto_notify: 是否开启自动推送（后续生成都推送）
            async_mode: 是否异步模式（只提交不等待，后台由 PollingWorker 轮询）
            **kwargs: 其他参数（如 duration, inject_exif 等）

        Returns:
            dict: 生成结果
        """
        # 更新自动推送设置
        if auto_notify:
            self._auto_notify = True

        # 检测工作流类型
        if workflow is None:
            workflow_type = detect_workflow(prompt)
        else:
            workflow_type = workflow

        # 调用分发器生成
        result = self.dispatcher.dispatch(
            prompt=prompt,
            reference_path=reference_path,
            workflow_type=workflow_type,
            async_mode=async_mode,
            **kwargs
        )

        # 添加 workflow_type 到 result（方便通知）
        result['workflow_type'] = workflow_type

        # 推送通知（同步模式下）
        should_notify = notify or self._auto_notify
        if should_notify and result.get('status') == 'success':
            try:
                notify_complete(result)
            except Exception as e:
                print(f"⚠️ 推送通知失败: {e}")

        return result

    def photo(self, prompt, reference_path=None, async_mode=False, **kwargs):
        """生成单张图片"""
        return self.generate(prompt, reference_path, 'photo', async_mode=async_mode, **kwargs)

    def multiphoto(self, prompt, reference_path=None, async_mode=False, **kwargs):
        """生成多图套装"""
        return self.generate(prompt, reference_path, 'multiphoto', async_mode=async_mode, **kwargs)

    def video(self, prompt, reference_path=None, async_mode=False, **kwargs):
        """生成视频"""
        return self.generate(prompt, reference_path, 'video', async_mode=async_mode, **kwargs)

    def prompt_photo(self, prompt, reference_path=None, async_mode=False, **kwargs):
        """分镜生图 - 根据多段分镜提示词生成人物一致性多场景多视角图片"""
        return self.generate(prompt, reference_path, 'prompt_photo', async_mode=async_mode, **kwargs)

    def get_stats(self, days=7):
        """获取统计信息"""
        return self.db_manager.get_stats(days)

    def get_gallery(self, workflow=None, limit=50):
        """获取图片库"""
        return self.db_manager.get_gallery(workflow, limit)

    def cleanup(self, days=30):
        """清理过期数据
        
        删除 30 天前的本地文件和 DB 记录（按正确顺序）。
        
        Args:
            days: 保留天数，默认 30 天
            
        Returns:
            dict: 清理统计
        """
        from scripts.cleanup_media import MediaCleaner
        cleaner = MediaCleaner(self.db_manager)
        return cleaner.cleanup(days)

    def cleanup_dry_run(self, days=30):
        """预览清理内容（不实际删除）"""
        from scripts.cleanup_media import MediaCleaner
        cleaner = MediaCleaner(self.db_manager)
        return cleaner.dry_run(days)

    def set_default_reference(self, file_path):
        """设置默认参考图"""
        ref_mgr = ReferenceManager(self.api_key, self.db_manager)
        return ref_mgr.upload(file_path)

    def get_default_reference(self):
        """获取当前默认参考图"""
        return self.db_manager.get_active_reference()

    def photo_to_video(self, photo_prompt, reference_path=None, duration=8, async_mode=False, **kwargs):
        """Photo → Video 一键生成

        将照片提示词转换为视频分镜，使用生成的照片作为视频首帧/关键帧。
        """
        pipeline = PhotoToVideoPipeline()

        parsed = pipeline.parse_photo_prompt(photo_prompt)
        storyboard = pipeline.build_storyboard(parsed, duration=duration)

        print(f"📋 Photo Prompt 解析完成:")
        print(f"   人物: {parsed['person']}")
        print(f"   服装: {parsed['clothing']}")
        print(f"   场景: {parsed['scene']}")
        print(f"   风格: {parsed['style']}")
        print(f"\n📝 生成 Storyboard:\n{storyboard}")

        # 生成照片（关键帧）
        print(f"\n📸 生成照片（关键帧）...")
        photo_result = self.photo(prompt=photo_prompt, reference_path=reference_path, **kwargs)

        if photo_result.get('cache_hit') and 'result' in photo_result:
            photo_local_path = photo_result['result'].get('local_path')
        else:
            photo_local_path = photo_result.get('local_path')

        if not photo_local_path:
            raise Exception("照片生成失败，无法继续视频生成")

        print(f"✅ 照片生成完成: {photo_local_path}")

        # 生成视频（使用照片作为关键帧）
        print(f"\n🎬 生成视频（使用照片作为首帧）...")
        video_result = self.video(
            prompt=storyboard,
            reference_path=photo_local_path,
            duration=duration,
            async_mode=async_mode,
            **kwargs
        )
        print(f"✅ 视频生成完成: {video_result.get('local_path')}")

        return {
            'photo_result': photo_result,
            'video_result': video_result,
            'storyboard': storyboard,
            'parsed_prompt': parsed
        }


# 模块版本
__version__ = 'v1.2'
__all__ = [
    'HonnyMedia',
    'HonnyDBManager',
    'get_db_manager',
    'detect_workflow',
    'ReferenceManager',
    'ExifManager',
    'CacheManager',
    'RunningHubClient',
    'PhotoToVideoPipeline',
    'GPS_COORDS',
    'IPHONE_16_PRO',
    'download_file',
    'split_grid_image',
    'get_image_size',
    'get_file_size'
]