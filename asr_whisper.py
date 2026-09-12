#!/usr/bin/env python3
"""
Whisper 批量 ASR 识别脚本 (低配电脑 CPU 优化版)
- 默认采用 small 模型
- 强制限制 PyTorch CPU 线程数防卡死
- 文件名自适应解析，按系统默认顺序输出
"""

import argparse
import re
import time
from pathlib import Path

import torch
import pandas as pd
import cn2an
import whisper
from opencc import OpenCC
from tqdm import tqdm

# 初始化繁简转换器
cc = OpenCC('t2s')


def normalize_text(text: str) -> str:
    """清洗文本：去除非中英文字符 -> 繁转简 -> 中文数字转阿拉伯数字"""
    if not text or pd.isna(text):
        return ""

    # 1. 过滤非中英文字符和数字
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', str(text)).strip()

    # 2. 繁体转简体
    text = cc.convert(text)

    # 3. 中文数字归一化为阿拉伯数字
    try:
        text = cn2an.transform(text, "cn2an")
    except Exception:
        pass

    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="tts/wav", help="音频所在目录或文件")
    parser.add_argument("-o", "--output", default="Whisper_Report.csv", help="输出CSV路径")
    parser.add_argument("-m", "--model", default="small", choices=["small", "base"], help="模型名称 (默认: small)")
    parser.add_argument(
        "-w", "--threads", type=int, default=8,
        help="PyTorch使用的CPU线程数 (低配电脑建议 4)"
    )
    args = parser.parse_args()

    # [关键优化] 限制底层运算库的线程数，保护低配主机
    torch.set_num_threads(args.threads)

    input_path = Path(args.input)
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        # 直接使用系统默认按名排序
        files = sorted(
            f for f in input_path.iterdir()
            if f.suffix.lower() in {".wav", ".mp3", ".flac", ".m4a"}
        )
    else:
        return print(f"❌ 找不到输入路径: {input_path}")

    if not files:
        return print("❌ 未找到音频文件！")

    print(f"\n[*] 启动 Whisper (模型: {args.model} | CPU线程限制: {args.threads})...")
    start_time = time.perf_counter()

    # 加载模型
    model = whisper.load_model(args.model, device="cpu")
    print(f"[*] 模型加载完成，耗时 {time.perf_counter() - start_time:.1f}s\n")

    results = []

    # 批量推理
    for f in tqdm(files, desc="ASR 识别进度", unit="条"):
        stem = f.stem
        # 有 '_' 前缀则取后面作为 expected；否则整个 stem 为 expected
        expected = stem.split("_", 1)[1].strip() if "_" in stem else stem.strip()

        # 识别 (锁定束搜索为1和0度退火，最大程度节省内存与算力)
        try:
            res = model.transcribe(
                str(f), language="zh", fp16=False,
                beam_size=1, temperature=0.0
            )
            actual = res.get("text", "").strip() # type: ignore
        except Exception as e:
            tqdm.write(f"⚠️ {f.name} 识别失败: {e}")
            actual = ""

        # 对比逻辑
        norm_exp = normalize_text(expected)
        norm_act = normalize_text(actual)
        match_status = "Pass" if (norm_exp == norm_act) and norm_exp else "Fail"

        results.append({
            "File_Name": f.name,
            "Expected": expected,
            "Actual": actual,
            "norm_Expected": norm_exp,
            "norm_Actual": norm_act,
            "Match": match_status
        })

    # 输出报告
    df = pd.DataFrame(results)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")

    # 统计信息
    total = len(df)
    passed = len(df[df["Match"] == "Pass"])
    accuracy = (passed / total * 100) if total > 0 else 0
    m, s = divmod(time.perf_counter() - start_time, 60)

    print("\n" + "=" * 45)
    print(f"🎉 识别完成 | 总耗时: {m:.0f}分 {s:.0f}秒")
    print("-" * 45)
    print(f"📋 样本总数: {total} 条")
    print(f"✅ 完全匹配: {passed} 条")
    print(f"📊 准确率:   {accuracy:.1f}%")
    print(f"💾 保存至:   {args.output}")
    print("=" * 45)


if __name__ == "__main__":
    main()