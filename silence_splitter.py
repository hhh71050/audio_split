import argparse
import numpy as np
import soundfile as sf
import re
from pathlib import Path

try:
    import openpyxl
except ImportError:
    import sys
    print("[!] 错误: 缺少必要依赖库 'openpyxl'。请先在终端运行: pip install openpyxl")
    sys.exit(1)

def get_start_idx_from_stem(stem):
    """
    从输入文件名中提取起始行号
    例如：'快乐_40-60' -> 40
    """
    match = re.search(r'(\d+)', stem)
    if match:
        return int(match.group(1))
    return 1

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
    target_col_letter = None
    
    if args.excel:
        excel_path = Path(args.excel)
        if not excel_path.exists():
            print(f"[!] 错误: 找不到指定的 Excel 文件 '{excel_path}'")
            return
        print(f"[*] 正在加载 Excel 文本映射库: {excel_path.name}")
        try:
            workbook = openpyxl.load_workbook(excel_path, data_only=True)
            sheet = workbook.active
            _, target_col_letter = find_column_by_header(sheet, args.column_name)
            if not target_col_letter:
                print(f"[!] 错误: 在 Excel 第一行没找到列名为 '{args.column_name}' 的列。")
                return
            print(f"  [✔] 成功定位: 列名 '{args.column_name}' 位于 Excel 的 [{target_col_letter}] 列")
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
        
        try:
            data, sample_rate = sf.read(file_path)
        except Exception as e:
            print(f"  [!] 无法读取音频数据: {e}")
            continue

        mono_data = data[:, args.channel] if data.ndim > 1 else data
        start_row = get_start_idx_from_stem(file_path.stem)
        print(f"  [*] 对齐 Excel 起始行号: {start_row}")
        
        segments = split_by_silence(
            mono_data, sample_rate, args.silence_threshold, 
            args.min_silence, args.buffer, args.min_duration
        )

        if not segments:
            print(f"  [-] 未能在当前文件中切分出有效片段。")
            continue

        print(f"  [*] 实际切出 {len(segments)} 个片段，开始对齐导出...")
        
        current_row = start_row      # 控制消耗哪一行文本
        idx_counter = start_row      # 控制当前切片的名义物理序号
        
        for idx, (seg_start, seg_end) in enumerate(segments, start=1):
            final_seg = mono_data[seg_start:seg_end]
            
            # 1. 触发误读漏报隔离逻辑
            if idx_counter in error_set:
                # 即使是废片，也带上它原本想对齐的单元格坐标作为前缀，方便你听声音核对是不是这一句读错了
                if target_col_letter:
                    cell_coord = f"{target_col_letter}{current_row}"
                    file_name = f"{cell_coord}_[误读废片]_{args.column_name}.wav"
                else:
                    file_name = f"Row{current_row}_[误读废片]_{args.column_name}.wav"
                    
                sf.write(output_dir / file_name, final_seg, sample_rate)
                print(f"    [!] 片段 {idx} 命中误读 (序号 {idx_counter}) -> 已隔离为: {file_name}")
                
                idx_counter += 1  # 名义序号递增
                continue          # 保持 current_row 不变，直接跳过本片段
                
            # 2. 正常切片动态命名逻辑
            if sheet is not None and target_col_letter is not None:
                cell_coord = f"{target_col_letter}{current_row}" # 单元格名称框，如 "B39"
                raw_cell_value = sheet[cell_coord].value
                cell_value = sanitize_filename(raw_cell_value)
                
                # 核心改动：把单元格坐标名称框拼接到最前面
                file_name = f"{cell_coord}_{args.column_name}_{cell_value}.wav"
                log_msg = f"    [+] 导出第 {idx} 个切片: {file_name}"
            else:
                file_name = f"Row{current_row}_Idx{idx}_{args.column_name}.wav"
                log_msg = f"    [+] 导出: {file_name}"
            
            sf.write(output_dir / file_name, final_seg, sample_rate)
            print(log_msg)
            
            current_row += 1
            idx_counter += 1

    print("\n[✔] 带有单元格坐标的切片导出任务已全部安全完成！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="纯静音音频切割与 Excel 单元格坐标名称框联动工具")
    parser.add_argument("input", help="输入的音频文件或文件夹")
    parser.add_argument("-o", "--output-dir", default="excel_named_wavs", help="输出目录")
    parser.add_argument("-c", "--channel", type=int, default=0, help="声道索引")
    parser.add_argument("-e", "--excel", default=None, help="Excel文件路径")
    parser.add_argument("-cn", "--column-name", default="快乐", help="目标列名")
    parser.add_argument("-err", "--error-segments", default="", help="录制者漏报/误录的序号")

    parser.add_argument("--silence-threshold", type=float, default=0.05, help="声音判定阈值")
    parser.add_argument("--min-silence", type=float, default=0.7, help="断句最短静音秒数")
    parser.add_argument("--buffer", type=float, default=0.3, help="首尾留白秒数")
    parser.add_argument("--min-duration", type=float, default=1.0, help="最小有效时长")

    args = parser.parse_args()
    process_directory(args)