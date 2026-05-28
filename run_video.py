import sys
sys.path.insert(0, '/root/.openclaw/skills/honny-media')
from honny_media import HonnyMedia

honny = HonnyMedia()

result = honny.video(
    prompt='8秒视频分镜：0-2s：开场固定机位，纯色背景前人物全身照；2-4s：人物慢慢转身展示穿搭，浅蓝蕾丝裙摆微动；4-6s：特写侧脸微笑，双手自然下垂展现身材；6-8s：保持纯色背景，人物微微后退，全景收尾',
    reference_path='/root/.openclaw/workspace-companion2/data/images/multiphoto_2_2059463038.png',
    duration=8
)
print(result)
