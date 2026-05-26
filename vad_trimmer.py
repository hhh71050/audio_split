import argparse
import numpy as np
import soundfile as sf
from pathlib import Path

def trim_silence(audio_segment, sample_rate, silence_threshold=0.02, buffer_sec=0.3):
    """
    核心 VAD 逻辑：定位人声起止点并应用缓冲。
    """
    abs_slice = np.abs(audio_segment)
    voice_indices = np.where(abs_slice > silence_threshold)[0]

    # 如果整段音频都没有超过阈值的有效声音（纯静音片段）
    if len(voice_indices) == 0:
        return None

    buffer_samples = int(sample_rate * buffer_sec)
    start = max(0, voice_indices[0] - buffer_samples)
    end = min(len(audio_segment), voice_indices[-1] + buffer_samples)

    return audio_segment[start:end]

def process_vad_directory(args):
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    
    if not input_dir.is_dir():
        print(f"[!] 错误: 输入路径 '{input_dir}' 不是一个有效的文件夹。")
        return

    output_dir.mkdir(exist_ok=True, parents=True)
    wav_files = sorted(input_dir.glob("*.wav"))
    
    if not wav_files:
        print(f"[*] 文件夹 '{input_dir}' 中未找到 .wav 文件。")
        return

    print(f"[*] 开始 VAD 批量处理，共发现 {len(wav_files)} 个音频文件...")
    processed_count = 0
    skipped_count = 0

    for file_path in wav_files:
        try:
            data, sample_rate = sf.read(file_path)
        except Exception as e:
            print(f"  [!] 无法读取文件 {file_path.name}: {e}")
            continue

        # --- 核心更新：多声道智能处理 ---
        if data.ndim > 1:
            if args.channel == -1:
                # 自动侦测模式：计算每个声道的最大绝对振幅
                peak_amplitudes = [np.max(np.abs(data[:, c])) for c in range(data.shape[1])]
                best_channel = np.argmax(peak_amplitudes)
                
                # 防御性判断：如果所有声道的最大振幅都极低，说明全都是静音
                if peak_amplitudes[best_channel] < args.silence_threshold:
                    print(f"  [-] 跳过 {file_path.name}: 所有声道均无有效声音。")
                    skipped_count += 1
                    continue
                    
                mono_data = data[:, best_channel]
                # 可选：打印出选择的声道，方便你核对
                # print(f"  [*] {file_path.name}: 自动选择最强声道 {best_channel} (峰值: {peak_amplitudes[best_channel]:.3f})")
            else:
                # 传统模式：强制使用用户指定的声道
                if args.channel >= data.shape[1]:
                    print(f"  [!] 跳过 {file_path.name}: 设定的声道索引 {args.channel} 溢出 (仅有 {data.shape[1]} 个声道)")
                    continue
                mono_data = data[:, args.channel]
        else:
            mono_data = data

        # 执行 VAD 裁剪
        trimmed_audio = trim_silence(
            mono_data, 
            sample_rate, 
            args.silence_threshold, 
            args.buffer
        )

        if trimmed_audio is None:
            print(f"  [-] 跳过 {file_path.name}: 未检测到有效人声 (纯静音)")
            skipped_count += 1
            continue
            
        # 过滤修剪后过短的碎片
        if (len(trimmed_audio) / sample_rate) < args.min_duration:
             print(f"  [-] 跳过 {file_path.name}: 修剪后时长过短 (< {args.min_duration}s)")
             skipped_count += 1
             continue

        # 保持原文件名导出到新文件夹
        output_file = output_dir / file_path.name
        sf.write(output_file, trimmed_audio, sample_rate)
        
        print(f"  [+] 已修剪并导出: {file_path.name}")
        processed_count += 1

    print("-" * 40)
    print(f"[✔] 批量 VAD 处理完成！成功: {processed_count} 个，跳过: {skipped_count} 个。")
    print(f"[*] 输出目录: {output_dir.absolute()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立 VAD 批量裁剪工具 (支持自动侦测最强声道)")

    # 必需参数
    parser.add_argument("input_dir", help="存放待处理 .wav 碎片的输入文件夹路径")

    # 可选配置 (默认 channel 改为 -1)
    parser.add_argument("-o", "--output-dir", default="vad_trimmed_wavs", help="裁剪后音频的输出目录 (默认: vad_trimmed_wavs)")
    parser.add_argument("-c", "--channel", type=int, default=-1, help="提取目标声道的索引。设为 -1 则自动侦测信号最强的声道 (默认 -1)")
    
    # VAD 核心阈值
    parser.add_argument("--silence-threshold", type=float, default=0.02, help="VAD 静音剔除判定阈值 (默认 0.02)")
    parser.add_argument("--buffer", type=float, default=0.3, help="人声首尾保留的缓冲保护秒数 (默认 0.3)")
    parser.add_argument("--min-duration", type=float, default=1.0, help="丢弃修剪后小于此秒数的片段 (默认 1.0)")

    args = parser.parse_args()
    process_vad_directory(args)