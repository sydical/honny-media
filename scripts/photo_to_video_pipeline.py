#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Photo to Video Pipeline
照片生成提示词 → 视频分镜提示词
保证图片作为关键帧，图片与视频融合
"""

import re
from typing import Dict, List, Tuple, Optional


class PhotoToVideoPipeline:
    """
    Photo → Video 转换管道
    
    流程：
    1. 生成照片（使用增强提示词）
    2. 将照片提示词转换为视频分镜
    3. 使用照片作为关键帧生成视频
    
    设计原则：
    - 照片作为视频的关键帧/起始帧
    - 照片提示词中的元素（人物、场景、服装）要保留到视频
    - 分镜设计要符合时间轴和运镜规律
    """
    
    # 人物特征关键词（从照片提示词中提取）
    PERSON_PATTERNS = [
        r'(\d+)岁.*?(?:女性|女生|少女|女孩|辣妹|甜妹)',
        r'(?:曼妙|苗条|丰满|凹凸).*?(?:身材|身姿|曲线)',
        r'(?:黑|棕|浅棕|长直|长卷).*?(?:发|头发|长发)',
        r'(?:皮肤|肌肤).*?(?:细腻|精致|通透|白嫩)',
        r'(?:前凸后翘|深V|细腰大长腿)',
    ]
    
    # 服装关键词
    CLOTHING_PATTERNS = [
        r'穿.*?([^\s，,]+(?:上衣|背心|吊带|衬衫|T恤|针织|连衣裙|短裙|牛仔裤|短裙))',
        r'([^\s，,]+(?:色).*?(?:针织|蕾丝|缎面|皮质|牛仔))',
    ]
    
    # 场景关键词
    SCENE_PATTERNS = [
        r'(?:在|于|位于)([^，,。]+(?:海边|街头|咖啡厅|卧室|公园|森林))',
        r'背景是([^，,。]+)',
        r'([^，,。]+(?:大海|沙滩|礁石|阳光|树荫))',
    ]
    
    # 运镜关键词
    CAMERA_MOVEMENTS = [
        '固定机位', '缓慢推进', '微推进', '向前推进', 
        '缓慢拉远', '向后拉', '后拉拉开',
        '侧面环绕', '缓慢环绕', '环绕至',
        '镜头推进', '镜头拉远', '镜头环绕',
        '固定', '推进', '拉远', '环绕'
    ]
    
    # 景别关键词
    SHOT_TYPES = {
        '远景': ['远景', '全景', '大全景'],
        '全景': ['全景', '大全景', '全貌'],
        '中景': ['中景', '中远景', '半身'],
        '近景': ['近景', '近景特写', '特写'],
        '特写': ['特写', '面部特写', '面部', '眼睛特写'],
    }
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """重置状态"""
        self.person_desc = ""      # 人物描述
        self.clothing_desc = ""    # 服装描述
        self.scene_desc = ""       # 场景描述
        self.style_desc = ""       # 风格描述
        self.emotion_desc = ""     # 情感描述
    
    def parse_photo_prompt(self, prompt: str) -> Dict[str, str]:
        """
        解析照片提示词，提取各元素
        
        Args:
            prompt: 照片生成提示词
            
        Returns:
            dict: {
                'person': '人物描述',
                'clothing': '服装描述', 
                'scene': '场景描述',
                'style': '风格描述',
                'emotion': '情感描述'
            }
        """
        self.reset()
        
        # 提取人物特征
        person_match = re.search(r'([^，,。]+岁[^，,。]+)', prompt)
        if person_match:
            self.person_desc = person_match.group(1)
        else:
            # 提取关键特征
            features = []
            if '长发' in prompt or '长直' in prompt or '长卷' in prompt:
                hair = re.search(r'((?:黑|棕|浅棕|金色|银白)长(?:直|卷|披肩)发)', prompt)
                if hair:
                    features.append(hair.group(1))
            if '皮肤' in prompt:
                skin = re.search(r'(?:皮肤(?:细腻|精致|通透|白嫩))', prompt)
                if skin:
                    features.append(skin.group(0))
            self.person_desc = '，'.join(features) if features else ""
        
        # 提取服装
        clothing_match = re.search(r'穿([^，,。]+)', prompt)
        if clothing_match:
            self.clothing_desc = clothing_match.group(1)
        
        # 提取场景
        for pattern in self.SCENE_PATTERNS:
            scene_match = re.search(pattern, prompt)
            if scene_match:
                self.scene_desc = scene_match.group(1)
                break
        
        # 提取风格
        styles = []
        for style in ['韩系', '清冷', '纯欲', '元气', '甜美', '温柔', '小清新', '氛围感']:
            if style in prompt:
                styles.append(style)
        self.style_desc = '，'.join(styles) if styles else ""
        
        # 提取情感/表情
        emotions = []
        for emotion in ['微笑', '微笑', '回眸', '侧头', '眼神', '望向远方', '自然']:
            if emotion in prompt:
                emotions.append(emotion)
        self.emotion_desc = '，'.join(emotions) if emotions else ""
        
        return {
            'person': self.person_desc,
            'clothing': self.clothing_desc,
            'scene': self.scene_desc,
            'style': self.style_desc,
            'emotion': self.emotion_desc
        }
    
    def build_storyboard(self, parsed: Dict[str, str], duration: int = 8) -> str:
        """
        根据解析的元素构建视频分镜
        
        Args:
            parsed: parse_photo_prompt 返回的解析结果
            duration: 视频时长（秒）
            
        Returns:
            str: 分镜提示词
        """
        # 计算分镜数量（每段约1.5-2秒）
        num_shots = max(3, min(6, int(duration / 2)))
        
        # 构建分镜
        storyboard_parts = []
        
        # 分镜1：开场（固定机位，全景/远景）
        storyboard_parts.append(
            f"0-{duration//num_shots}秒：开场{'固定机位' if num_shots > 3 else ''}，"
            f"{self._build_opening_shot()}"
        )
        
        # 分镜2-3：发展（推进/环绕，中景）
        for i in range(1, num_shots - 1):
            start = (duration // num_shots) * i
            end = (duration // num_shots) * (i + 1)
            
            if i == 1:
                # 第一次动作
                shot = self._build_action_shot(i)
            else:
                # 后续镜头
                shot = self._build_development_shot(i)
            
            storyboard_parts.append(f"{start}-{end}秒：{shot}")
        
        # 最后分镜：收尾（后拉，特写/回眸）
        last_start = (duration // num_shots) * (num_shots - 1)
        storyboard_parts.append(
            f"{last_start}-{duration}秒：{self._build_closing_shot()}"
        )
        
        return '\n'.join(storyboard_parts)
    
    def _build_opening_shot(self) -> str:
        """构建开场分镜"""
        parts = []
        
        # 场景
        if self.scene_desc:
            parts.append(f"{self.scene_desc}")
        else:
            parts.append("阳光明媚，环境优美")
        
        # 人物 + 服装（如果有）
        if self.person_desc:
            parts.append(f"出现{self.person_desc}")
        
        if self.clothing_desc:
            parts.append(f"穿{self.clothing_desc}")
        
        # 风格
        if self.style_desc:
            parts.append(f"整体{self.style_desc}")
        
        # 动作/表情
        if self.emotion_desc:
            parts.append(f"表情{self.emotion_desc}")
        else:
            parts.append("自然姿态")
        
        return '，'.join(parts)
    
    def _build_action_shot(self, shot_idx: int) -> str:
        """构建动作分镜"""
        parts = []
        
        # 镜头运动
        movements = ['镜头向前微推进至中景', '缓慢推进', '镜头向前推进']
        parts.append(movements[shot_idx % len(movements)])
        
        # 人物动作
        if self.person_desc:
            parts.append(f"{self.person_desc}")
        
        if self.emotion_desc:
            parts.append(f"开始{self.emotion_desc}")
        else:
            parts.append("开始自然走动")
        
        # 服装细节
        if self.clothing_desc:
            parts.append(f"服装：{self.clothing_desc}")
        
        return '，'.join(parts)
    
    def _build_development_shot(self, shot_idx: int) -> str:
        """构建发展分镜"""
        parts = []
        
        # 镜头运动
        if shot_idx % 2 == 0:
            parts.append('镜头从侧面缓慢环绕')
        else:
            parts.append('景别收缩至近景')
        
        # 情感/表情变化
        if self.emotion_desc:
            emotions = self.emotion_desc.split('，')
            if shot_idx <= len(emotions):
                parts.append(f"表情{emotions[shot_idx-1]}")
            else:
                parts.append(f"表情自然")
        
        # 场景细节
        if self.scene_desc:
            parts.append(f"背景{self.scene_desc}")
        
        return '，'.join(parts)
    
    def _build_closing_shot(self) -> str:
        """构建收尾分镜"""
        parts = []
        
        # 镜头运动
        parts.append("镜头缓慢后拉从近景转为全景")
        
        # 情感/动作
        if self.emotion_desc:
            emotions = self.emotion_desc.split('，')
            if '回眸' in emotions:
                parts.append("转身回眸望向你")
            elif '微笑' in emotions:
                parts.append("自然微笑")
            else:
                parts.append(emotions[0] if emotions else "完美收尾")
        else:
            parts.append("完美收尾")
        
        # 场景
        if self.scene_desc:
            parts.append(f"背景{self.scene_desc}")
        
        return '，'.join(parts)
    
    def generate(self, photo_prompt: str, reference_path: str = None, 
                 duration: int = 8, honny_media=None) -> Dict:
        """
        完整流程：Photo Prompt → Photo → Video Storyboard → Video
        
        Args:
            photo_prompt: 照片生成提示词
            reference_path: 参考图路径（可选）
            duration: 视频时长（秒）
            honny_media: HonnyMedia实例（可选）
            
        Returns:
            dict: {
                'photo_result': 照片生成结果,
                'video_result': 视频生成结果,
                'storyboard': 分镜提示词,
                'parsed_prompt': 解析后的提示词元素
            }
        """
        # Step 1: 解析照片提示词
        parsed = self.parse_photo_prompt(photo_prompt)
        print(f"📋 提示词解析完成:")
        print(f"   人物: {parsed['person']}")
        print(f"   服装: {parsed['clothing']}")
        print(f"   场景: {parsed['scene']}")
        print(f"   风格: {parsed['style']}")
        
        # Step 2: 构建分镜
        storyboard = self.build_storyboard(parsed, duration)
        print(f"\n📝 生成分镜:")
        print(storyboard)
        
        # Step 3: 如果提供了 honny_media，执行生成
        photo_result = None
        video_result = None
        
        if honny_media:
            # 生成照片
            print(f"\n📸 生成照片...")
            photo_result = honny_media.photo(
                prompt=photo_prompt,
                reference_path=reference_path
            )
            print(f"✅ 照片生成完成: {photo_result.get('local_path')}")
            
            # 生成视频（使用照片作为关键帧）
            print(f"\n🎬 生成视频...")
            video_result = honny_media.video(
                prompt=storyboard,
                reference_path=photo_result.get('local_path'),
                duration=duration
            )
            print(f"✅ 视频生成完成: {video_result.get('local_path')}")
        
        return {
            'photo_result': photo_result,
            'video_result': video_result,
            'storyboard': storyboard,
            'parsed_prompt': parsed
        }


def demo():
    """演示 Photo → Video 流程"""
    
    # 示例照片提示词
    photo_prompt = """
    参考图1人物，保持人物一致性。
    图中人物，28岁曼妙身姿东亚女性，163cm，49kg，
    前凸后翘，深V细腰大长腿，皮肤细腻精致。
    身穿浅杏色镂空挂脖吊带，修身短款露腰版型，
    温柔针织肌理面料。
    搭配浅蓝色高腰微喇牛仔裤。
    慵懒蓬松羊毛卷长发，风吹氛围感碎发，
    清透伪素颜淡妆，水光嫩唇。
    场景：平潭环岛路海边，蓝绿色大海、干净白色沙滩。
    风格：韩系清冷纯欲风，元气少女。
    """
    
    # 初始化管道
    pipeline = PhotoToVideoPipeline()
    
    # 解析并生成分镜
    parsed = pipeline.parse_photo_prompt(photo_prompt)
    storyboard = pipeline.build_storyboard(parsed, duration=8)
    
    print("=" * 60)
    print("Photo Prompt → Video Storyboard 演示")
    print("=" * 60)
    print("\n【原始照片提示词】")
    print(photo_prompt)
    print("\n【解析结果】")
    for key, value in parsed.items():
        print(f"  {key}: {value}")
    print("\n【生成的分镜】")
    print(storyboard)
    print("\n【分镜预览】")
    for line in storyboard.split('\n'):
        print(f"  {line}")


if __name__ == '__main__':
    demo()