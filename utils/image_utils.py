#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 图片处理工具
版本：v1.0
日期：2026-05-18
"""

import os
import hashlib
from PIL import Image
from datetime import datetime


def download_file(url, output_path, timeout=60):
    """下载文件到本地"""
    import requests
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        f.write(response.content)
    
    return output_path


def get_image_size(image_path):
    """获取图片尺寸"""
    try:
        with Image.open(image_path) as img:
            return img.size  # (width, height)
    except:
        return None, None


def get_file_size(file_path):
    """获取文件大小"""
    return os.path.getsize(file_path) if os.path.exists(file_path) else 0


def split_grid_image(image_path, layout='2x2', output_dir=None):
    """切割网格图为多张图片
    
    Args:
        image_path: 网格图路径
        layout: 布局，如 '2x2', '3x3', '1x4'
        output_dir: 输出目录
    
    Returns:
        list: 切割后的图片路径列表
    """
    # 解析布局
    rows, cols = map(int, layout.lower().split('x'))
    total = rows * cols
    
    # 确定输出目录
    if output_dir is None:
        output_dir = os.path.dirname(image_path)
    
    # 生成文件名
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    
    # 打开图片
    img = Image.open(image_path)
    width, height = img.size
    
    # 计算每格尺寸
    cell_width = width // cols
    cell_height = height // rows
    
    images = []
    
    for i in range(total):
        row = i // cols
        col = i % cols
        
        left = col * cell_width
        top = row * cell_height
        right = left + cell_width
        bottom = top + cell_height
        
        # 切割
        cell_img = img.crop((left, top, right, bottom))
        
        # 保存
        output_path = os.path.join(output_dir, f"{base_name}_{i+1}_{timestamp}.jpg")
        cell_img.save(output_path, 'jpeg', quality=95)
        
        images.append({
            'index': i,
            'path': output_path,
            'width': cell_width,
            'height': cell_height
        })
    
    return images


def create_grid_image(image_paths, layout='2x2', output_path=None):
    """将多张图片合并为网格图
    
    Args:
        image_paths: 图片路径列表
        layout: 布局，如 '2x2', '3x3'
        output_path: 输出路径
    
    Returns:
        str: 网格图路径
    """
    rows, cols = map(int, layout.lower().split('x'))
    
    if output_path is None:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        output_path = f"grid_{layout}_{timestamp}.jpg"
    
    # 打开所有图片
    images = [Image.open(p) for p in image_paths]
    
    # 获取每张图片的尺寸
    sizes = [img.size for img in images]
    
    # 使用第一张图片的尺寸作为基准
    cell_width, cell_height = sizes[0]
    
    # 计算网格尺寸
    grid_width = cell_width * cols
    grid_height = cell_height * rows
    
    # 创建网格图
    grid_img = Image.new('RGB', (grid_width, grid_height), (255, 255, 255))
    
    for i, img in enumerate(images):
        row = i // cols
        col = i % cols
        
        # 调整图片尺寸（如果有不同的）
        if img.size != (cell_width, cell_height):
            img = img.resize((cell_width, cell_height), Image.LANCZOS)
        
        x = col * cell_width
        y = row * cell_height
        
        grid_img.paste(img, (x, y))
    
    grid_img.save(output_path, 'jpeg', quality=95)
    
    return output_path


def calculate_hash(file_path):
    """计算文件MD5"""
    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            md5.update(chunk)
    return md5.hexdigest()