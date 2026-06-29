from pathlib import Path
import argparse
import numpy as np
import soundfile as sf
import re

try:
    import openpyxl
except ImportError:
    import sys
    print("[!] 错误: 缺少必要依赖库 'openpyxl'。请先在终端运行: pip install openpyxl")
    sys.exit(1)


def parse_filename(stem):
    """
    解析文件名获取：列名, 起始行号, 结束行号
    示例: "愤怒_3827-3846" -> ("愤怒", 3827, 3846)
    """
    match = re.search(r'(.*)_(\d+)-(\d+)', stem)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    
    # 回退兼容: 只有数字区间 "3827-3846"
    match_num = re.search(r'(\d+)-(\d+)', stem)
    if match_num:
        return "Unknown", int(match_num.group(1)), int(match_num.group(2))
    
    # 再回退: 只有起始数字 "3827"
    match_single = re.search(r'(\d+)', stem)
    if match_single:
        return "Unknown", int(match_single.group(1)), None
        
    return "Unknown", 1, None

def sanitize_filename(name):
    """安全过滤文件名非法字符，防系统报错"""
    if name is None:
        return "EMPTY_CELL"
    clean_name = re.sub(r'[\\/*?:"<>|\s\t\n\r]', '_', str(name))
    return clean_name.strip('_')

def find_column_by_header(sheet, header_name):
    """在 Excel 第一行动态寻找匹配列名的列字母"""
    for cell in sheet[1]:
        if cell.value and str(cell.value).strip() == header_name.strip():
            return cell.column, cell.column_letter
    return None, None

def parse_error_segments(err_str):
    """解析输入的误读序号，转为整型集合"""
    if not err_str:
        return set()
    return set(int(x) for x in re.findall(r'\d+', err_str))

def split_by_silence(mono_data, sample_rate, silence_threshold, min_silence_sec, buffer_sec, min_duration_sec):
    """核心静音切分算法"""
    abs_data = np.abs(mono_data)
    voice_indices = np.where(abs_data > silence_threshold)[0]

    if len(voice_indices) == 0:
        return []

    gap_samples = int(sample_rate * min_silence_sec)
    jumps = np.where(np.diff(voice_indices) > gap_samples)[0]

    starts = np.insert(voice_indices[jumps + 1], 0, voice_indices[0])
    ends = np.append(voice_indices[jumps], voice_indices[-1])
    clusters = list(zip(starts, ends))

    valid_segments = []
    buffer_samples = int(sample_rate * buffer_sec)

    for c_start, c_end in clusters:
        seg_start = max(0, c_start - buffer_samples)
        seg_end = min(len(mono_data), c_end + buffer_samples)

        duration = (seg_end - seg_start) / sample_rate
        if duration >= min_duration_sec:
            valid_segments.append((seg_start, seg_end))

    return valid_segments

