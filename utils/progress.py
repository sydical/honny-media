#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia 进度显示模块
版本：v1.0
日期：2026-05-18
"""

import sys
import time


class ProgressBar:
    """进度条显示"""
    
    def __init__(self, total=100, prefix='⏳', suffix='完成', width=30, stream=None):
        self.total = total
        self.prefix = prefix
        self.suffix = suffix
        self.width = width
        self.stream = stream or sys.stdout
        self.current = 0
    
    def update(self, current=None, suffix=None):
        """更新进度"""
        if current is not None:
            self.current = current
        if suffix is not None:
            self.suffix = suffix
        
        percent = int(self.current / self.total * 100) if self.total > 0 else 0
        filled = int(self.width * self.current / self.total) if self.total > 0 else 0
        bar = '█' * filled + '░' * (self.width - filled)
        
        self.stream.write(f'\r{self.prefix} [{bar}] {percent}% {self.suffix}')
        self.stream.flush()
    
    def finish(self, message='完成'):
        """完成进度条"""
        self.stream.write(f'\r{self.prefix} [{\"█\" * self.width}] 100% {message}     \n')
        self.stream.flush()


def print_step(message, emoji='📋'):
    """打印步骤信息"""
    print(f'{emoji} {message}')


def print_success(message):
    """打印成功信息"""
    print(f'✅ {message}')


def print_error(message):
    """打印错误信息"""
    print(f'❌ {message}')


def print_info(message):
    """打印普通信息"""
    print(f'{message}')


def print_progress(task_name, delay=0.5):
    """模拟进度显示（用于测试）"""
    steps = [
        ('正在连接...', 20),
        ('处理中...', 50),
        ('即将完成...', 80),
        ('完成', 100),
    ]
    
    for step_msg, percent in steps:
        print(f'\r⏳ {task_name}: {step_msg} [{percent}%]', end='', flush=True)
        time.sleep(delay)
    
    print(f'\r✅ {task_name} 完成!')