from pathlib import Path
import argparse
import numpy as np
import soundfile as sf
import re

try:
    import openpyxl
except ImportError:
    import sys
    print("[!] 错误: 缺少依赖 'openpyxl'。请运行: pip install openpyxl")
    sys.exit(1)


def parse_filename(stem):
    """解析文件名：列名/字母标识, 起始行号, 结束行号 (如 'A_122-141')"""
    match = re.search(r'(.*)_(\d+)-(\d+)', stem)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    
    match_num = re.search(r'(\d+)-(\d+)', stem)
    if match_num:
        return "Unknown", int(match_num.group(1)), int(match_num.group(2))
    
    match_single = re.search(r'(\d+)', stem)
    if match_single:
        return "Unknown", int(match_single.group(1)), None
        
    return "Unknown", 1, None

def sanitize_filename(name):
    """过滤文件名非法字符"""
    if name is None:
        return "EMPTY_CELL"
    clean_name = re.sub(r'[\\/*?:"<>|\s\t\n\r]', '_', str(name))
    return clean_name.strip('_')

def find_column_by_header(sheet, header_name):
    """寻找 Excel 列"""
    header_name_clean = header_name.strip()
    if re.match(r'^[A-Za-z]+$', header_name_clean):
        return None, header_name_clean.upper()

    for cell in sheet[1]:
        if cell.value and str(cell.value).strip() == header_name_clean:
            return cell.column, cell.column_letter
    return None, None

def parse_error_segments(err_str):
    if not err_str:
        return set()
    return set(int(x) for x in re.findall(r'\d+', err_str))

def format_time(seconds):
    """将秒数转为 mm:ss"""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

def detect_silence_segments(mono_data, sample_rate, silence_threshold, min_silence_sec, buffer_sec, min_duration_sec):
    """核心静音检测算法，计算带 buffer 的始末时间点 (允许 overlap)"""
    abs_data = np.abs(mono_data)
    
    # 自动适应 float32 或 int16 范围
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

    for c_start, c_end in clusters:
        # 补入留白，边界保护但不强行裁剪交集 (允许前后片段重叠)
        seg_start = max(0, c_start - buffer_samples)
        seg_end = min(total_samples, c_end + buffer_samples)

        duration = (seg_end - seg_start) / sample_rate
        if duration >= min_duration_sec:
            start_sec = seg_start / sample_rate
            end_sec = seg_end / sample_rate
            valid_segments.append((start_sec, end_sec))

    return valid_segments

def process_labels(args):
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    sheet = None
    if args.excel:
        excel_path = Path(args.excel)
        if excel_path.exists():
            print(f"[*] 加载 Excel 文本库: {excel_path.name}")
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            sheet = wb.active

    error_set = parse_error_segments(args.error_segments)
    wav_files = [input_path] if (input_path.is_file() and input_path.suffix.lower() == '.wav') else sorted(input_path.glob("*.wav"))

    for file_path in wav_files:
        print(f"\n[{'='*40}]")
        print(f"[*] 正在生成 Audacity 标签: {file_path.name}")

        col_name, start_row, end_row = parse_filename(file_path.stem)
        expected_count = (end_row - start_row + 1) if end_row else None

        target_col_letter = None
        if sheet:
            _, target_col_letter = find_column_by_header(sheet, col_name)

        try:
            data, sample_rate = sf.read(file_path)
        except Exception as e:
            print(f"  [!] 无法读取音频数据: {e}")
            continue

        # 按指定通道提取
        mono_data = data[:, args.channel] if data.ndim > 1 else data

        segments = detect_silence_segments(
            mono_data, sample_rate, args.silence_threshold,
            args.min_silence, args.buffer, args.min_duration
        )

        actual_count = len(segments)
        if expected_count is not None and actual_count != expected_count:
            print(f"  [!] ⚠️ 数量预警: 预期 {expected_count} 个，实际检测出 {actual_count} 个区间。")
        else:
            print(f"  [✔] 检测出 {actual_count} 个时间区间。")

        # 准备生成 Audacity 标签文件
        label_file_path = output_dir / f"{file_path.stem}_labels.txt"
        label_lines = []

        current_row = start_row
        idx_counter = start_row

        for start_sec, end_sec in segments:
            # 精确到整数秒（根据要求 rounding/int 转换）
            s_sec = round(start_sec)
            e_sec = round(end_sec)

            if idx_counter in error_set:
                label_text = f"{current_row}_[废弃不做重读]"
            elif sheet and target_col_letter:
                cell_value = sanitize_filename(sheet[f"{target_col_letter}{current_row}"].value)
                label_text = f"{current_row}_{cell_value}"
            else:
                label_text = f"{current_row}_Unknown"

            # 格式：Start_sec\tEnd_sec\tLabel_Name
            label_lines.append(f"{s_sec}\t{e_sec}\t{label_text}")

            current_row += 1
            idx_counter += 1
            s_tm = format_time(s_sec)
            e_tm = format_time(e_sec)
            print(f"{s_tm}|{e_tm}|{cell_value}")

        # 写入标签文件
        with open(label_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(label_lines))

        print(f"  [✔] 标签文件已导出至: {label_file_path}")

    print("\n[✔] 所有 Audacity 标签文件生成完毕！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 Audacity 标签文件的轻量化脚本")
    parser.add_argument("input", help="输入的音频文件或文件夹")
    parser.add_argument("-o", "--output-dir", default="audacity_labels", help="输出标签文件的目录")
    parser.add_argument("-c", "--channel", type=int, default=0, help="用于静音检测的通道索引 (默认 0)")
    parser.add_argument("-e", "--excel", default=None, help="Excel 文件路径")
    parser.add_argument("-err", "--error-segments", default="", help="废弃跳过的序号")

    parser.add_argument("--silence-threshold", type=float, default=0.025, help="声音判定阈值")
    parser.add_argument("--min-silence", type=float, default=0.5, help="断句最短静音秒数")
    parser.add_argument("--buffer", type=float, default=0.25, help="首尾留白秒数")
    parser.add_argument("--min-duration", type=float, default=1.5, help="最小有效时长")

    args = parser.parse_args()
    process_labels(args)