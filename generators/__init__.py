#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia Generators 模块

⚠️ DEPRECATED (2026-05-27)
这些生成器已被 workflow_dispatcher 替代，不再被主流程调用。
保留供独立调用场景，2026-07 后移除。

引用方式：
    from generators.photo_generator import PhotoGenerator
    from generators.multiphoto_generator import MultiPhotoGenerator
    from generators.video_generator import VideoGenerator
"""

import os as _os
import warnings as _warnings

_deprecated_paths = [
    _os.path.join(_os.path.dirname(__file__), 'photo_generator.py'),
    _os.path.join(_os.path.dirname(__file__), 'multiphoto_generator.py'),
    _os.path.join(_os.path.dirname(__file__), 'video_generator.py'),
    _os.path.join(_os.path.dirname(__file__), 'prompt_photo_generator.py'),
]

def __getattr__(name):
    if name in ('PhotoGenerator', 'MultiPhotoGenerator', 'VideoGenerator', 'PromptPhotoGenerator'):
        _warnings.warn(
            f"{name} is deprecated and will be removed after 2026-07. "
            "Use HonnyMedia.generate(workflow='photo') instead.",
            DeprecationWarning,
            stacklevel=2
        )
    
    if name == 'PhotoGenerator':
        from generators.photo_generator import PhotoGenerator
        return PhotoGenerator
    elif name == 'MultiPhotoGenerator':
        from generators.multiphoto_generator import MultiPhotoGenerator
        return MultiPhotoGenerator
    elif name == 'VideoGenerator':
        from generators.video_generator import VideoGenerator
        return VideoGenerator
    elif name == 'PromptPhotoGenerator':
        from generators.prompt_photo_generator import PromptPhotoGenerator
        return PromptPhotoGenerator

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")