#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HonnyMedia CLI 主入口
版本：v1.0
日期：2026-05-18
"""

import os
import sys
import argparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_api_key():
    """从环境变量或配置文件获取API Key"""
    api_key = os.environ.get('RUNNINGHUB_API_KEY')
    
    if not api_key:
        # 尝试从workspace读取
        workspace_env = os.path.expanduser('~/.openclaw/workspace-companion2/.env')
        if os.path.exists(workspace_env):
            with open(workspace_env) as f:
                for line in f:
                    if line.startswith('RUNNINGHUB_API_KEY='):
                        api_key = line.split('=')[1].strip()
                        break
    
    return api_key


def cmd_photo(args):
    """Photo 单图生成命令"""
    from core.workflow_dispatcher import WorkflowDispatcher
    from db.db_manager import HonnyDBManager
    
    api_key = get_api_key()
    if not api_key:
        print("❌ 未找到 RUNNINGHUB_API_KEY")
        return 1
    
    db = HonnyDBManager()
    dispatcher = WorkflowDispatcher(api_key, db)
    
    result = dispatcher.dispatch(
        prompt=args.prompt,
        reference_path=args.ref,
        workflow_type='photo',
        output_dir=args.output,
        inject_exif=not args.no_exif
    )
    
    print("\n✅ 生成完成!")
    print(f"📝 提示词: {result.get('prompt', args.prompt)}")
    print(f"💾 本地路径: {result.get('local_path')}")
    
    return 0


def cmd_multiphoto(args):
    """MultiPhoto 多图套装生成命令"""
    from core.workflow_dispatcher import WorkflowDispatcher
    from db.db_manager import HonnyDBManager
    
    api_key = get_api_key()
    if not api_key:
        print("❌ 未找到 RUNNINGHUB_API_KEY")
        return 1
    
    db = HonnyDBManager()
    dispatcher = WorkflowDispatcher(api_key, db)
    
    result = dispatcher.dispatch(
        prompt=args.prompt,
        reference_path=args.ref,
        workflow_type='multiphoto',
        output_dir=args.output,
        inject_exif=not args.no_exif
    )
    
    print("\n✅ 生成完成!")
    print(f"📝 提示词: {result.get('prompt', args.prompt)}")
    print(f"📦 套装数量: {len(result.get('images', []))} 张")
    
    return 0


def cmd_video(args):
    """Video 视频生成命令"""
    from core.workflow_dispatcher import WorkflowDispatcher
    from db.db_manager import HonnyDBManager
    
    api_key = get_api_key()
    if not api_key:
        print("❌ 未找到 RUNNINGHUB_API_KEY")
        return 1
    
    db = HonnyDBManager()
    dispatcher = WorkflowDispatcher(api_key, db)
    
    result = dispatcher.dispatch(
        prompt=args.prompt,
        reference_path=args.ref,
        workflow_type='video',
        output_dir=args.output,
        duration=args.duration
    )
    
    print("\n✅ 生成完成!")
    print(f"📝 分镜: {result.get('prompt', args.prompt)}")
    print(f"💾 本地路径: {result.get('local_path')}")
    print(f"⏱️ 时长: {result.get('duration')} 秒")
    
    return 0


def cmd_generate(args):
    """自动识别类型生成命令"""
    from core.workflow_dispatcher import WorkflowDispatcher
    from db.db_manager import HonnyDBManager
    
    api_key = get_api_key()
    if not api_key:
        print("❌ 未找到 RUNNINGHUB_API_KEY")
        return 1
    
    db = HonnyDBManager()
    dispatcher = WorkflowDispatcher(api_key, db)
    
    result = dispatcher.dispatch(
        prompt=args.prompt,
        reference_path=args.ref,
        workflow_type=None,  # 自动识别
        output_dir=args.output,
        inject_exif=not args.no_exif
    )
    
    print("\n✅ 生成完成!")
    print(f"🎯 类型: {result.get('workflow_type', 'unknown')}")
    print(f"💾 本地路径: {result.get('local_path')}")
    
    return 0


def cmd_stats(args):
    """统计命令"""
    from db.db_manager import HonnyDBManager
    
    db = HonnyDBManager()
    stats = db.get_stats(days=args.days)
    
    print(f"\n📊 最近 {args.days} 天统计:")
    print("-" * 50)
    
    for ws in stats.get('workflow_stats', []):
        print(f"  {ws['workflow_type']}: {ws['success']}/{ws['total']} 成功")
    
    print("-" * 50)
    print(f"📦 缓存总数: {stats.get('cache_total', 0)}")
    print(f"🔄 缓存命中: {stats.get('cache_hits', 0)}")
    
    return 0


def cmd_gallery(args):
    """图片库命令"""
    from db.db_manager import HonnyDBManager
    
    db = HonnyDBManager()
    images = db.get_gallery(workflow_type=args.type, limit=args.limit)
    
    print(f"\n📷 图片库 (共 {len(images)} 张):")
    print("-" * 80)
    
    for img in images:
        path = img.get('local_path', 'N/A')
        shot_at = img.get('shot_at', 'N/A')
        workflow = img.get('workflow_type', 'unknown')
        print(f"  [{workflow}] {path} ({shot_at})")
    
    return 0


def cmd_cleanup(args):
    """清理过期缓存命令"""
    from db.db_manager import HonnyDBManager
    
    db = HonnyDBManager()
    result = db.cleanup_expired(days=args.days)
    
    print(f"\n🧹 清理完成:")
    print(f"  🗑️ 删除过期缓存: {result.get('expired_cache', 0)}")
    print(f"  🗑️ 删除过期任务: {result.get('expired_tasks', 0)}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='HonnyMedia - 统一媒体生成工具',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # photo 命令
    photo_parser = subparsers.add_parser('photo', help='生成单张图片')
    photo_parser.add_argument('prompt', help='图片描述提示词')
    photo_parser.add_argument('--ref', help='参考图路径')
    photo_parser.add_argument('--output', help='输出目录')
    photo_parser.add_argument('--no-exif', action='store_true', help='不注入EXIF')
    photo_parser.set_defaults(func=cmd_photo)
    
    # multiphoto 命令
    multiphoto_parser = subparsers.add_parser('multiphoto', help='生成多图套装')
    multiphoto_parser.add_argument('prompt', help='套装描述提示词')
    multiphoto_parser.add_argument('--ref', help='参考图路径')
    multiphoto_parser.add_argument('--output', help='输出目录')
    multiphoto_parser.add_argument('--no-exif', action='store_true', help='不注入EXIF')
    multiphoto_parser.set_defaults(func=cmd_multiphoto)
    
    # video 命令
    video_parser = subparsers.add_parser('video', help='生成视频')
    video_parser.add_argument('prompt', help='视频分镜描述')
    video_parser.add_argument('--ref', help='参考图路径')
    video_parser.add_argument('--output', help='输出目录')
    video_parser.add_argument('--duration', type=int, default=8, help='视频时长(秒)')
    video_parser.set_defaults(func=cmd_video)
    
    # generate 命令（自动识别）
    generate_parser = subparsers.add_parser('generate', help='自动识别类型生成')
    generate_parser.add_argument('prompt', help='描述提示词')
    generate_parser.add_argument('--ref', help='参考图路径')
    generate_parser.add_argument('--output', help='输出目录')
    generate_parser.add_argument('--no-exif', action='store_true', help='不注入EXIF')
    generate_parser.set_defaults(func=cmd_generate)
    
    # stats 命令
    stats_parser = subparsers.add_parser('stats', help='查看统计')
    stats_parser.add_argument('--days', type=int, default=7, help='统计天数')
    stats_parser.set_defaults(func=cmd_stats)
    
    # gallery 命令
    gallery_parser = subparsers.add_parser('gallery', help='查看图片库')
    gallery_parser.add_argument('--type', choices=['photo', 'multiphoto', 'video'], help='筛选类型')
    gallery_parser.add_argument('--limit', type=int, default=50, help='显示数量')
    gallery_parser.set_defaults(func=cmd_gallery)
    
    # cleanup 命令
    cleanup_parser = subparsers.add_parser('cleanup', help='清理过期数据')
    cleanup_parser.add_argument('--days', type=int, default=30, help='超过多少天清理')
    cleanup_parser.set_defaults(func=cmd_cleanup)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main() or 0)