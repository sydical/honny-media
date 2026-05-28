# HonnyMedia Skill

> 版本：v1.8
> 日期：2026-05-20
> 状态：✅ Video 轮询优化 + async_mode 支持

统一管理 photo / multiphoto / video 三种工作流的媒体生成技能。

---

## 核心模块功能 ✅ 已验证

### detect_workflow(prompt)

自动检测 prompt 类型并返回对应工作流标识符。

```python
from honny_media import detect_workflow

# 测试结果（2026-05-20 验证）
detect_workflow("韩系穿搭")           # → 'photo' ✅
detect_workflow("生成一套4图")        # → 'multiphoto' ✅
detect_workflow("做视频")             # → 'video' ✅
```

| 关键词示例 | 返回值 | 说明 |
|------------|--------|------|
| 韩系穿搭、拍张照片、生成照片 | `photo` | 单张照片生成 |
| 4图、套装、多图、一致性套图 | `multiphoto` | 多图套装生成 |
| 做视频、生成视频、图生视频 | `video` | 视频生成 |

---

## Photo → Video Pipeline ✅ 新增

### 功能说明

将**照片提示词**自动转换为**视频分镜**，使用生成的照片作为视频首帧/关键帧，实现图片与视频的完美融合。

### 使用方法

```python
from honny_media import HonnyMedia

honny = HonnyMedia()

# 一键生成 Photo → Video
result = honny.photo_to_video(
    photo_prompt="28岁曼妙身姿东亚女性，穿浅杏色镂空挂脖吊带，场景：平潭海边",
    reference_path="/path/to/ref.jpg",
    duration=8
)

# result 包含：
# - photo_result: 照片生成结果
# - video_result: 视频生成结果
# - storyboard: 分镜提示词
# - parsed_prompt: 解析后的提示词元素
```

### 流程

```
Photo Prompt → 解析元素 → Storyboard → 生成 Photo（关键帧）
                                           ↓
                              生成 Video（使用 Photo 作为首帧）
```

### 分镜构建规则

| 时间 | 分镜 | 内容 |
|------|------|------|
| 0-2s | 开场 | 固定机位，全景，展示场景+人物 |
| 2-4s | 发展 | 镜头推进，人物开始动作 |
| 4-6s | 深入 | 环绕/特写，表情变化 |
| 6-8s | 收尾 | 后拉全景，回眸微笑 |

---

## 工作流类型

| 类型 | 命令 | 输入 | 输出 |
|------|------|------|------|
| photo | `/photo` | 参考图 + 提示词 | 单张图片 |
| multiphoto | `/multiphoto` | 参考图 + 提示词 | 多图套装 |
| video | `/video` | 参考图 + 分镜 | 视频 |
| photo_to_video | - | 照片提示词 + 参考图 | 照片 + 视频 |

## 工作流 ID 映射

```python
WORKFLOW_IDS = {
    'photo': '2047002838944980993',        # Wan2.2 图生图
    'multiphoto': '2054941025688399873',   # 一致性多图
    'video': '2048133528671490050',        # Wan 2.2 视频
}
```

---

## 使用方法

### Python API

```python
from honny_media import HonnyMedia, detect_workflow

# 1. 自动检测工作流
workflow = detect_workflow("生成一套韩系甜妹4图")
print(workflow)  # → 'multiphoto'

# 2. 使用统一框架生成
honny = HonnyMedia()

# 生成图片
result = honny.photo(
    prompt="韩系甜美穿搭街拍",
    reference_path="/path/to/ref.jpg"
)

# 生成多图套装
result = honny.multiphoto(
    prompt="韩系元气甜妹",
    reference_path="/path/to/model.jpg"
)

# 生成视频
result = honny.video(
    prompt="分镜描述...",
    reference_path="/path/to/ref.jpg",
    duration=8
)

# 异步模式：适合长时间任务（避免shell超时），
# 提交后立即返回 task_id，后台轮询等待结果
result = honny.video(
    prompt="分镜描述...",
    reference_path="/path/to/ref.jpg",
    duration=8,
    async_mode=True  # 只提交不等待，返回 task_id
)
# 返回: {'status': 'submitted', 'task_id': '...', 'workflow_id': '...', 'duration': 8}
# 然后用 task_id 查询结果，或用 sessions_spawn 后台轮询

# Photo → Video 一键生成
result = honny.photo_to_video(
    photo_prompt="韩系甜美穿搭",
    reference_path="/path/to/ref.jpg",
    duration=8
)
```

