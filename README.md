# 语音语料自动化切割与对齐工具

本工具专为批量处理长音频语料设计，支持基于静音检测的自动切片，并能与 Excel 表格自动联动进行命名。特别针对录制过程中出现的“误读/废片”场景，提供了灵活的**平移对齐/直接放弃**容错机制。

## 🛠️ 快速安装

请确保您的 Python 环境中安装了必要的依赖：

```bash
pip install numpy soundfile openpyxl
```

## 📜 完整脚本

<details>
<summary>silence_splitter.py 点击查看完整代码</summary>

```python
import argparse
import numpy as np
import soundfile as sf
import re
from pathlib import Path
import openpyxl

# --- 辅助函数 ---
def get_start_idx_from_stem(stem):
    match = re.search(r'(\d+)', stem)
    return int(match.group(1)) if match else 1

def sanitize_filename(name):
    if name is None: return "EMPTY_CELL"
    return re.sub(r'[\\/*?:"<>|\s\t\n\r]', '_', str(name)).strip('_')

def find_column_by_header(sheet, header_name):
    for cell in sheet[1]:
        if cell.value and str(cell.value).strip() == header_name.strip():
            return cell.column, cell.column_letter
    return None, None

def parse_error_segments(err_str):
    if not err_str: return set()
    return set(int(x) for x in re.findall(r'\d+', err_str))

# --- 静音切分算法 ---
def split_by_silence(mono_data, sample_rate, silence_threshold, min_silence_sec, buffer_sec, min_duration_sec):
    abs_data = np.abs(mono_data)
    voice_indices = np.where(abs_data > silence_threshold)[0]
    if len(voice_indices) == 0: return []
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
        if (seg_end - seg_start) / sample_rate >= min_duration_sec:
            valid_segments.append((seg_start, seg_end))
    return valid_segments

# --- 主逻辑 ---
def process_directory(args):
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    
    sheet = None
    target_col_letter = None
    if args.excel:
        wb = openpyxl.load_workbook(args.excel, data_only=True)
        sheet = wb.active
        _, target_col_letter = find_column_by_header(sheet, args.column_name)
    
    error_set = parse_error_segments(args.error_segments)
    wav_files = [input_path] if input_path.is_file() else sorted(input_path.glob("*.wav"))
    
    for file_path in wav_files:
        print(f"[*] 处理中: {file_path.name}")
        data, sr = sf.read(file_path)
        mono_data = data[:, args.channel] if data.ndim > 1 else data
        current_row = get_start_idx_from_stem(file_path.stem)
        idx_counter = current_row
        
        segments = split_by_silence(mono_data, sr, args.silence_threshold, args.min_silence, args.buffer, args.min_duration)
        
        for idx, (seg_start, seg_end) in enumerate(segments, start=1):
            if idx_counter in error_set:
                file_name = f"{target_col_letter}{current_row}_[废弃不做重读]_{args.column_name}.wav"
                sf.write(output_dir / file_name, mono_data[seg_start:seg_end], sr)
                current_row += 1
                idx_counter += 1
                continue
            
            val = sanitize_filename(sheet[f"{target_col_letter}{current_row}"].value) if sheet else "Unknown"
            file_name = f"{target_col_letter}{current_row}_{args.column_name}_{val}.wav"
            sf.write(output_dir / file_name, mono_data[seg_start:seg_end], sr)
            current_row += 1
            idx_counter += 1
    print("[✔] 任务完成！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("-o", "--output-dir", default="outputs")
    parser.add_argument("-c", "--channel", type=int, default=0)
    parser.add_argument("-e", "--excel")
    parser.add_argument("-cn", "--column-name", default="快乐")
    parser.add_argument("-err", "--error-segments", default="")
    parser.add_argument("--silence-threshold", type=float, default=0.02)
    parser.add_argument("--min-silence", type=float, default=1.5)
    parser.add_argument("--buffer", type=float, default=0.3)
    parser.add_argument("--min-duration", type=float, default=1.0)
    args = parser.parse_args()
    process_directory(args)
```
</details>

