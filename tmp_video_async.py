#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '/root/.openclaw/skills/honny-media')

# Set env var explicitly
os.environ['RUNNINGHUB_API_KEY'] = '5a953faadf6b412b8d64b58b64f4a683'

from honny_media import HonnyMedia

honny = HonnyMedia()

prompt_text = '8秒视频分镜：\n0-2s：开场固定机位，全景展示花园场景+人物全身\n2-4s：人物开始慢步走动，浅蓝蕾丝裙摆随风轻摆\n4-6s：镜头推进，特写侧脸微笑，展现身材\n6-8s：后拉全景，回眸微笑，背景虚化'

result = honny.video(
    prompt=prompt_text,
    reference_path='/root/.openclaw/workspace-companion2/data/images/multiphoto_1_2059463038.png',
    duration=8,
    async_mode=True
)
print("RESULT:", result)