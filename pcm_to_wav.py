import wave
import argparse
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


def convert_pcm_to_mono_wav(pcm_path, wav_path, channels=14, target_channel=0, sample_rate=16000):
    """
    读取多声道 PCM 并提取指定声道保存为单声道 WAV
    默认假设采样位深为 16-bit (np.int16)
    """
    try:
        # 读取原始 PCM 字节流
        raw_bytes = pcm_path.read_bytes()
        
        # 转换为 numpy 16-bit 整数数组
        audio_data = np.frombuffer(raw_bytes, dtype=np.int16)
        
        # 校验数据长度是否能被声道数整除（防备文件截断/损坏）
        remainder = len(audio_data) % channels
        if remainder != 0:
            # 截断不完整的尾部数据
            audio_data = audio_data[:-remainder]
            
        # 重塑矩阵形状为 (样本数, 声道数)
        audio_data = audio_data.reshape(-1, channels)
        
        # 提取目标声道数据 (注意：target_channel 是 0-indexed)
        if target_channel >= channels:
            raise ValueError(f"目标声道 {target_channel} 超出范围 (最大 {channels-1})")
            
        mono_data = audio_data[:, target_channel]
        
        # 写入 WAV 文件
        with wave.open(str(wav_path), 'wb') as wav_file:
            wav_file.setnchannels(1)           # 单声道
            wav_file.setsampwidth(2)           # 16-bit 采样位深 (2 bytes)
            wav_file.setframerate(sample_rate) # 采样率
            wav_file.writeframes(mono_data.tobytes())
            
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="多声道 PCM 转 单声道 WAV 工具")
    parser.add_argument("-i", "--input", default="pcms", help="输入的 PCM 文件夹 (默认: pcms)")
    parser.add_argument("-o", "--output", default="wavs", help="输出的 WAV 文件夹 (默认: wavs)")
    parser.add_argument("-c", "--channel", type=int, default=0, help="要提取的声道索引，0为第一个声道 (默认: 0)")
    parser.add_argument("--sr", type=int, default=16000, help="音频采样率 (默认: 16000)")
    parser.add_argument("--ch", type=int, default=14, help="原始 PCM 的总声道数 (默认: 14)")
    parser.add_argument("-w", "--workers", type=int, default=8, help="并发线程数 (默认: 8)")
    
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.is_dir():
        print(f"[!] 错误: 输入目录 '{input_dir}' 不存在。")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 扫描所有 pcm 文件
    pcm_files = list(input_dir.glob("*.pcm"))
    if not pcm_files:
        print(f"[*] 在 '{input_dir}' 中没有找到 .pcm 文件。")
        return

    print(f"[*] 找到 {len(pcm_files)} 个 PCM 文件，准备转换为单声道 WAV...")
    print(f"[*] 参数配置: 采样率 {args.sr}Hz | 总声道 {args.ch} | 提取第 {args.channel} 声道")

    success_count = 0
    error_count = 0

    def process_file(pcm_path):
        wav_path = output_dir / f"{pcm_path.stem}.wav"
        success, err_msg = convert_pcm_to_mono_wav(
            pcm_path, wav_path, 
            channels=args.ch, 
            target_channel=args.channel, 
            sample_rate=args.sr
        )
        if success:
            print(f"  [+] 转换成功: {pcm_path.name} -> {wav_path.name}")
            return True
        else:
            print(f"  [-] 转换失败: {pcm_path.name} | 错误: {err_msg}")
            return False

    # 并发执行转换
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(process_file, pcm_files))

    success_count = results.count(True)
    error_count = results.count(False)

    print("\n[OK] 批量转换完成！汇总信息：")
    print(f"     - 转换成功: {success_count} 个")
    print(f"     - 转换失败: {error_count} 个")
    print(f"     - 输出目录: {output_dir.resolve()}")


if __name__ == "__main__":
    main()