<details>
<summary>rename_rm_prefix.py 点击查看完整代码</summary>

```python
import argparse
import re
from pathlib import Path

def remove_cell_prefix(args):
    target_dir = Path(args.dir)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"[!] 错误: 找不到指定的文件夹路径 '{target_dir}'")
        return

    # 匹配模式：形如 B39_快乐_xxx.wav 或 C1251_[误读废片]_xxx.wav
    # 正则解析：以字母开头，后面紧跟数字，再跟着一个下划线
    prefix_pattern = re.compile(r'^[A-Za-z]+\d+_(.*)$')

    print(f"[*] 开始扫描目录 '{target_dir.name}' 中的 WAV 切片...")
    
    wav_files = sorted(target_dir.glob("*.wav"))
    success_count = 0
    skip_count = 0

    for file_path in wav_files:
        old_name = file_path.name
        match = prefix_pattern.match(old_name)
        
        if match:
            # 提取去掉前缀后的新名称
            new_name = match.group(1)
            
            # 如果你在核对时保留了带有 [误读废片] 的文件，这里可以顺便过滤掉或者保留
            if args.drop_error and "[误读废片]" in new_name:
                print(f"  [-] 自动清理废片: {old_name} -> [物理删除]")
                file_path.unlink()  # 直接删除误读的废品音频
                success_count += 1
                continue

            new_file_path = file_path.with_name(new_name)
            
            # 安全防重名碰撞机制
            if new_file_path.exists():
                # 如果已经存在同名文件（比如重读片段和废片去前缀后重名），自动加后缀保护
                counter = 1
                while new_file_path.exists():
                    stem = new_file_path.stem
                    # 如果原先就有 _重读 或 _v2 顺延，没有就加 _counter
                    new_file_path = file_path.with_name(f"{stem}_{counter}.wav")
                    counter += 1
            
            # 物理执行重命名
            file_path.rename(new_file_path)
            print(f"  [✔] 成功清洗: {old_name} -> {new_file_path.name}")
            success_count += 1
        else:
            # 没有匹配到 B39_ 这种前缀的文件，保持原样不动
            skip_count += 1

    print(f"\n[✔] 重命名任务安全完成！")
    print(f"    - 成功清洗/处理文件: {success_count} 个")
    print(f"    - 忽略（无需处理）: {skip_count} 个")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一键去除音频切片名中的 Excel 单元格坐标前缀")
    
    # 必需参数：切片所在的文件夹
    parser.add_argument("dir", nargs="?", default="excel_named_wavs", help="切片音频所在的文件夹目录 (默认: excel_named_wavs)")
    
    # 可选参数：是否在去前缀的同时，把带有 '[误读废片]' 字样的音频直接物理删除
    parser.add_argument("--drop-error", action="store_true", help="是否顺便一键彻底删除带有 '[误读废片]' 标志的音频")

    args = parser.parse_args()
    remove_cell_prefix(args)
```
</details>

---

## 🚀 使用方法

### 1. 基础切割
```bash
python silence_splitter.py input_audio.wav -e data.xlsx -cn 快乐
```

### 2. 应对“误读且不重读”场景
当录制者告知序号 `50` 误读且不重读时，脚本会自动跳过对应的 Excel 行，并保留废片供核对：
```bash
python silence_splitter.py input_audio.wav -e data.xlsx -cn 快乐 -err 50
```

### 3. 核对与清洗
完成核对后，使用辅助去前缀脚本（如有）去除物理坐标前缀，恢复成标准命名并自动清理废片：
```bash
python remove_prefix.py outputs/ --drop-error
```

---

## 💡 特性总结
* **精准溯源**：切片名强制附带 `B39_` 等单元格坐标，听感核对时无需查找 Excel。
* **防错位机制**：通过 `-err` 传入序号，彻底解决误读导致的后续语料错位问题。
* **物理隔离**：废弃片段被明确标记，并支持一键自动化物理销毁。