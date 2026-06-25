# 🎧 语音语料自动化切分与清洗工具链 (Audio Splitter & Cleaner)

本工具链包含两个高度自动化的 Python 脚本，专为语音大模型训练、ASR（自动语音识别）语料制作及数据标注前期准备而设计。通过将**长录音文件**与 **Excel 文本映射表**进行智能对齐，实现毫秒级精准切分、动态单元格命名、异常片段隔离及后期一键式安全清洗。

## 🏗️ 工具链整体工作流

```Text
[ 原始长录音 .wav ] （如: 愤怒_3827-3846.wav）
       +
[ 文本映射表 .xlsx ] --->  (1) silence_splitter.py (VAD 静音切分与动态对齐)
                               |
                               v
                     [ 格式化语料切片 .wav ] （如: B39_愤怒_语料文本.wav）
                               |
                               v
                           (核对无误后)
                               |
                               v
                     (2) remove_cell_prefix.py (一键去前缀/废片清理)
                               |
                               v
                     [ 终版干净语料 .wav ] （如: 愤怒_语料文本.wav）
```

## 🛠️ 核心功能特性

### 1. 自动化智能切分与 Excel 动态命名 (`silence_splitter.py`)
* **语义区间解析**：自动从长音频文件名（如 `情感列名_起始行-结束行.wav`）中提取并解析 Excel 位置参数。
* **动态列定位**：首行表头自动检索，精准对齐并定位目标文本列。
* **VAD 静音断句**：基于振幅阈值与最短静音时长控制，支持首尾留白平滑缓冲。
* **双向数量校验**：切片数量与 Excel 预期行数不匹配时自动触发 `⚠️ Warning` 警示，防漏切与误切。
* **故障序号隔离**：支持传入硬编码误读序号，自动隔离为 `[废弃不做重读]` 标记，指针自动下移对齐。

### 2. 语料清洗与去前缀工具 (`remove_cell_prefix.py`)
* **坐标前缀剥离**：一键去除清洗完工语料文件名中的 `B39_` 等单元格坐标前缀。
* **安全防重名碰撞**：去前缀后若发生重名（如同音字或重读片段），自动启用数字顺延机制（`_1.wav`, `_2.wav`）进行物理重名保护。
* **一键物理除渣**：支持可选参数，在去前缀的同时彻底删除带有 `[误读废片]` 标志的音频。

## 📦 环境依赖

由于涉及多模态数据交互，本工具链不依赖复杂的庞大框架（如 Conda 环境），推荐使用 Python 原生 `venv` 进行轻量化管理：

```Bash
# 创建并激活您的虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/WSL 2
# 或 .\venv\Scripts\activate (Windows)

# 安装核心音频与数据处理依赖
pip install openpyxl numpy soundfile
```

## 🚀 命令行快速参考

### 📑 脚本一：`silence_splitter.py` (切分与对齐)

运行此脚本将根据静音切分长音频，并从 Excel 中提取对应单元格的值作为文件名。

#### 核心参数说明：
| 参数 (Argument) | 短指令 | 默认值 | 功能描述 |
| :--- | :--- | :--- | :--- |
| `input` | 无 | *(必填)* | 输入的 `.wav` 长音频文件或包含多个 WAV 的文件夹路径。 |
| `--output-dir` | `-o` | `excel_named_wavs` | 切片音频的输出目录。 |
| `--excel` | `-e` | `None` | 对应的 Excel 文本库路径。 |
| `--error-segments`| `-err`| `""` | 录制者反馈需要直接废弃的物理切片序号（逗号/空格分隔）。 |
| `--silence-threshold`| 无 | `0.025` | 声音判定阈值（绝对振幅）。 |
| `--min-silence` | 无 | `0.5` | 断句所需的最短静音秒数。 |

#### 使用示例：

```Bash
# 基础批量切分（不带Excel文本映射）
python silence_splitter.py /path/to/wav_dir/ -o ./output_slices/

# 联动 Excel 实施动态文本命名，并隔离第 12, 15 个故障片段
python silence_splitter.py ./input_audio/ -e ./corpus_v1.xlsx -err "12 15" --silence-threshold 0.020
```

### 🧹 脚本二：`remove_cell_prefix.py` (清洗与归档)

语料核对及 ASR 标注修正完成后，用于快速剥离坐标前缀，使文件名更纯净，方便直接喂入大模型训练。

#### 核心参数说明：
| 参数 (Argument) | 默认值 | 功能描述 |
| :--- | :--- | :--- |
| `dir` | `excel_named_wavs` | 需要清洗的前缀切片所在的文件夹。 |
| `--drop-error` | `False` (不开启) | 若指定此参数，将顺便彻底物理删除含有 `[误读废片]` 标志的音频。 |

#### 使用示例：

```Bash
# 仅去掉文件名开头的单元格坐标前缀 (如 B39_愤怒_xxx.wav -> 愤怒_xxx.wav)
python remove_cell_prefix.py ./output_slices/

# 去前缀的同时，一键物理删除所有核对出的“误读废片”
python remove_cell_prefix.py ./output_slices/ --drop-error
```

## 📂 文件命名规范与系统安全性

1. **非法字符过滤**：`silence_splitter.py` 内置 `sanitize_filename` 模块，自动将 Excel 文本中包含的 Windows/Linux 文件系统非法字符（如 `\ / * ? : < > |` 及换行符、制表符）自动无缝替换为下划线 `_`，防止写入报错。
2. **崩溃保护**：去前缀脚本 `remove_cell_prefix.py` 具有安全重名碰撞机制，绝不发生代码执行覆盖，确保语料资产 100% 物理安全。