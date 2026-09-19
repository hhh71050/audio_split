#!/usr/bin/env python3
"""
TTS 单声道 WAV 生成脚本（精简版）
- 纯内存 I/O，避免中间临时文件落盘
- 输出标准 ASR 友好的 16kHz / 16-bit / Mono WAV
- 支持自定义/关闭文件名前缀序号
- 自动重试限流、断点续传、超时打断
"""

import asyncio
import argparse
import re
import time
import io
import random
from pathlib import Path

import edge_tts
import numpy as np
from pydub import AudioSegment


# ============================================================
# 1. 辅助函数
# ============================================================
def extract_text_content(line: str) -> tuple[str | None, str]:
    """提取行内的数字前缀与纯文本，例: '001_开门' -> ('001', '开门')"""
    match = re.match(r'^(\d+)[_\s]+(.+)$', line.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, line.strip()


def sanitize_filename(text: str, max_len: int = 30) -> str:
    """清理文件名中的非法字符，仅保留中英文和数字"""
    safe = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)
    return safe[:max_len] if safe else "empty"


def generate_mono_wav(
    audio_bytes: bytes,
    padding_ms: int = 1500,
    target_ratio: float = 0.9,
) -> bytes:
    """
    将下载的 MP3 字节流转为标准的 16kHz / Mono / 16-bit WAV 字节流
    - padding_ms: 首尾各补多少毫秒静音
    - target_ratio: 峰值归一化比例 (0.0 ~ 1.0)，None 表示不做归一化
    """
    # 1. 内存中解码音频并重采样
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)

    # 2. 首尾补充静音
    pad = AudioSegment.silent(duration=padding_ms)
    audio = pad + audio + pad

    # 3. 峰值归一化（可选）
    if target_ratio is not None:
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
        peak = np.max(np.abs(samples))
        if peak > 0:
            gain = target_ratio / peak
            samples = samples * gain
        pcm_int16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        audio = AudioSegment(
            data=pcm_int16.tobytes(),
            sample_width=2,
            frame_rate=16000,
            channels=1,
        )

    # 4. 导出为 WAV 字节流
    wav_buffer = io.BytesIO()
    audio.export(wav_buffer, format="wav")
    return wav_buffer.getvalue()


# ============================================================
# 2. 单条合成
# ============================================================
async def synthesize_text(text: str, out_path: Path, args) -> tuple[bool, str]:
    """带有超时、重试与限流保护的 TTS 单条合成流"""
    clean_text = re.sub(r'[<>]', '', text).strip()
    if not re.search(r'[A-Za-z0-9\u4e00-\u9fa5]', clean_text):
        return False, "无效文本(不含可发音字符)"

    last_err = ""
    for attempt in range(args.retries):
        try:
            # 使用 Edge-TTS 流式获取音频字节
            comm = edge_tts.Communicate(clean_text, args.voice, rate=args.rate)
            audio_data = bytearray()

            async def fetch_stream():
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"]) # type: ignore

            await asyncio.wait_for(fetch_stream(), timeout=args.timeout)

            if len(audio_data) < 100:
                raise ValueError("音频流拉取失败或为空")

            # 内存中转为标准 Mono WAV
            wav_bytes = generate_mono_wav(
                bytes(audio_data),
                padding_ms=args.padding_ms,
                target_ratio=args.ratio,
            )

            # 直接存入最终路径
            with open(out_path, "wb") as f:
                f.write(wav_bytes)

            duration = len(wav_bytes) / (16000 * 2)  # WAV 加上 header，粗略估算
            return True, f"时长: ~{duration:.2f}s"

        except Exception as e:
            last_err = str(e)
            if attempt < args.retries - 1:
                wait = random.uniform(2.0, 4.0) * (attempt + 1)
                print(f"    [!] 失败 ({last_err})，等待 {wait:.1f}s 后重试...")
                await asyncio.sleep(wait)

    return False, f"已重试 {args.retries} 次均失败: {last_err}"


