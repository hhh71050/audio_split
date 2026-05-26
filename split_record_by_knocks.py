from pathlib import Path
import numpy as np
import soundfile as sf
import argparse
import re

def trim_silence(audio_segment, sample_rate, silence_threshold=0.02, buffer_sec=0.3):
    """
    基于 VAD (端点检测) 切除首尾冗余静音。
    """
    abs_slice = np.abs(audio_segment)
    voice_indices = np.where(abs_slice > silence_threshold)[0]

    if len(voice_indices) == 0:
        return None, 0, 0

    buffer_samples = int(sample_rate * buffer_sec)
    start = max(0, voice_indices[0] - buffer_samples)
    end = min(len(audio_segment), voice_indices[-1] + buffer_samples)

    return audio_segment[start:end], start, end

def get_start_idx_from_stem(stem):
    """
    从类似 '2801-2900' 的文件名中提取起始序号 '2801'
    """
    # 优先尝试用 '-' 分割
    parts = stem.split('-')
    if parts and parts[0].isdigit():
        return int(parts[0])
    
    # 作为后备方案：提取文件名中出现的第一组连续数字
    match = re.search(r'(\d+)', stem)
    if match:
        return int(match.group(1))
    
    print(f"[!] 警告: 无法从文件名 '{stem}' 中解析出起始序号，默认使用 1")
    return 1

def process_single_file(input_file, args):
    """
    处理单个音频文件的核心逻辑
    """
    output_path = Path(args.output_dir)
    output_path.mkdir(exist_ok=True, parents=True)

    print(f"\n[{'='*40}]")
    print(f"[*] 正在处理文件: {input_file.name}")
    
    # 自动获取起始序号
    start_idx = get_start_idx_from_stem(input_file.stem)
    print(f"[*] 解析起始序号为: {start_idx}")

    # 1. 加载音频
    try:
        data, sample_rate = sf.read(input_file)
    except Exception as e:
        print(f"[!] 读取音频失败，跳过该文件: {e}")
        return

    # 声道提取安全判断
    if data.ndim > 1:
        if args.channel >= data.shape[1]:
            print(f"[!] 错误: 声道索引 {args.channel} 溢出 (该文件仅有 {data.shape[1]} 个声道)")
            return
        mono_data = data[:, args.channel]
    else:
        mono_data = data
    
    # 将整条音频的振幅放大 2 倍（或者根据需要微调，如 1.5, 2.5）
    mono_data = mono_data * 2.5

    # 2. 识别敲击声聚类 (Clusters)
    abs_data = np.abs(mono_data)
    peak_indices = np.where(abs_data > args.knock_threshold)[0]
    gap_samples = int(sample_rate * args.knock_gap)

    clusters = []
    if len(peak_indices) > 0:
        c_start = c_end = peak_indices[0]
        for i in range(1, len(peak_indices)):
            if peak_indices[i] - c_end < gap_samples:
                c_end = peak_indices[i]
            else:
                clusters.append((c_start, c_end))
                c_start = c_end = peak_indices[i]
        clusters.append((c_start, c_end))

    # 3. 确定分割边界
    raw_boundaries = [0]
    for cluster in clusters:
        raw_boundaries.extend([cluster[0], cluster[1]])
    raw_boundaries.append(len(mono_data))

    print(f"[*] 检测到 {len(clusters)} 处分隔敲击，准备分割为最大 {len(clusters) + 1} 个片段...")

    # 4. 执行分割与 VAD 修剪
    current_num = start_idx
    labels = []

    for i in range(0, len(raw_boundaries), 2):
        seg_start, seg_end = raw_boundaries[i], raw_boundaries[i+1]

        # 基础偏移，避开敲击声残余
        offset = int(sample_rate * .03)
        # 确保索引不越界
        safe_start = min(len(mono_data), seg_start + offset)
        safe_end = max(0, seg_end - offset)

        if safe_start >= safe_end:
            continue

        raw_seg = mono_data[safe_start:safe_end]

        # 应用 VAD 精修
        final_seg, v_start, v_end = trim_silence(
            raw_seg, sample_rate, args.silence_threshold, args.buffer
        )

        if final_seg is None or (len(final_seg) / sample_rate) < args.min_duration:
            print(f"  [+] 片段 {i+1} 时长过短 (< {args.min_duration}s, 不做提取导出)")
            continue

        actual_start_s = (safe_start + v_start) / sample_rate
        actual_end_s = (safe_start + v_end) / sample_rate

        # 格式化文件名 (加入分钟秒标记)
        m, s = divmod(int(actual_start_s), 60)
        file_name = f"{current_num}_{m}m{s}s.wav"

        # 导出文件
        sf.write(output_path / file_name, final_seg, sample_rate)

        # 收集标签信息
        if args.export_labels:
            labels.append(f"{actual_start_s:.1f}\t{actual_end_s:.1f}\t{current_num}")

        print(f"  [+] 已导出: {file_name} ({len(final_seg)/sample_rate:.1f}s)")
        current_num += 1

    # 5. 可选导出标签文件
    if args.export_labels:
        label_file = output_path / f"labels_{input_file.stem}.txt"
        with open(label_file, "w", encoding="utf-8") as f:
            f.write("\n".join(labels))
        print(f"[*] 标签文件已保存至: {label_file}")

    print(f"[✔] {input_file.name} 处理完成。")


def process_audio(args):
    """
    入口函数：判断输入是文件还是文件夹并分发处理
    """
    input_path = Path(args.input)

    if input_path.is_file() and input_path.suffix.lower() == '.wav':
        # 单文件模式
        process_single_file(input_path, args)
        
    elif input_path.is_dir():
        # 文件夹模式，寻找所有 wav 文件并按名称排序
        wav_files = sorted(input_path.glob("*.wav"))
        if not wav_files:
            print(f"[!] 错误: 文件夹 '{input_path}' 中未找到任何 WAV 文件。")
            return
            
        print(f"[*] 在目标文件夹中共发现 {len(wav_files)} 个 WAV 文件。即将开始批量处理...")
        for wav_file in wav_files:
            process_single_file(wav_file, args)
            
    else:
        print(f"[!] 错误: 输入路径 '{input_path}' 不存在，或不是一个支持的格式。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="音频批量自动分割与 VAD 精修工具")

    # 必需参数 (现在支持文件夹)
    parser.add_argument("input", help="输入的音频文件路径 或 包含多个音频的文件夹路径")

    # 可选参数
    parser.add_argument("-c", "--channel", type=int, default=0, help="目标声道索引 (默认 0)")
    parser.add_argument("-o", "--output-dir", default="split_wavs", help="输出目录 (默认 split_wavs)")

    # 阈值参数
    parser.add_argument("--knock-threshold", type=float, default=0.5, help="敲击声触发阈值 (默认 0.5)")
    parser.add_argument("--knock-gap", type=float, default=2.0, help="敲击合并窗口秒数 (默认 2.0)")
    parser.add_argument("--silence-threshold", type=float, default=0.02, help="VAD 静音剔除阈值 (默认 0.02)")
    parser.add_argument("--buffer", type=float, default=0.3, help="人声前后保留缓冲秒数 (默认 0.3)")
    parser.add_argument("--min-duration", type=float, default=5.0, help="丢弃小于此秒数的片段 (默认 5.0)")

    # 开关参数
    parser.add_argument("--export-labels", action="store_true", help="导出 Audacity 标签文件 (默认不导出)")

    args = parser.parse_args()
    process_audio(args)