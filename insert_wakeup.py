import argparse
import re
import shutil
from pathlib import Path


def natural_sort_key(s):
  """自然排序 Key：保证 '2_xxx.pcm' 严格排在 '10_xxx.pcm' 前面，不会按字母序乱序"""
  return [
      int(text) if text.isdigit() else text.lower()
      for text in re.split(r'(\d+)', str(s))
  ]


def main():
  parser = argparse.ArgumentParser(
      description="在音频列表中按固定间隔插入唤醒词并重新统一编号"
  )
  parser.add_argument(
      "-i",
      "--input",
      default="refined",
      help="精修音频所在的文件夹 (默认: refined)",
  )
  parser.add_argument(
      "-w", "--wakeup", required=True, help="唤醒词 PCM 音频文件路径 (必须)"
  )
  parser.add_argument(
      "-o",
      "--output",
      default="refined_with_wakeup",
      help="输出文件夹 (默认: refined_with_wakeup)",
  )
  parser.add_argument(
      "-n", "--interval", type=int, default=5, help="每隔多少条插入一次唤醒词 (默认: 5)"
  )
  parser.add_argument(
      "-e", "--ext", default=".pcm", help="音频文件后缀 (默认: .pcm)"
  )
  parser.add_argument(
      "--start-with-wakeup",
      action="store_true",
      help="是否在开头(第0位置)先插入一次唤醒词",
  )

  args = parser.parse_args()

  input_dir = Path(args.input)
  wakeup_file = Path(args.wakeup)
  wakeup_stem = wakeup_file.stem
  output_dir = Path(args.output)
  ext = args.ext if args.ext.startswith(".") else f".{args.ext}"

  # 1. 校验输入路径与唤醒词文件
  if not input_dir.is_dir():
    print(f"[!] 错误: 输入文件夹 '{input_dir}' 不存在。")
    return
  if not wakeup_file.is_file():
    print(f"[!] 错误: 找不到唤醒词文件 '{wakeup_file}'。")
    return

  output_dir.mkdir(parents=True, exist_ok=True)

  # 2. 读取并自然排序所有音频文件
  audio_files = sorted(input_dir.glob(f"*{ext}"), key=natural_sort_key)
  if not audio_files:
    print(f"[*] 未在 '{input_dir}' 中找到后缀为 {ext} 的音频文件。")
    return

  total_audios = len(audio_files)
  print(f"[*] 读取到 {total_audios} 个原始音频文件...")

  # 计算总文件数，用于动态确定数字补零位数 (如 0001, 0010)
  estimated_total = total_audios + (total_audios // args.interval) + 2
  pad_width = max(4, len(str(estimated_total)))  # 至少 4 位补零

  seq_num = 1
  wakeup_count = 0

  # 3. 如果指定了开头插入唤醒词 (对应 0_唤醒词)
  if args.start_with_wakeup:
    wakeup_count += 1
    out_name = f"{0:0{pad_width}d}_{wakeup_stem}{ext}"
    shutil.copy2(wakeup_file, output_dir / out_name)
    print(f"  [+] [开头补入] {out_name}")
    # seq_num += 1

  # 4. 遍历复制原音频，并在满足间隔时插入唤醒词
  for idx, src_file in enumerate(audio_files, 1):
    # 复制原音频
    new_audio_name = f"{seq_num:0{pad_width}d}_{src_file.name}"
    shutil.copy2(src_file, output_dir / new_audio_name)
    print(f"  [>] {src_file.name} -> {new_audio_name}")
    seq_num += 1

    # 每满 interval 条，插入一次唤醒词
    if idx % args.interval == 0:
      wakeup_count += 1
      wakeup_name = f"{seq_num:0{pad_width}d}_{wakeup_stem}{ext}"
      shutil.copy2(wakeup_file, output_dir / wakeup_name)
      print(f"  [+] [每{args.interval}条插入] {wakeup_name}")
      seq_num += 1

  print("\n[OK] 处理完成！")
  print(f"     - 原音频数量: {total_audios} 个")
  print(f"     - 插入唤醒词: {wakeup_count} 次")
  print(f"     - 总文件输出: {seq_num - 1} 个")
  print(f"     - 输出目录: {output_dir.resolve()}")


if __name__ == "__main__":
  main()