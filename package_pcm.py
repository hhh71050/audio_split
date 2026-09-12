#!/usr/bin/env python3
import zipfile
import argparse
from pathlib import Path


def package_pcm_segments(input_dir: str, output_zip: str, exclude_keywords: list = None):
    if exclude_keywords is None:
        exclude_keywords = ["废弃", "废片", "discard"]

    input_path = Path(input_dir).resolve()
    output_zip_path = Path(output_zip).resolve()

    if not input_path.exists():
        print(f"[!] 错误: 输入目录 '{input_path}' 不存在。")
        return

    pcm_files = []
    skipped_files = []

    # 扫描 input_dir 及其所有子目录中的 .pcm 文件
    for file_path in sorted(input_path.rglob("*.pcm")):
        filename = file_path.name
        # 检查是否包含废弃标志关键字
        if any(keyword in filename for keyword in exclude_keywords):
            skipped_files.append(file_path)
        else:
            pcm_files.append(file_path)

    if not pcm_files:
        print(f"[!] 警告: 在目录 '{input_path}' 中未找到符合条件的 .pcm 文件。")
        return

    print(f"[*] 找到 {len(pcm_files)} 个有效的 PCM 切片文件。")
    if skipped_files:
        print(f"[*] 跳过 {len(skipped_files)} 个包含废弃标志的文件:")
        for sf in skipped_files:
            print(f"    - {sf.name}")

    # 创建 zip 压缩包
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for file_path in pcm_files:
            # 保持在 input_dir 相对路径下的结构
            arcname = file_path.relative_to(input_path)
            zipf.write(file_path, arcname=arcname)
            print(f"  [+] 已打包: {arcname}")

    total_size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    print(f"\n[✔] 打包完成！已生成压缩包: {output_zip_path} ({total_size_mb:.2f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将有效 PCM 切片打包为 Zip 压缩包（自动排除废片）")
    parser.add_argument("-i", "--input-dir", default="output", help="包含 PCM 切片的输入目录 (默认 'output')")
    parser.add_argument("-o", "--output-zip", default="pcm_segments.zip", help="输出的 zip 文件路径 (默认 'pcm_segments.zip')")
    parser.add_argument("-x", "--exclude", nargs="*", default=["废弃", "废片", "discard"], help="要排除的文件名关键字 (默认 '废弃' '废片' 'discard')")

    args = parser.parse_args()
    package_pcm_segments(args.input_dir, args.output_zip, args.exclude)
