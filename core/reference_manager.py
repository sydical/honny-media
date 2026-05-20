#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 参考图管理模块
版本：v1.0
日期：2026-05-18
"""

import os
import requests
from datetime import datetime


class ReferenceManager:
    """参考图管理器"""
    
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
        """上传图片到 RunningHub"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")
        
        print(f"📤 正在上传参考图: {image_path}")
        
        filename = os.path.basename(image_path)
        
        with open(image_path, 'rb') as f:
            files = {'file': (filename, f, 'image/png')}
            response = requests.post(self.upload_url, files=files, headers=self.get_headers(), timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                remote_url = result['data'].get('url') or result['data'].get('download_url')
                print(f"✅ 参考图上传成功: {remote_url}")
                
                # 保存到数据库
                if self.db_manager:
                    ref_id = self.db_manager.save_reference(image_path, remote_url, user_id)
                    print(f"📝 参考图记录已保存 (id={ref_id})")
                
                return remote_url
            else:
                raise Exception(f"上传失败: {result.get('errorMessage')}")
        else:
            raise Exception(f"上传请求失败: {response.status_code}, {response.text}")
    
    def find_avatar(self, user_dir):
        """查找用户目录下的 avatar 图片"""
        avatar_names = ['avatar.jpg', 'avatar.png', 'avatar.jpeg', 'avatar.gif',
                       '头像.jpg', '头像.png', 'photo.jpg', 'photo.png']
        
        common_images = ['photo.jpg', 'photo.png', 'photo.jpeg', 'img.jpg', 'img.png',
                       'photo_1.jpg', 'photo_1.png', 'p1.jpg', 'p1.png']
        
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
        """获取当前激活的参考图URL"""
        if self.db_manager:
            ref = self.db_manager.get_active_reference(user_id)
            if ref:
                return ref['remote_url']
        return None
    
    def is_url_expired(self, reference_record):
        """检查参考图URL是否过期"""
        if not reference_record:
            return True
        
        expires_at = reference_record.get('expires_at')
        if not expires_at:
            return True
        
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        
        return datetime.now() > expires_at