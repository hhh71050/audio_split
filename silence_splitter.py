from pathlib import Path
import argparse
import numpy as np
import soundfile as sf
import re
import pandas as pd



def parse_filename(stem):
    """解析文件名：列名, 起始行, 结束行 (例: "A-122-141" -> ("A", 122, 141))"""
    match = re.search(r'(.*)-(\d+)-(\d+)', stem)
    if match:
        return match.group(1).upper(), int(match.group(2)), int(match.group(3))

    match_num = re.search(r'(\d+)-(\d+)', stem)
    if match_num:
        return "Unknown", int(match_num.group(1)), int(match_num.group(2))

    match_single = re.search(r'(\d+)', stem)
    if match_single:
        return "Unknown", int(match_single.group(1)), None

    return "Unknown", 1, None


def sanitize_filename(name):
    """过滤文件名非法字符"""
    if name is None or pd.isna(name):
        return "EMPTY_CELL"
    clean_name = re.sub(r'[\\/*?:"<>|\s\t\n\r]', '_', str(name))
    return clean_name.strip('_')


def parse_error_segments(err_str):
    """解析输入的误读片段序号 (idx)，转为整型集合"""
    if not err_str:
        return set()
    return set(int(x) for x in re.findall(r'\d+', err_str))


def split_by_silence(mono_data, sample_rate, silence_threshold, min_silence_sec, buffer_sec, min_duration_sec):
    abs_data = np.abs(mono_data)

    threshold = silence_threshold * 32767 if np.max(abs_data) > 1.0 else silence_threshold
    voice_indices = np.where(abs_data > threshold)[0]

    if len(voice_indices) == 0:
        return []

    gap_samples = int(sample_rate * min_silence_sec)
    jumps = np.where(np.diff(voice_indices) > gap_samples)[0]

    starts = np.insert(voice_indices[jumps + 1], 0, voice_indices[0])
    ends = np.append(voice_indices[jumps], voice_indices[-1])
    clusters = list(zip(starts, ends))

    valid_segments = []
    buffer_samples = int(sample_rate * buffer_sec)
    total_samples = len(mono_data)

    for i, (c_start, c_end) in enumerate(clusters):
        seg_start = max(0, c_start - buffer_samples)
        seg_end = min(total_samples, c_end + buffer_samples)

        duration = (seg_end - seg_start) / sample_rate
        if duration >= min_duration_sec:
            valid_segments.append((seg_start, seg_end))

    return valid_segments


def export_slice(final_seg, base_path, sample_rate, args):
    """根据参数格式化并导出切片，返回生成的文件名列表"""
    saved_files = []

    # 确定要导出的核心数据声道
    fmt_ch = args.slice_channel.lower()
    vad_ch = args.channel  # VAD 参考声道索引

    if fmt_ch == 'mono':
        if final_seg.ndim > 1 and final_seg.shape[1] > vad_ch:
            out_data = final_seg[:, vad_ch]
        else:
            out_data = final_seg[:, 0] if final_seg.ndim > 1 else final_seg
            
    elif fmt_ch == 'stereo':
        if final_seg.ndim > 1 and final_seg.shape[1] > vad_ch + 1:
            # 提取 VAD 声道及紧随其后的 1 个声道组成双声道
            out_data = final_seg[:, vad_ch : vad_ch + 2]
        elif final_seg.ndim > 1 and final_seg.shape[1] > vad_ch:
            # 存在 VAD 声道但没有下一个声道，复制该单声道凑齐双声道（防越界保护）
            mono_data = final_seg[:, vad_ch]
            out_data = np.column_stack((mono_data, mono_data))
        else:
            # 输入本身就是单声道或异常维度时，直接复制为双声道
            mono_data = final_seg if final_seg.ndim == 1 else final_seg[:, 0]
            out_data = np.column_stack((mono_data, mono_data))
            
    else: # 'all'
        out_data = final_seg

    fmt = args.slice_fmt.lower()

    # 导出 PCM 逻辑
    if fmt == 'pcm':
        pcm_path = base_path.with_suffix(".pcm")
        with open(pcm_path, "wb") as f:
            f.write(out_data.tobytes())
        saved_files.append(pcm_path.name)

        # 追加生成 WAV 试听文件（取 VAD 用到的参考声道）
        wav_path = base_path.with_suffix(".wav")
        vad_ch = args.channel
        if final_seg.ndim > 1 and final_seg.shape[1] > vad_ch:
            mono_audition = final_seg[:, vad_ch]
        else:
            mono_audition = final_seg[:, 0] if final_seg.ndim > 1 else final_seg
        sf.write(wav_path, mono_audition, sample_rate, subtype='PCM_16')
        saved_files.append(wav_path.name)

    # 导出 WAV 逻辑
    elif fmt == 'wav':
        wav_path = base_path.with_suffix(".wav")
        sf.write(wav_path, out_data, sample_rate, subtype='PCM_16')
        saved_files.append(wav_path.name)

    return saved_files


