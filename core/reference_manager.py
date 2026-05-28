#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 参考图管理模块
版本：v1.1
日期：2026-05-27
变更：支持参考图自动追溯来源任务 + URL 过期检测
"""

import os
import requests
from datetime import datetime, timedelta


class ReferenceManager:
    """参考图管理器"""

    LOCAL_HTTP_BASE = "http://43.163.99.99"

    def __init__(self, api_key, db_manager=None):
        self.api_key = api_key
        self.db_manager = db_manager
        self.base_url = "https://www.runninghub.cn"
        self.upload_url = f"{self.base_url}/openapi/v2/media/upload/binary"

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    def upload(self, image_path, user_id=None):
        """上传图片到 RunningHub（支持自动追溯来源任务）

        流程：
        1. 判断是否为本地路径 → 构造 HTTP URL（跳过上传）
        2. 上传到 RunningHub，获取 remote_url
        3. 查找该文件是否是某次生成任务的产物（自动追溯）
        4. 建立 reference ↔ task 映射关系
        5. 保存参考图记录
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")

        # ✅ 本地路径直接用 HTTP URL，跳过上传
        if image_path.startswith('/root/.openclaw/'):
            relative_path = image_path[len('/root/.openclaw/'):]
            remote_url = f"{self.LOCAL_HTTP_BASE}/{relative_path}"
            print(f"🌐 使用本地HTTP URL（跳过上传）: {remote_url}")
            if self.db_manager:
                # 保存参考图记录（不追溯来源，避免重复查询）
                ref_id = self.db_manager.save_reference(
                    file_path=image_path,
                    remote_url=remote_url,
                    user_id=user_id,
                    source_task_id=None,
                    original_prompt=None
                )
                print(f"📝 参考图记录已保存 (id={ref_id})")
            return remote_url

        print(f"📤 正在上传参考图: {image_path}")

        # 1. 上传到 RunningHub
        remote_url = self._do_upload(image_path)

        # 2. 自动追溯来源任务
        source_task_db_id = None
        original_prompt = None

        if self.db_manager:
            # 查找该文件是否是某次生成任务的产物
            results = self.db_manager.find_result_by_local_path(image_path)

            if results:
                # 有关联记录，自动建立映射
                source_task_db_id = results[0]['task_db_id']
                task = self.db_manager.get_task_by_id(source_task_db_id)
                if task:
                    original_prompt = task.get('prompt')
                print(f"🔗 检测到参考图来源任务: task_db_id={source_task_db_id}, prompt={original_prompt[:30]}...")

            # 3. 保存参考图记录（含来源任务追溯信息）
            ref_id = self.db_manager.save_reference(
                file_path=image_path,
                remote_url=remote_url,
                user_id=user_id,
                source_task_id=source_task_db_id,
                original_prompt=original_prompt
            )

            # 4. 建立映射关系（支持多对一：同一张图可被多个下游任务引用）
            if source_task_db_id:
                # used_as_ref_for 留空，由调用方后续更新
                self.db_manager.save_reference_task_mapping(ref_id, source_task_db_id)

            print(f"📝 参考图记录已保存 (id={ref_id})")

        return remote_url

    def _do_upload(self, image_path):
        """执行实际上传到 RunningHub"""
        filename = os.path.basename(image_path)

        with open(image_path, 'rb') as f:
            files = {'file': (filename, f, 'image/png')}
            response = requests.post(self.upload_url, files=files, headers=self.get_headers(), timeout=120)

        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                remote_url = result['data'].get('url') or result['data'].get('download_url')
                print(f"✅ 参考图上传成功: {remote_url}")
                return remote_url
            else:
                raise Exception(f"上传失败: {result.get('errorMessage')}")
        else:
            raise Exception(f"上传请求失败: {response.status_code}, {response.text}")

    def reupload_if_expired(self, ref_id):
        """检查并重新上传过期的参考图"""
        if not self.db_manager:
            return None

        ref = self.db_manager.get_reference_by_id(ref_id)
        if not ref:
            return None

        # ✅ 本地 HTTP URL 不过期，直接返回
        if ref['remote_url'].startswith(self.LOCAL_HTTP_BASE):
            return ref['remote_url']

        # 检查 URL 是否过期
        expires_at = ref.get('expires_at')
        if expires_at:
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if datetime.now() < expires_at:
                # 未过期，无需重新上传
                return ref['remote_url']

        # 已过期，重新上传
        file_path = ref['file_path']
        if not os.path.exists(file_path):
            print(f"⚠️ 参考图文件已不存在: {file_path}")
            return None

        print(f"🔄 参考图 URL 已过期，重新上传: {file_path}")
        new_url = self._do_upload(file_path)

        # 更新数据库中的 URL
        self.db_manager.update_reference_url(ref_id, new_url)

        return new_url

    def upload_and_update_mapping(self, image_path, used_as_ref_for):
        """上传参考图并更新映射关系中的 used_as_ref_for

        Args:
            image_path: 本地文件路径
            used_as_ref_for: 被谁引用（'photo' / 'multiphoto' / 'video'）
        """
        if not self.db_manager:
            return self._do_upload(image_path)

        # 先上传
        remote_url = self._do_upload(image_path)

        # 查找刚保存的参考图记录（根据 file_path 和 remote_url）
        # 自动追溯来源
        results = self.db_manager.find_result_by_local_path(image_path)
        source_task_db_id = results[0]['task_db_id'] if results else None

        # 保存参考图记录
        ref_id = self.db_manager.save_reference(
            file_path=image_path,
            remote_url=remote_url,
            source_task_id=source_task_db_id,
            original_prompt=None
        )

        # 建立映射关系
        if source_task_db_id:
            self.db_manager.save_reference_task_mapping(ref_id, source_task_db_id, used_as_ref_for)

        return remote_url

    def find_avatar(self, user_dir):
        """查找用户目录下的 avatar 图片"""
        avatar_names = ['avatar.jpg', 'avatar.png', 'avatar.jpeg', 'avatar.gif',
                       '头像.jpg', '头像.png', 'photo.jpg', 'photo.png']

        # 首先检查指定的 avatar 名称
        for name in avatar_names:
            path = os.path.join(user_dir, name)
            if os.path.exists(path):
                return path

        # 扫描所有图片文件
        try:
            for f in os.listdir(user_dir):
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    path = os.path.join(user_dir, f)
                    if os.path.isfile(path) and os.getsize(path) > 10000:
                        return path
        except:
            pass

        return None

    def get_active_reference_url(self, user_id=None):
        """获取当前激活的参考图 URL（含过期检测）"""
        if self.db_manager:
            ref = self.db_manager.get_active_reference(user_id)
            if ref:
                # 检查是否过期
                if self.is_url_expired(ref):
                    print(f"⚠️ 激活的参考图 URL 已过期，重新上传...")
                    new_url = self.reupload_if_expired(ref['id'])
                    return new_url
                return ref['remote_url']
        return None

    def is_url_expired(self, reference_record):
        """检查参考图 URL 是否过期"""
        if not reference_record:
            return True

        expires_at = reference_record.get('expires_at')
        if not expires_at:
            # 没有过期时间，默认 24 小时
            uploaded_at = reference_record.get('uploaded_at')
            if uploaded_at:
                if isinstance(uploaded_at, str):
                    uploaded_at = datetime.fromisoformat(uploaded_at)
                expires_at = uploaded_at + timedelta(hours=24)
            else:
                return True

        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        return datetime.now() > expires_at