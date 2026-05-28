#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia EXIF注入模块
版本：v1.1
日期：2026-05-19

修复：piexif.ImageExif -> piexif.ImageIFD
     piexif.GPSInfo -> piexif.GPSIFD
     正确分离 ImageIFD 和 ExifIFD 字段
"""

import os
import piexif
from datetime import datetime
from PIL import Image


# EXIF GPS 坐标库
GPS_COORDS = {
    "福州": (26.0753, 119.2964),
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "深圳": (22.5431, 114.0579),
    "成都": (30.5728, 104.0668),
}

# iPhone 16 Pro 参数
IPHONE_16_PRO = {
    'make': 'Apple',
    'model': 'iPhone 16 Pro',
    'software': '18.0',
    'exposure_time': (1, 120),  # tuple (numerator, denominator)
    'f_number': (178, 100),  # f/1.78
    'iso': 80,
    'focal_length': (686, 100),  # 6.86mm
    'white_balance': 0,
    'metering_mode': 5,
    'color_space': 1,
    'exif_version': b'0232',
    'flash': 16,
}


class ExifManager:
    """EXIF注入管理器"""
    
    def __init__(self, phone_model='iPhone 16 Pro', gps_city='福州'):
        self.phone_model = phone_model
        self.gps_city = gps_city
        self.gps_coords = GPS_COORDS.get(gps_city, GPS_COORDS['福州'])
        
        # 获取iPhone参数
        self.iphone_params = IPHONE_16_PRO.copy()
        self.iphone_params['model'] = phone_model
    
    def inject(self, image_path, shot_at=None, gps_city=None, phone_model=None):
        """注入EXIF信息到图片"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")
        
        # 更新参数
        if gps_city:
            self.gps_coords = GPS_COORDS.get(gps_city, self.gps_coords)
        if phone_model:
            self.iphone_params['model'] = phone_model
        
        if shot_at is None:
            shot_at = datetime.now()
        elif isinstance(shot_at, str):
            shot_at = datetime.fromisoformat(shot_at)
        
        # 读取图片
        img = Image.open(image_path)
        width, height = img.size
        
        # 构建EXIF数据
        exif_dict = self._build_exif_dict(shot_at, width, height)
        
        # 保存EXIF
        try:
            exif_bytes = piexif.dump(exif_dict)
            
            # 根据扩展名选择格式
            ext = os.path.splitext(image_path)[1].lower()
            if ext in ('.jpg', '.jpeg'):
                img.save(image_path, 'jpeg', exif=exif_bytes, quality=95)
            else:
                # 转换为jpg
                jpg_path = os.path.splitext(image_path)[0] + '.jpg'
                img.convert('RGB').save(jpg_path, 'jpeg', exif=exif_bytes, quality=95)
                os.remove(image_path)
                return jpg_path
            
            return image_path
        except Exception as e:
            print(f"⚠️ EXIF注入失败: {e}")
            return image_path
    
    def _build_exif_dict(self, shot_at, width, height):
        """构建EXIF字典"""
        # GPS坐标
        lat, lon = self.gps_coords
        gps_ifd = self._create_gps_ifd(lat, lon)
        
        # Exif IFD（曝光参数）
        exif_ifd = {
            piexif.ExifIFD.ExposureTime: self.iphone_params['exposure_time'],
            piexif.ExifIFD.FNumber: self.iphone_params['f_number'],
            piexif.ExifIFD.ISOSpeedRatings: self.iphone_params['iso'],
            piexif.ExifIFD.FocalLength: self.iphone_params['focal_length'],
            piexif.ExifIFD.WhiteBalance: self.iphone_params['white_balance'],
            piexif.ExifIFD.MeteringMode: self.iphone_params['metering_mode'],
            piexif.ExifIFD.ColorSpace: self.iphone_params['color_space'],
            piexif.ExifIFD.Flash: self.iphone_params['flash'],
            piexif.ExifIFD.ExifVersion: self.iphone_params['exif_version'],
            piexif.ExifIFD.DateTimeOriginal: shot_at.strftime('%Y:%m:%d %H:%M:%S'),
            piexif.ExifIFD.DateTimeDigitized: shot_at.strftime('%Y:%m:%d %H:%M:%S'),
        }
        
        # 0th IFD（主要信息）
        zeroth_ifd = {
            piexif.ImageIFD.Make: self.iphone_params['make'],
            piexif.ImageIFD.Model: self.iphone_params['model'],
            piexif.ImageIFD.Software: self.iphone_params['software'],
            piexif.ImageIFD.DateTime: shot_at.strftime('%Y:%m:%d %H:%M:%S'),
            piexif.ImageIFD.Orientation: 1,
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
            piexif.ImageIFD.ResolutionUnit: 2,
        }
        
        # 1st IFD（缩略图）
        first_ifd = {
            piexif.ImageIFD.Compression: 6,
            piexif.ImageIFD.XResolution: (72, 1),
            piexif.ImageIFD.YResolution: (72, 1),
            piexif.ImageIFD.ResolutionUnit: 2,
        }
        
        # 组装
        exif_dict = {
            "0th": zeroth_ifd,
            "Exif": exif_ifd,
            "GPS": gps_ifd,
            "1st": first_ifd
        }
        
        return exif_dict
    
    def _create_gps_ifd(self, lat, lon):
        """创建GPS IFD数据"""
        lat_hemisphere = 'N' if lat >= 0 else 'S'
        lon_hemisphere = 'E' if lon >= 0 else 'W'
        
        lat = abs(lat)
        lon = abs(lon)
        
        # 转换度分秒
        lat_deg = int(lat)
        lat_min = int((lat - lat_deg) * 60)
        lat_sec = (lat - lat_deg - lat_min / 60) * 3600
        
        lon_deg = int(lon)
        lon_min = int((lon - lon_deg) * 60)
        lon_sec = (lon - lon_deg - lon_min / 60) * 3600
        
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: lat_hemisphere.encode('ascii'),
            piexif.GPSIFD.GPSLatitude: ((lat_deg, 1), (lat_min, 1), (int(lat_sec * 100), 100)),
            piexif.GPSIFD.GPSLongitudeRef: lon_hemisphere.encode('ascii'),
            piexif.GPSIFD.GPSLongitude: ((lon_deg, 1), (lon_min, 1), (int(lon_sec * 100), 100)),
            piexif.GPSIFD.GPSAltitudeRef: 0,
            piexif.GPSIFD.GPSAltitude: (0, 1),
        }
        
        return gps_ifd
    
    def inject_batch(self, image_paths, shot_at=None, gps_city=None):
        """批量注入EXIF"""
        results = []
        for path in image_paths:
            try:
                result_path = self.inject(path, shot_at, gps_city)
                results.append({'path': result_path, 'success': True})
            except Exception as e:
                results.append({'path': path, 'success': False, 'error': str(e)})
        
        return results