### CLI 用法

```bash
# 生成单图
honny-media photo "韩系纯欲风穿搭" --ref /path/to/ref.jpg

# 生成多图套装
honny-media multiphoto "卧室纯欲风4宫格" --ref /path/to/ref.jpg

# 生成视频
honny-media video "海边日落分镜" --ref /path/to/ref.jpg --duration 8

# Photo → Video
honny-media photo-to-video "韩系穿搭" --ref /path/to/ref.jpg
```

---

## 目录结构

```
~/.openclaw/skills/honny-media/
├── SKILL.md                     # 技能说明
├── main.py                      # CLI主入口
├── honny_media.py               # HonnyMedia主类
├── honny.db                     # SQLite数据库
├── db/                          # 数据库模块
│   ├── schema.py               # 7张表结构
│   └── db_manager.py           # CRUD操作
├── core/                       # 核心模块
│   ├── workflow_dispatcher.py  # 工作流分发
│   ├── reference_manager.py   # 参考图管理
│   ├── exif_manager.py        # EXIF注入
│   └── cache_manager.py       # 缓存管理
├── generators/                 # 生成器
│   ├── photo_generator.py     # 单图生成器
│   ├── multiphoto_generator.py # 多图套装生成器
│   └── video_generator.py     # 视频生成器
├── scripts/                    # 脚本
│   ├── photo_to_video_pipeline.py  # Photo→Video 管道
│   └── honny_media.py         # CLI脚本
└── utils/                      # 工具
    ├── runninghub.py          # RunningHub API
    └── image_utils.py         # 图片处理
```

---

## 数据库表

| 表名 | 说明 |
|------|------|
| workflow_types | 工作流类型枚举（photo/multiphoto/video） |
| reference_images | 参考图管理 |
| generation_tasks | 任务记录 |
| generation_results | 生成结果（图片/视频本地路径） |
| prompt_cache | 缓存表（30天过期） |

---

## ⚠️ PNG 自动转 JPG 行为说明

### 现象
当 RunningHub 返回 PNG 格式的图片时，EXIF 注入后会**自动转换为 JPG 格式**，原 PNG 文件会被删除。

### 原因
PIL/Pillow 向 PNG 写入 EXIF 支持有限，且 PNG 不支持 JPEG 压缩的 EXIF 区块。因此 `exif_manager.inject()` 在处理非 JPG 扩展名时会强制转为 JPG：

```python
# exif_manager.py inject() 方法
if ext in ('.jpg', '.jpeg'):
    img.save(image_path, 'jpeg', exif=exif_bytes, quality=95)
else:
    # 转换为jpg
    jpg_path = os.path.splitext(image_path)[0] + '.jpg'
    img.convert('RGB').save(jpg_path, 'jpeg', exif=exif_bytes, quality=95)
    os.remove(image_path)  # 删除原PNG
    return jpg_path
```

### 影响
- **multiphoto 生成的套图**：全部为 JPG 格式，便于飞书发送
- **本地路径变化**：`multiphoto_1_xxx.png` → `multiphoto_1_xxx.jpg`
- **文件删除**：原 PNG 在转换后被删除，不可恢复

### 设计决策
> 这是**有意为之**的设计。PNG 转 JPG 确保 EXIF 信息完整注入，且输出的 JPG 文件更适合社交媒体传输。

---

## 配置

环境变量或 `~/.openclaw/workspace-companion2/.env`:
```bash
RUNNINGHUB_API_KEY=你的API密钥
```

---

## 更新日志

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-20 | v1.8 | Video async_mode 支持，轮询间隔从5秒改为30秒，max_wait从300秒改为1200秒（20分钟）|
| 2026-05-20 | v1.1 | ✅ 核心模块测试完成，detect_workflow 已验证 |
| 2026-05-18 | v1.0 | 初始版本，Phase 1-3 完成 |

---

*基于 honny-media 统一框架*
*核心模块：detect_workflow() + photo_to_video()*
*版本：v1.7*