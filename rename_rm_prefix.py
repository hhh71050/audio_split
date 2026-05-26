import argparse
import re
from pathlib import Path

def remove_cell_prefix(args):
    target_dir = Path(args.dir)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"[!] 错误: 找不到指定的文件夹路径 '{target_dir}'")
        return

    # 匹配模式：形如 B39_快乐_xxx.wav 或 C1251_[误读废片]_xxx.wav
    # 正则解析：以字母开头，后面紧跟数字，再跟着一个下划线
    prefix_pattern = re.compile(r'^[A-Za-z]+\d+_(.*)$')

    print(f"[*] 开始扫描目录 '{target_dir.name}' 中的 WAV 切片...")
    
    wav_files = sorted(target_dir.glob("*.wav"))
    success_count = 0
    skip_count = 0

    for file_path in wav_files:
        old_name = file_path.name
        match = prefix_pattern.match(old_name)
        
        if match:
            # 提取去掉前缀后的新名称
            new_name = match.group(1)
            
            # 如果你在核对时保留了带有 [误读废片] 的文件，这里可以顺便过滤掉或者保留
            if args.drop_error and "[误读废片]" in new_name:
                print(f"  [-] 自动清理废片: {old_name} -> [物理删除]")
                file_path.unlink()  # 直接删除误读的废品音频
                success_count += 1
                continue

            new_file_path = file_path.with_name(new_name)
            
            # 安全防重名碰撞机制
            if new_file_path.exists():
                # 如果已经存在同名文件（比如重读片段和废片去前缀后重名），自动加后缀保护
                counter = 1
                while new_file_path.exists():
                    stem = new_file_path.stem
                    # 如果原先就有 _重读 或 _v2 顺延，没有就加 _counter
                    new_file_path = file_path.with_name(f"{stem}_{counter}.wav")
                    counter += 1
            
            # 物理执行重命名
            file_path.rename(new_file_path)
            print(f"  [✔] 成功清洗: {old_name} -> {new_file_path.name}")
            success_count += 1
        else:
            # 没有匹配到 B39_ 这种前缀的文件，保持原样不动
            skip_count += 1

    print(f"\n[✔] 重命名任务安全完成！")
    print(f"    - 成功清洗/处理文件: {success_count} 个")
    print(f"    - 忽略（无需处理）: {skip_count} 个")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一键去除音频切片名中的 Excel 单元格坐标前缀")
    
    # 必需参数：切片所在的文件夹
    parser.add_argument("dir", nargs="?", default="excel_named_wavs", help="切片音频所在的文件夹目录 (默认: excel_named_wavs)")
    
    # 可选参数：是否在去前缀的同时，把带有 '[误读废片]' 字样的音频直接物理删除
    parser.add_argument("--drop-error", action="store_true", help="是否顺便一键彻底删除带有 '[误读废片]' 标志的音频")

    args = parser.parse_args()
    remove_cell_prefix(args)