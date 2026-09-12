from pathlib import Path
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import argparse


def detect_speech_bounds(
    audio_float_channel,
    sample_rate,
    frame_ms=10,
    threshold_ratio=.04,
    head_buffer_s=.3,
    tail_buffer_s=.7,
):
  """基于短时 RMS 振幅比例进行端点检测，带前后双向安全延展缓冲 (Pre-roll & Hangover)"""
  frame_len = int(sample_rate * (frame_ms / 1000.0))
  num_frames = len(audio_float_channel) // frame_len
  if num_frames == 0:
    return 0, len(audio_float_channel)

  frames = audio_float_channel[: num_frames * frame_len].reshape(-1, frame_len)
  rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-10)

  active_frames = np.where(rms > threshold_ratio)[0]
  if len(active_frames) == 0:
    return 0, len(audio_float_channel)

  # 1. 原始 VAD 检测起止点
  raw_start_idx = active_frames[0] * frame_len
  raw_end_idx = (active_frames[-1] + 1) * frame_len

  # 2. 前置安全缓冲 (Pre-roll)：向左回退 head_buffer_s 秒
  head_samples = int(sample_rate * head_buffer_s)
  start_idx = max(0, raw_start_idx - head_samples)

  # 3. 后置安全缓冲 (Hangover)：向右延伸 tail_buffer_s 秒
  tail_samples = int(sample_rate * tail_buffer_s)
  end_idx = min(len(audio_float_channel), raw_end_idx + tail_samples)

  return start_idx, end_idx


def refine_multichannel_pcm(
    pcm_in_path,
    pcm_out_path,
    channels=14,
    ref_channel=0,
    sample_rate=16000,
    padding_s=0.1,
    target_ratio=.62,
    threshold_ratio=.04,
    head_buffer_s=.3,
    tail_buffer_s=.7,
):
  """多声道 PCM 端点裁剪、双向缓冲补齐与振幅归一化"""
  try:
    raw_bytes = pcm_in_path.read_bytes()
    audio_int16 = np.frombuffer(raw_bytes, dtype=np.int16)

    remainder = len(audio_int16) % channels
    if remainder != 0:
      audio_int16 = audio_int16[:-remainder]

    audio_matrix = audio_int16.reshape(-1, channels)
    audio_float = audio_matrix.astype(np.float32) / 32768.0

    ref_channel_idx = ref_channel if 0 <= ref_channel < channels else 0
    ref_float = audio_float[:, ref_channel_idx]

    # 执行带前后缓冲的端点检测
    start_idx, end_idx = detect_speech_bounds(
        ref_float,
        sample_rate,
        threshold_ratio=threshold_ratio,
        head_buffer_s=head_buffer_s,
        tail_buffer_s=tail_buffer_s,
    )
    trimmed_float = audio_float[start_idx:end_idx, :]

    # 全声道峰值归一化
    max_peak = np.max(np.abs(trimmed_float))
    if max_peak > 0:
      gain = target_ratio / max_peak
      normalized_float = trimmed_float * gain
    else:
      normalized_float = trimmed_float

    # 补齐纯静音 padding
    pad_samples = int(sample_rate * padding_s)
    padding = np.zeros((pad_samples, channels), dtype=np.float32)
    final_float = np.vstack([padding, normalized_float, padding])

    final_int16 = np.clip(final_float * 32767.0, -32768, 32767).astype(
        np.int16
    )
    pcm_out_path.write_bytes(final_int16.tobytes())

    return True, None
  except Exception as e:
    return False, str(e)