def process_directory(args):
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    sheet = None

    if args.excel:
        excel_path = Path(args.excel)
        if not excel_path.exists():
            print(f"[!] 错误: 找不到指定的 Excel 文件 '{excel_path}'")
            return
        print(f"[*] 正在加载 Excel 文本映射库: {excel_path.name}")
        try:
            workbook = openpyxl.load_workbook(excel_path, data_only=True)
            sheet = workbook.active
        except Exception as e:
            print(f"[!] 无法读取 Excel 文件: {e}")
            return

    # 解析误读序号列表
    error_set = parse_error_segments(args.error_segments)
    if error_set:
        print(f"[*] 接收到漏报/误录校准参数，以下序号视为【误读片段】: {sorted(list(error_set))}")

    if input_path.is_file() and input_path.suffix.lower() == '.wav':
        wav_files = [input_path]
    elif input_path.is_dir():
        wav_files = sorted(input_path.glob("*.wav"))
    else:
        print(f"[!] 错误: 路径 '{input_path}' 无效。")
        return

    for file_path in wav_files:
        print(f"\n[{'='*40}]")
        print(f"[*] 正在处理长音频: {file_path.name}")
        
        # 1. 动态解析文件名信息
        col_name, start_row, end_row = parse_filename(file_path.stem)
        expected_count = (end_row - start_row + 1) if end_row else None
        
        # 创建以列名（如“愤怒”）命名的子文件夹
        sub_dir = output_dir / col_name
        sub_dir.mkdir(exist_ok=True, parents=True)
        
        # 2. 动态匹配 Excel 目标列
        target_col_letter = None
        if sheet:
            _, target_col_letter = find_column_by_header(sheet, col_name)
            if target_col_letter:
                print(f"  [✔] 成功定位: 列名 '{col_name}' 位于 Excel 的 [{target_col_letter}] 列")
            else:
                print(f"  [!] 警告: 在 Excel 第一行没找到列名为 '{col_name}' 的列。")

        try:
            data, sample_rate = sf.read(file_path)
        except Exception as e:
            print(f"  [!] 无法读取音频数据: {e}")
            continue

        mono_data = data[:, args.channel] if data.ndim > 1 else data
        print(f"  [*] 对齐 Excel 起始行号: {start_row}")

        segments = split_by_silence(
            mono_data, sample_rate, args.silence_threshold,
            args.min_silence, args.buffer, args.min_duration
        )
        actual_count = len(segments)

        if not segments:
            print(f"  [-] 未能在当前文件中切分出有效片段。")
            continue

        # 3. 警示校验逻辑
        if expected_count is not None:
            if actual_count == expected_count:
                print(f"  [✔] 数量完美匹配: 预期 {expected_count} 个，实际切出 {actual_count} 个。")
            else:
                print(f"  [!] ⚠️ Warning: 切片数量异常！文件名预期区间需要 {expected_count} 个片段，实际却切出 {actual_count} 个。")
        else:
            print(f"  [*] 实际切出 {actual_count} 个片段。")
            
        print(f"  [*] 开始对齐导出...")

        current_row = start_row      # 控制消耗哪一行文本
        idx_counter = start_row      # 控制当前切片的名义物理序号

        for idx, (seg_start, seg_end) in enumerate(segments, start=1):
            final_seg = mono_data[seg_start:seg_end]

            # 当前物理序号是录制者告知的“直接废弃不做重读”的序号
            if idx_counter in error_set:
                if target_col_letter:
                    cell_coord = f"{target_col_letter}{current_row}"
                    file_name = f"{cell_coord}_[废弃不做重读].wav"
                else:
                    file_name = f"Row{current_row}_[废弃不做重读].wav"

                sf.write(sub_dir / file_name, final_seg, sample_rate)
                print(f"    [!] 片段 {idx} 属于废弃不重读行 (序号 {idx_counter}) -> 已隔离为: {col_name}/{file_name}")

                # 让 Excel 指针同步向下移动一行，去对齐接下来的正常音频！
                current_row += 1
                idx_counter += 1  # 名义序号递增
                continue

            # 正常切片动态命名逻辑
            if sheet is not None and target_col_letter is not None:
                cell_coord = f"{target_col_letter}{current_row}" # 单元格名称框，如 "B39"
                raw_cell_value = sheet[cell_coord].value
                cell_value = sanitize_filename(raw_cell_value)

                # 去除 col_name，直接使用坐标和单元格内容
                file_name = f"{cell_coord}_{cell_value}.wav"
                log_msg = f"    [+] 导出第 {idx} 个切片: {col_name}/{file_name}"
            else:
                file_name = f"Row{current_row}_Idx{idx:02d}.wav"
                log_msg = f"    [+] 导出: {col_name}/{file_name}"

            sf.write(sub_dir / file_name, final_seg, sample_rate)
            print(log_msg)

            current_row += 1
            idx_counter += 1

    print("\n[✔] 带有单元格坐标的切片导出任务已全部安全完成！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自动解析长音频文件名的切割工具")
    parser.add_argument("input", help="输入的音频文件或文件夹")
    parser.add_argument("-o", "--output-dir", default="excel_named_wavs", help="输出目录")
    parser.add_argument("-c", "--channel", type=int, default=0, help="声道索引")
    parser.add_argument("-e", "--excel", default=None, help="Excel文件路径")
    parser.add_argument("-err", "--error-segments", default="", help="录制者漏报/误录直接废弃的序号")

    parser.add_argument("--silence-threshold", type=float, default=0.025, help="声音判定阈值")
    parser.add_argument("--min-silence", type=float, default=0.5, help="断句最短静音秒数")
    parser.add_argument("--buffer", type=float, default=0.25, help="首尾留白秒数")
    parser.add_argument("--min-duration", type=float, default=1.5, help="最小有效时长")

    args = parser.parse_args()
    process_directory(args)