# ============================================================
# 3. 主流程
# ============================================================
async def main_async(args):
    input_txt = Path(args.input)
    out_dir = Path(args.output_dir)

    if not input_txt.exists():
        print(f"[!] 错误: 找不到 TXT 文件 '{input_txt}'")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    with open(input_txt, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    print(f"[*] 共读取 {len(lines)} 条文本 | 输出目录: {out_dir}")
    print(f"[*] 音色: {args.voice} | 语速: {args.rate}")
    print(f"[*] 输出格式: 16kHz / 16-bit / Mono WAV")
    print(f"[*] 首尾 Padding: {args.padding_ms}ms | 峰值归一: {args.ratio if args.ratio is not None else '不归一'}")
    if args.no_prefix:
        print("[*] 序号前缀: 已关闭 (直接以文本内容命名)")
    else:
        print(f"[*] 序号前缀: 开启 (保留 {args.digits} 位数字)")

    total_start = time.perf_counter()
    stats = {"ok": 0, "skip": 0, "fail": 0}
    current_idx = args.start_idx

    for line in lines:
        seq_str, text = extract_text_content(line)

        # 1. 决定当前的序号
        if seq_str and seq_str.isdigit():
            seq_num = int(seq_str)
        else:
            seq_num = current_idx
            current_idx += 1

        # 2. 生成文件名
        safe_name = sanitize_filename(text)
        if args.prefix_enabled:
            prefix = str(seq_num).zfill(args.digits)
            file_name = f"{prefix}_{safe_name}.wav"
        else:
            file_name = f"{safe_name}.wav"

        out_path = out_dir / file_name

        # 断点续传
        if out_path.exists():
            print(f"  [跳过] {file_name} (已存在)")
            stats["skip"] += 1
            continue

        if args.dry_run:
            print(f"  [预览] {file_name} <- '{text}'")
            continue

        print(f"  [合成] {file_name} <- '{text}'")
        success, msg = await synthesize_text(text, out_path, args)

        if success:
            print(f"    [+] {msg}")
            stats["ok"] += 1
        else:
            print(f"    [-] 失败: {msg}")
            stats["fail"] += 1

        await asyncio.sleep(random.uniform(1.5, 3.5))

    elapsed = time.perf_counter() - total_start
    m, s = divmod(elapsed, 60)
    print(f"\n[✔] 任务结束！成功: {stats['ok']} | 跳过: {stats['skip']} | 失败: {stats['fail']}")
    print(f"    ⏱️ 总耗时: {int(m)} 分 {s:.1f} 秒")


# ============================================================
# 4. CLI 入口
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TTS 批量生成 Mono WAV 工具")
    parser.add_argument("-i", "--input", required=True, help="输入的 TXT 文件路径")
    parser.add_argument("-o", "--output-dir", default="tts/", help="输出文件夹 (默认: tts/)")
    parser.add_argument("-v", "--voice", default="zh-CN-YunxiNeural", help="Edge-TTS 音色")
    parser.add_argument("-r", "--rate", default="-7%", help="语速")

    # --- 音频参数 ---
    parser.add_argument("--padding-ms", type=int, default=1500, help="首尾静音毫秒 (默认: 1500)")
    parser.add_argument("--ratio", type=float, default=None, help="峰值归一化比例 (默认不归一)")

    # --- 文件名序号参数 ---
    prefix_group = parser.add_mutually_exclusive_group()
    prefix_group.add_argument("--prefix", dest="prefix_enabled", action="store_true", help="为文件名添加序号前缀 (默认关闭)")
    prefix_group.add_argument("--no-prefix", dest="prefix_enabled", action="store_false", help="关闭文件名前缀序号 (默认)")
    parser.set_defaults(prefix_enabled=False)
    parser.add_argument("-s", "--start-idx", type=int, default=1, help="行内无序号时的起始序号 (默认: 1)")
    parser.add_argument("-d", "--digits", type=int, default=3, help="序号前缀补零位数 (默认: 3)")

    # --- 超时控制与模式 ---
    parser.add_argument("--timeout", type=int, default=38, help="单条超时秒数")
    parser.add_argument("--retries", type=int, default=3, help="最大重试次数")
    parser.add_argument("--dry-run", action="store_true", help="测试模式（仅打印名称不合成）")

    asyncio.run(main_async(parser.parse_args()))