def process_directory(args):
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    df = None
    if args.excel:
        excel_path = Path(args.excel)
        if not excel_path.exists():
            print(f"[!] 错误: 找不到指定的 Excel 文件 '{excel_path}'")
            return

        sheet_name = int(args.sheet) if args.sheet.isdigit() else args.sheet
        print(f"[*] 正在加载 Excel 文本映射库: {excel_path.name} (Sheet: {sheet_name})")

        try:
            df = pd.read_excel(excel_path, sheet_name=sheet_name, header=0)
        except Exception as e:
            print(f"[!] 无法读取 Excel 文件或指定 Sheet: {e}")
            return

    error_set = parse_error_segments(args.error_segments)
    if error_set:
        print(f"[*] 接收到误录校准参数，长音频中的第 {sorted(list(error_set))} 个切片将被标记为废片并跳过 Excel 匹配")

    resolved_path = input_path.resolve()

    # 支持的音频后缀
    valid_exts = {".wav"}

    if resolved_path.is_file():
        if resolved_path.suffix.lower() not in valid_exts:
            print(f"[!] 警告: 传入的文件 '{resolved_path.name}' 格式可能不受支持。")
        audio_files = [input_path]
    elif resolved_path.is_dir():
        # 扫描 wav 文件
        audio_files = []
        for ext in valid_exts:
            audio_files.extend(input_path.glob(f"*{ext}"))
            audio_files.extend(input_path.glob(f"*{ext.upper()}"))
        audio_files = sorted(list(set(audio_files)))
    else:
        print(f"[!] 错误: 路径 '{input_path}' 无效。")
        return

    for file_path in audio_files:
        print(f"\n[{'='*40}]")
        print(f"[*] 正在处理长音频: {file_path.name}")

        col_name, start_row, end_row = parse_filename(file_path.stem)
        expected_count = (end_row - start_row + 1) if end_row else None

        matched_col = None
        if df is not None:
            if col_name in df.columns:
                matched_col = col_name
            else:
                for col in df.columns:
                    if str(col).strip().upper() == col_name.upper():
                        matched_col = col
                        break

        try:
            data, sample_rate = sf.read(file_path, dtype='int16')
        except Exception as e:
            print(f"  [!] 无法读取音频数据: {e}")
            continue

        # 提取用于断句检测 (VAD) 的声道
        if data.ndim > 1:
            vad_ch = args.channel if args.channel < data.shape[1] else 0
            mono_data = data[:, vad_ch]
        else:
            mono_data = data

        segments = split_by_silence(
            mono_data, sample_rate, args.silence_threshold,
            args.min_silence, args.buffer, args.min_duration
        )
        actual_count = len(segments)

        # 校验 1: 未能切出有效片段
        if not segments:
            print("  [⚠️] 未能切出任何有效片段！")
            continue

        # 校验 2: 结合 error_set 校验切片数量
        if expected_count is not None:
            required_total = expected_count + len(error_set)

            if actual_count != required_total:
                print(f"  [⚠️] 数量不匹配！(预期文本 {expected_count} + 废片 {len(error_set)} = {required_total}，实际切出 {actual_count})")
                continue
            else:
                valid_export_count = actual_count - len(error_set)
                if error_set:
                    print(f"  [✔] 数量完美契合！实际切出 {actual_count} 个物理切片（含 {valid_export_count} 个有效文本 + {len(error_set)} 个隔离废片），允许导出。")
                else:
                    print(f"  [✔] 数量完美契合 ({valid_export_count} 片段)，允许导出文件。")
        else:
            if error_set:
                valid_export_count = actual_count - len(error_set)
                print(f"  [*] 未设定预期数量范围，实际切出 {actual_count} 个物理切片（含 {valid_export_count} 个有效导出 + {len(error_set)} 个隔离废片）。")
            else:
                print(f"  [*] 未设定预期数量范围，按实际切出 {actual_count} 个片段导出。")

        sub_dir = output_dir / col_name
        sub_dir.mkdir(exist_ok=True, parents=True)
        current_row = start_row

        for idx, (seg_start, seg_end) in enumerate(segments, start=1):
            final_seg = data[seg_start:seg_end]

            # 废片隔离判定
            if idx in error_set:
                base_name = f"{current_row}_[第{idx}个物理切片-废弃]"
                saved_names = export_slice(final_seg, sub_dir / base_name, sample_rate, args)

                files_str = saved_names[0] + ' & .wav' if len(saved_names) > 1 else saved_names[0]
                print(f"    [!] 第 {idx} 个物理切片为误录 -> {col_name}/{files_str}")
                continue

            # 正常切片
            if df is not None and matched_col is not None:
                df_idx = current_row - 2
                if 0 <= df_idx < len(df):
                    raw_cell_value = df.at[df_idx, matched_col]
                    cell_value = sanitize_filename(raw_cell_value)
                else:
                    cell_value = "OUT_OF_BOUNDS"
                base_name = f"{current_row}_{cell_value}"
                log_prefix = f"    [+] 导出第 {idx} 个切片 - 对齐 Excel 第 {current_row} 行"
            else:
                base_name = f"{current_row}_Idx{idx:02d}"
                log_prefix = f"    [+] 导出"

            saved_names = export_slice(final_seg, sub_dir / base_name, sample_rate, args)
            files_str = saved_names[0] + ' & .wav' if len(saved_names) > 1 else saved_names[0]
            print(f"{log_prefix} -> {col_name}/{files_str}")
            current_row += 1

    print("\n[✔] 任务处理完毕！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="长音频断句与格式导出集成工具")
    parser.add_argument("input", help="输入的音频文件或文件夹（可直接传入 abnormal 文件夹路径）")
    parser.add_argument("-o", "--output-dir", default="output", help="输出根目录")

    # ---------------- 导出与格式参数 ----------------
    parser.add_argument("--slice-fmt", type=str, default="pcm", choices=["wav", "pcm"], help="导出切片的音频格式 (默认 pcm)")
    parser.add_argument("--slice-channel", type=str, default="all", choices=["mono", "stereo", "all"], help="导出切片的保留声道 (mono=VAD参考单声道, stereo=VAD及紧随其后的1个声道, all=保留所有声道)")

    # ---------------- VAD & Excel 控制参数 ----------------
    parser.add_argument("-c", "--channel", type=int, default=0, help="VAD 用于静音检测分析的参考声道索引 (默认 0 即左声道/第1声道)")
    parser.add_argument("-e", "--excel", default=None, help="Excel 文本映射库路径")
    parser.add_argument("-s", "--sheet", default='Sheet1', help="Excel 工作表名称或索引 (默认 'Sheet1')")
    parser.add_argument("-err", "--error-segments", default="", help="长音频中被判定为误读的物理切片索引 (如 '3' 或 '2,5')")

    # ---------------- fineturn 参数 ----------------
    parser.add_argument("--silence-threshold", type=float, default=0.03, help="声音判定阈值")
    parser.add_argument("--min-silence", type=float, default=3.0, help="断句最短静音秒数")
    parser.add_argument("--buffer", type=float, default=1.5, help="首尾留白秒数")
    parser.add_argument("--min-duration", type=float, default=4.0, help="最小有效时长")

    args = parser.parse_args()
    process_directory(args)