import argparse
import re
from pathlib import Path

def remove_cell_prefix(args):
    target_dir = Path(args.dir)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"[!] 错误: 找不到指定的文件夹路径 '{target_dir}'")
        return

    # 匹配模式：形如 B39_xxx.wav
    prefix_pattern = re.compile(r'^[A-Za-z]+\d+_(.*)$')

    print(f"[*] 开始递归扫描目录 '{target_dir.name}' 及其子文件夹中的 WAV 切片...")

    # 核心改动：使用 rglob (recursive glob) 穿透所有子文件夹
    wav_files = sorted(target_dir.rglob("*.wav"))
    success_count = 0
    skip_count = 0

    for file_path in wav_files:
        old_name = file_path.name
        # 获取所在的子文件夹名，用于在控制台打印时更直观
        rel_path = file_path.relative_to(target_dir).parent
        display_dir = f"{rel_path}/" if str(rel_path) != "." else ""

        match = prefix_pattern.match(old_name)

        if match:
            new_name = match.group(1)

            # 同步更新了废片判定词，同时兼容新老版本
            if args.drop_error and ("[误读废片]" in new_name or "[废弃不做重读]" in new_name):
                print(f"  [-] 自动清理废片: {display_dir}{old_name} -> [物理删除]")
                file_path.unlink()
                success_count += 1
                continue

            new_file_path = file_path.with_name(new_name)

            # 安全防重名碰撞机制
            if new_file_path.exists():
                counter = 1
                while new_file_path.exists():
                    stem = new_file_path.stem
                    new_file_path = file_path.with_name(f"{stem}_{counter}.wav")
                    counter += 1

            # 物理执行重命名
            file_path.rename(new_file_path)
            print(f"  [✔] 成功清洗: {display_dir}{old_name} -> {new_file_path.name}")
            success_count += 1
        else:
            skip_count += 1

    print(f"\n[✔] 穿透重命名任务安全完成！")
    print(f"    - 成功清洗/处理文件: {success_count} 个")
    print(f"    - 忽略（无前缀或已清洗）: {skip_count} 个")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一键递归去除音频切片名中的 Excel 单元格坐标前缀")

    parser.add_argument("dir", nargs="?", default="excel_named_wavs", help="切片音频所在的文件夹目录 (默认: excel_named_wavs)")
    parser.add_argument("--drop-error", action="store_true", help="是否顺便一键彻底删除带有 '[废弃不做重读]' 等废片标志的音频")

    args = parser.parse_args()
    remove_cell_prefix(args)