#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_photo 提示词模板 v1.0
自动保证服装一致性 + 质量层统一注入

三段式结构：
[基础服装层] - 所有分镜共享，统一格式
[分镜描述层] - 每个分镜独立动作/景别
[质量保证层] - 自动注入，用户零成本
"""

from .photo_template import DEFAULTS


# ============================================================
# 质量层（自动注入，无需用户输入）
# ============================================================

QUALITY_LAYER = (
    "电影级面光1.6，柔和光影，明暗层次分明。"
    "24mm主摄等效焦距，大师构图，主体突出，浅景深虚化。"
    "超级高清，大师作品，顶级画质，iPhone原生质感。"
    "暖调通透，低饱和，电影感颗粒，iPhone原生相机拍摄。"
    "--no 模糊，畸变，穿模，AI绘画痕迹，水印，噪点，杂乱背景，过度美颜。"
)


def build_outfit_prompt(outfit_text):
    """
    将用户输入的穿搭文本格式化为标准化服装描述

    策略：
    - 按 ；或 换行 分割各穿搭项
    - 识别上衣/下装/鞋包/发型/妆容五大类
    - 用分号连接为一段连贯描述

    Args:
        outfit_text: 用户输入的穿搭描述

    Returns:
        str: 格式化后的服装描述字符串
    """
    if not outfit_text:
        return ""

    # 换行或分号都作为分割符
    import re
    parts = re.split(r'[；;\n]', outfit_text.strip())
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return ""

    # 去除可能的"分镜N提示词"标记
    marker_pattern = re.compile(
        r'^(分镜\s*\d+\s*[:：]?\s*|'
        r'【?分镜\s*\d+】?\s*[:：]?\s*|'
        r'^\d+\.\s*|'
        r'^\d+\s*[:：]\s*)',
        re.IGNORECASE
    )
    parts = [marker_pattern.sub('', p).strip() for p in parts]
    parts = [p for p in parts if p]

    return "；".join(parts) + "。"


def parse_shots_with_outfit(raw_prompt):
    """
    将用户原始输入解析为：
    - outfit: 基础服装描述
    - shots: list[str]，每项为分镜动作/景别描述

    策略：
    - 识别所有分镜行（以 分镜N 开头或 1. 2. 等）
    - 剩余非分镜行 → 合并为服装描述
    - 分镜内容：取 marker 后的完整内容

    Args:
        raw_prompt: 用户原始提示词

    Returns:
        dict: {
            'outfit': str,           # 基础服装描述
            'shots': list[str],       # 每分镜描述列表
            'raw_shots': list[str]    # 原始分镜内容
        }
    """
    import re

    marker_pattern = re.compile(
        r'^(分镜\s*\d+\s*[:：]?\s*|'
        r'【?分镜\s*\d+】?\s*[:：]?\s*|'
        r'^\d+\.\s*|'
        r'^\d+\s*[:：]\s*)',
        re.IGNORECASE
    )

    lines = [l.strip() for l in raw_prompt.split('\n') if l.strip()]
    outfit_lines = []
    raw_shots = []

    for line in lines:
        m = marker_pattern.match(line)
        if m:
            # 提取 marker 后的内容
            content = line[m.end():].strip()
            if content:
                raw_shots.append(content)
        else:
            outfit_lines.append(line)

    outfit = build_outfit_prompt(" ".join(outfit_lines))

    return {
        'outfit': outfit,
        'shots': raw_shots,
        'raw_shots': raw_shots,
    }


def build_shot_prompt(outfit, shot_action, quality_layer=QUALITY_LAYER):
    """
    将 服装 + 分镜动作 + 质量层 组装为完整分镜提示词

    Args:
        outfit: 基础服装描述（来自 build_outfit_prompt）
        shot_action: 分镜专属动作/景别描述
        quality_layer: 质量保证层（默认自动注入）

    Returns:
        str: 完整分镜提示词
    """
    parts = []

    if outfit:
        parts.append(outfit)

    if shot_action:
        parts.append(shot_action)

    if quality_layer:
        parts.append(quality_layer)

    return "\n".join(parts)


def format_prompt_photo(raw_prompt, quality_layer=QUALITY_LAYER):
    """
    主入口：将用户原始 prompt_photo 输入格式化为标准分镜提示词

    格式：
    分镜1提示词
    [服装描述]；[分镜动作]...
    [质量保证层]

    Args:
        raw_prompt: 用户原始提示词（穿搭 + 分镜描述混合格式）
        quality_layer: 质量层（可选，默认自动注入）

    Returns:
        str: 格式化后的完整提示词（多段，每段一个分镜）
    """
    parsed = parse_shots_with_outfit(raw_prompt)
    outfit = parsed['outfit']
    shots = parsed['shots']

    if not shots:
        raise ValueError("未检测到分镜描述，请使用 分镜1 / 分镜2 ... 或 1. 2. ... 格式")

    result_lines = []
    for i, shot in enumerate(shots):
        shot_prompt = build_shot_prompt(outfit, shot, quality_layer)
        result_lines.append(f"分镜{i+1}提示词\n{shot_prompt}")

    return "\n\n".join(result_lines)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    test_prompt = """白色T恤+浅蓝牛仔短裤+堆堆袜，大波浪长发，淡妆

分镜1：正面全身站立街拍，户外自然光
分镜2：三分侧身行走，腿臀线条展示
分镜3：四分侧身回眸，浅景深背景虚化
分镜4：背影全身，大波浪长发背影
分镜5：半身特写，歪头淡妆露锁骨
分镜6：S曲线侧身，身材玲珑曲线"""

    result = format_prompt_photo(test_prompt)
    print("=" * 60)
    print("INPUT:")
    print(test_prompt)
    print("=" * 60)
    print("OUTPUT:")
    print(result)
    print("=" * 60)
    print(f"Total length: {len(result)} chars")
    print(f"Shots: {result.count('分镜')}")