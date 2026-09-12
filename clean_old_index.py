import argparse
import re
from pathlib import Path


def clean_filename(stem):
  """将 '0001_10_语音内容文本' 提取重构为 '0001_语音内容文本'

  正则表达式解析：
  - ^(\d+_)  : 匹配最前面的新统一序号（如 0001_）
  - \d+[_\-] : 匹配紧随其后的原旧序号及分隔符（如 10_ 或 10-），将被剔除
  - (.+)$    : 匹配剩下的语音内容文本
  """
  match = re.match(r"^(\d+_)\d+[_\-](.+)$", stem)
  if match:
    new_prefix = match.group(1)  # 例如 "0001_"
    content_text = match.group(2)  # 例如 "语音内容文本"
    return f"{new_prefix}{content_text}"

  # 若不匹配（如 0006_WAKEUP_1），则保持原名不动
  return stem


def main():
  parser = argparse.ArgumentParser(
      description="清洗文件名中的旧序号 (例: 0001_10_文本 -> 0001_文本)"
  )
  parser.add_argument(
      "-i",
      "--input",
      default="refined_with_wakeup",
      help="音频文件所在的目录 (默认: refined_with_wakeup)",
  )
  parser.add_argument(
      "-d",
      "--dry-run",
      action="store_true",
      help="试运行模式 (仅打印重命名效果，不实际修改文件名)",
  )

  args = parser.parse_args()
  input_dir = Path(args.input)

  if not input_dir.is_dir():
    print(f"[!] 错误: 找不到文件夹 '{input_dir}'。")
    return

  files = sorted([f for f in input_dir.iterdir() if f.is_file()])
  if not files:
    print(f"[*] 文件夹 '{input_dir}' 中没有找到文件。")
    return

  print(f"[*] 找到 {len(files)} 个文件，准备执行文件名清洗：")
  if args.dry_run:
    print("  [!] 当前为【试运行/预览模式】，不会真实改动磁盘文件：\n")

  renamed_count = 0
  skipped_count = 0

  for f in files:
    old_name = f.name
    new_stem = clean_filename(f.stem)
    new_name = f"{new_stem}{f.suffix}"

    # 仅当文件名确实发生变化时才执行操作
    if old_name != new_name:
      target_path = input_dir / new_name

      # 防覆盖校验
      if target_path.exists() and not args.dry_run:
        print(f"  [!] 跳过: '{new_name}' 已存在，防止覆盖现有文件。")
        skipped_count += 1
        continue

      if args.dry_run:
        print(f"  [预览] {old_name}  ==>  {new_name}")
      else:
        try:
          f.rename(target_path)
          print(f"  [+] 成功重命名: {old_name}  ==>  {new_name}")
        except Exception as e:
          print(f"  [-] 修改失败: {old_name} | 错误: {e}")
          skipped_count += 1
          continue

      renamed_count += 1

  print("\n[OK] 处理完成！")
  print(f"     - 变动/拟重命名: {renamed_count} 个文件")
  print(f"     - 保持原样/跳过: {len(files) - renamed_count} 个文件")


if __name__ == "__main__":
  main()