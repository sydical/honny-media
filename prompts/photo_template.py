#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Photo 提示词模板 v2.0
将用户输入重组为 8 段式结构化提示词

范式：
[年龄+性别+气质+穿搭+五官质感], [景别+姿态+眼神情绪],
[光影类型+明暗效果], [焦段+构图+景深], [背景环境],
[分辨率+摄影类型], [色调+质感颗粒], --no [排除项]
"""

DEFAULTS = {
    # 模块1：人物基础
    "性别": "美女",
    "年龄": "28岁",
    "身高": "163cm",
    "体重": "49kg",
    "身材": "曼妙身姿，曲线玲珑，凹凸有致，黄金比例身材，前凸后翘，深V细腰，无多余赘肉，贴合身形曲线",
    "气质": "精致优雅，御姐气场",
    "肤色": "皮肤细腻，透亮粉嫩",
    "妆容": "精致妆容，裸感自然",
    "动作": "动作舒展优雅，姿态曼妙",
    "唇色": "晶莹剔透",
    "皮肤细节": "血管隐约可见",

    # 模块2：景别姿态
    "景别": "全身站立",
    "姿态": "自然舒展",
    "眼神": "眼神温柔，光彩流转",

    # 模块3：光影
    "光影": "电影级面光1.6",
    "明暗": "柔和光影，明暗层次分明",

    # 模块4：镜头
    "焦段": "24mm主摄等效焦距",
    "构图": "大师构图，主体突出",
    "景深": "浅景深虚化，主体清晰",

    # 模块5：背景
    "背景": "浅色纯色背景，简洁干净",

    # 模块6：画质
    "分辨率": "超级高清",
    "摄影类型": "大师作品，顶级画质",

    # 模块7：色调
    "色调": "暖调通透，低饱和",
    "质感": "电影感颗粒，iPhone原生质感",

    # 模块8：排除项
    "排除": "模糊，畸变，杂乱背景，过度美颜，水印，噪点，AI绘画痕迹",
}


def _clean(s):
    """去除字符串首尾空白和标点"""
    if not s:
        return ""
    return s.strip().strip("，。；：、·.")


def build_template(
    性别=None, 年龄=None, 身高=None, 体重=None,
    身材=None, 气质=None, 肤色=None, 妆容=None,
    动作=None, 唇色=None, 皮肤细节=None,
    穿搭=None,
    景别=None, 姿态=None, 眼神=None,
    光影=None, 明暗=None,
    焦段=None, 构图=None, 景深=None,
    背景=None,
    分辨率=None, 摄影类型=None,
    色调=None, 质感=None,
    排除项=None,
    **kwargs
):
    """
    将各模块字段组合为标准 8 段式提示词

    返回：
        str: 重组后的完整提示词
    """
    d = DEFAULTS.copy()

    def up(key, value):
        if value:
            d[key] = _clean(value)

    up("性别", 性别)
    up("年龄", 年龄)
    up("身高", 身高)
    up("体重", 体重)
    up("身材", 身材)
    up("气质", 气质)
    up("肤色", 肤色)
    up("妆容", 妆容)
    up("动作", 动作)
    up("唇色", 唇色)
    up("皮肤细节", 皮肤细节)
    up("穿搭", 穿搭)
    up("景别", 景别)
    up("姿态", 姿态)
    up("眼神", 眼神)
    up("光影", 光影)
    up("明暗", 明暗)
    up("焦段", 焦段)
    up("构图", 构图)
    up("景深", 景深)
    up("背景", 背景)
    up("分辨率", 分辨率)
    up("摄影类型", 摄影类型)
    up("色调", 色调)
    up("质感", 质感)
    up("排除", 排除项)

    parts = []

    # ===== 模块1：人物基础 + 穿搭 =====
    person = (
        f"{d['年龄']}{d['性别']}，{d['气质']}，"
        f"{d['身高']}，{d['体重']}，{d['身材']}，"
        f"{d['肤色']}，{d['妆容']}，{d['动作']}。"
        f"露脸{d['妆容']}，唇彩{d['唇色']}，{d['皮肤细节']}。"
    )
    parts.append(person)

    if d.get("穿搭"):
        parts.append(d["穿搭"] + "。")

    # ===== 模块2：景别 + 姿态 + 眼神 =====
    parts.append(f"{d['景别']}，{d['姿态']}，{d['眼神']}")

    # ===== 模块3：光影 =====
    parts.append(f"{d['光影']}，{d['明暗']}")

    # ===== 模块4：镜头 =====
    parts.append(f"{d['焦段']}，{d['构图']}，{d['景深']}")

    # ===== 模块5：背景 =====
    parts.append(d["背景"])

    # ===== 模块6：画质 =====
    parts.append(f"{d['分辨率']}，{d['摄影类型']}")

    # ===== 模块7：色调 =====
    parts.append(f"{d['色调']}，{d['质感']}")

    # ===== 模块8：--no 排除项 =====
    if d.get("排除"):
        parts.append(f"--no {d['排除']}")

    return "\n".join(parts)


def parse_user_input(raw_prompt):
    """
    将用户原始输入解析为结构化字段

    策略：
    - 先提取独立的穿搭/鞋包/发型妆容行（段首有 换行+空行 或 行首有 鞋包/发型/妆容/连衣裙/配饰 等关键词）
    - 剩余行合成为人物基础描述
    - 电影级面光 → 光影
    - iphone/手机拍摄 → 摄影类型
    - 全身/半身/特写 → 景别
    - 站姿/坐姿/倚靠 → 姿态

    Args:
        raw_prompt: 用户原始提示词

    Returns:
        dict: 结构化字段字典
    """
    lines = [l.strip() for l in raw_prompt.split("\n") if l.strip()]
    result = {}

    # 提取穿搭相关行（整行作为 穿搭 字段）
    穿搭_parts = []
    人物_lines = []

    for line in lines:
        # 识别穿搭专属行
        dress_keywords = ["连衣裙", "裙子", "上衣", "衬衫", "T恤", "外套", "防晒",
                         "裤", "短裙", "工装", "吊带", "蕾丝",
                         "鞋", "包", "配饰", "耳饰", "墨镜", "项链", "手链",
                         "发型", "妆容", "妆面", "长发", "卷发", "盘发"]
        if any(kw in line for kw in dress_keywords):
            穿搭_parts.append(line)
        else:
            人物_lines.append(line)

    # 人物基础描述 = 所有非穿搭行的合并
    result["人物描述"] = "，".join(人物_lines)
    result["穿搭"] = "；".join(穿搭_parts)

    # 人物描述中额外提取
    desc = " ".join(人物_lines)

    # 景别
    if "全身" in desc:
        result["景别"] = "全身站立"
    elif "半身" in desc:
        result["景别"] = "半身取景"
    elif "特写" in desc or "近景" in desc:
        result["景别"] = "面部特写"

    # 光影
    if "电影级" in desc or "面光" in desc:
        result["光影"] = "电影级面光1.6"
        result["明暗"] = "柔和光影，明暗层次分明"

    # 摄影类型
    if "iphone" in desc.lower() or "手机拍摄" in desc:
        result["摄影类型"] = "iPhone原生相机拍摄"
        result["质感"] = "iPhone原生质感"

    # 年龄
    import re
    age_m = re.search(r"(\d+)\s*[岁]", desc)
    if age_m:
        result["年龄"] = f"{age_m.group(1)}岁"

    # 身高体重
    h_m = re.search(r"(\d+)\s*cm", desc)
    w_m = re.search(r"(\d+)\s*kg", desc)
    if h_m:
        result["身高"] = f"{h_m.group(1)}cm"
    if w_m:
        result["体重"] = f"{w_m.group(1)}kg"

    return result


def format_prompt(raw_prompt, use_template=True):
    """
    主入口：将用户原始提示词格式化为标准 8 段式提示词

    Args:
        raw_prompt: 用户原始提示词
        use_template: 是否使用模板重组

    Returns:
        str: 格式化后的标准提示词
    """
    if not use_template:
        return raw_prompt

    parsed = parse_user_input(raw_prompt)
    return build_template(**parsed)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    test_prompt = """中国28岁美女，曼妙身姿，曲线玲珑，凹凸有致，皮肤细腻，精致妆容, 人物身高163cm，体重49kg，100cm大长腿，黄金比例身材，前凸后翘，深V细腰，无多余赘肉，贴合身形曲线，五官自然精致，动作舒展优雅。露脸妆容自然，唇彩晶莹剔透，皮肤细腻，血管隐约可见。电影级面光1.6，iphone16手机拍摄，大师作品。

连衣裙 白色复古卷草暗纹蕾丝面料，深V交叉领，喇叭长袖设计，高腰收腰，修身包臀鱼尾长款，通透微透质感，紧身凸显身材曲线
鞋包配饰 裸色一字带细跟高跟凉鞋；金色简约轻奢长款耳饰；白色手提腋下包放置于旁处长椅
发型妆容 黑色柔顺微卷长发，中分自然垂落；清透冷调御姐妆，精致眼妆+低饱和唇色，优雅氛围感妆面"""

    result = format_prompt(test_prompt)
    print("=" * 60)
    print("INPUT:")
    print(test_prompt)
    print("=" * 60)
    print("OUTPUT:")
    print(result)
    print("=" * 60)
    print(f"Length: {len(result)} chars")