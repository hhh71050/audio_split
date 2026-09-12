#!/usr/bin/env python3
"""
WAV 转多声道 PCM 还原脚本（内存优化版）
- 使用 io.BytesIO 和标准库 wave，避免 pydub/ffmpeg 子进程与临时文件开销
- NumPy 矩阵向量化运算，内存中瞬间完成 14 声道扩充与衰减计算
- 支持管道/字节流处理与批量磁盘文件还原
"""

import argparse
import io
import time
import wave
from pathlib import Path
import numpy as np


def convert_wav_bytes_to_multichannel_pcm(
    wav_bytes: bytes,
    channels: int = 14,
    active_channels: int = 6,
    decay: float = 0.62,
) -> bytes:
    """在内存中将单声道 WAV 字节流转换为多声道 16-bit PCM 字节流"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw_frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        samples = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128) * 256
    else:
        raise ValueError(f"不支持的采样位数: {sampwidth * 8}-bit")

    if n_channels > 1:
        samples = samples[::n_channels]

    samples /= 32768.0

    num_samples = len(samples)
    multichannel = np.zeros((num_samples, channels), dtype=np.float32)

    for ch in range(min(active_channels, channels)):
        multichannel[:, ch] = samples * (decay ** ch)

    pcm_int16 = np.clip(multichannel * 32767.0, -32768, 32767).astype(np.int16)

    pcm_buffer = io.BytesIO()
    pcm_buffer.write(pcm_int16.tobytes())
    return pcm_buffer.getvalue()


def process_file(
    input_path: Path,
    output_path: Path,
    channels: int,
    active_channels: int,
    decay: float,
) -> bool:
    try:
        with open(input_path, "rb") as f:
            wav_bytes = f.read()

        pcm_bytes = convert_wav_bytes_to_multichannel_pcm(
            wav_bytes,
            channels=channels,
            active_channels=active_channels,
            decay=decay,
        )

        with open(output_path, "wb") as f:
            f.write(pcm_bytes)

        return True
    except Exception as e:
        print(f"  [!] 处理失败 {input_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="将单声道 WAV 批量还原为多声道 PCM (内存加速版)"
    )
    parser.add_argument("-i", "--input", required=True, help="输入 WAV 文件或文件夹路径")
    parser.add_argument("-o", "--output-dir", default="restored_pcm", help="PCM 输出目录")
    parser.add_argument("-c", "--channels", type=int, default=14, help="总声道数")
    parser.add_argument("-a", "--active-channels", type=int, default=6, help="发声声道数")
    parser.add_argument("-d", "--decay", type=float, default=0.62, help="声道衰减系数")

    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = list(input_path.glob("*.wav"))
    else:
        print(f"[!] 错误: 输入路径 '{input_path}' 不存在")
        return

    print(f"[*] 找到 {len(files)} 个 WAV 文件 | 输出目录: {out_dir.resolve()}")
    print(f"[*] 配置: {args.channels} 声道 (前 {args.active_channels} 声道衰减比 {args.decay})")

    start_time = time.perf_counter()
    success_count = 0

    for file in files:
        out_pcm_path = out_dir / f"{file.stem}.pcm"
        if process_file(file, out_pcm_path, args.channels, args.active_channels, args.decay):
            success_count += 1

    elapsed = time.perf_counter() - start_time
    print(f"\n[✔] 处理完成！成功: {success_count}/{len(files)} | 总耗时: {elapsed:.3f} 秒")


if __name__ == "__main__":
    main()