def main():
  parser = argparse.ArgumentParser(
      description=(
          "多声道 PCM 精修工具 (支持单文件或文件夹批量，含 Pre-roll & Hangover)"
      )
  )
  parser.add_argument(
      "-i",
      "--input",
      required=True,
      help="输入 PCM 文件路径或文件夹路径 (例如: wakeup.pcm 或 未识别/)",
  )
  parser.add_argument(
      "-o",
      "--output",
      default="refined",
      help="输出 PCM 文件路径或文件夹路径 (默认: refined)",
  )
  parser.add_argument(
      "--ch", type=int, default=14, help="原始 PCM 的总声道数 (默认: 14)"
  )
  parser.add_argument(
      "-ref",
      "--ref-channel",
      type=int,
      default=0,
      help="端点检测参考声道索引 (默认: 0)",
  )
  parser.add_argument(
      "--sr", type=int, default=16000, help="采样率 (默认: 16000)"
  )
  parser.add_argument(
      "-p",
      "--padding-s",
      type=float,
      default=1.0,
      help="首尾补齐纯静音秒数 (默认: 1.0s)",
  )
  parser.add_argument(
      "-head",
      "--head-buffer",
      type=float,
      default=.3,
      help="开头往前多截取的原声秒数 (Pre-roll, 默认: 0.3s)",
  )
  parser.add_argument(
      "-tail",
      "--tail-buffer",
      type=float,
      default=.7,
      help="结尾往后多截取的原声秒数 (Hangover, 默认: 0.7s)",
  )
  parser.add_argument(
      "-r",
      "--ratio",
      type=float,
      default=.62,
      help="目标最大振幅比例 (默认: .62)",
  )
  parser.add_argument(
      "-t",
      "--thresh-ratio",
      type=float,
      default=.04,
      help="静音判断门限振幅比例 (默认: .04 即 1%%)",
  )
  parser.add_argument(
      "-w",
      "--workers",
      type=int,
      default=8,
      help="批量模式下的并发线程数 (默认: 8)",
  )

  args = parser.parse_args()
  input_path = Path(args.input)
  output_path = Path(args.output)

  if not input_path.exists():
    print(f"[!] 错误: 输入路径 '{input_path}' 不存在。")
    return

  # 通用参数定义
  refine_kwargs = dict(
      channels=args.ch,
      ref_channel=args.ref_channel,
      sample_rate=args.sr,
      padding_s=args.padding_s,
      target_ratio=args.ratio,
      threshold_ratio=args.thresh_ratio,
      head_buffer_s=args.head_buffer,
      tail_buffer_s=args.tail_buffer,
  )

  # ================= 【场景 1: 单 PCM 文件精修】 =================
  if input_path.is_file():
    # 确定输出目标文件
    if output_path.suffix.lower() == ".pcm":
      output_path.parent.mkdir(parents=True, exist_ok=True)
      out_file = output_path
    else:
      output_path.mkdir(parents=True, exist_ok=True)
      out_file = output_path / input_path.name

    print(f"[*] 【单文件精修模式】")
    print(f"    - 输入文件: {input_path}")
    print(f"    - 输出文件: {out_file}")
    print(
        f"    - 前扩 Pre-roll: {args.head_buffer}s | 后扩 Hangover:"
        f" {args.tail_buffer}s"
    )

    success, err = refine_multichannel_pcm(
        input_path, out_file, **refine_kwargs
    )
    if success:
      print(f"\n[OK] 单文件精修完成！输出保存至: {out_file.resolve()}")
    else:
      print(f"\n[-] 精修失败: {err}")
    return

  # ================= 【场景 2: 文件夹批量精修】 =================
  output_dir = output_path
  output_dir.mkdir(parents=True, exist_ok=True)
  pcm_files = list(input_path.glob("*.pcm"))

  if not pcm_files:
    print(f"[*] 未在目录 '{input_path}' 中找到 .pcm 文件。")
    return

  print(f"[*] 【批量精修模式】找到 {len(pcm_files)} 个 PCM 文件：")
  print(f"    - 声道配置: {args.ch} 声道 | 参考声道: 第 {args.ref_channel} 声道")
  print(
      f"    - 前扩 Pre-roll: {args.head_buffer}s | 后扩 Hangover:"
      f" {args.tail_buffer}s"
  )
  print(f"    - 静音 Padding: 前后各 {args.padding_s}s | 触发门限: {args.thresh_ratio}\n")

  def worker(pcm_path):
    out_path = output_dir / pcm_path.name
    success, err = refine_multichannel_pcm(pcm_path, out_path, **refine_kwargs)
    if success:
      print(f"  [+] 成功: {pcm_path.name}")
      return True
    else:
      print(f"  [-] 失败: {pcm_path.name} | 错误: {err}")
      return False

  with ThreadPoolExecutor(max_workers=args.workers) as executor:
    results = list(executor.map(worker, pcm_files))

  print(
      f"\n[OK] 批量处理完毕！成功: {results.count(True)} 个 | 失败:"
      f" {results.count(False)} 个"
  )
  print(f"     输出目录: {output_dir.resolve()}")


if __name__ == "__main__":
  main()