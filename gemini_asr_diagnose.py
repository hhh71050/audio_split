import argparse
import json
import os
import time
from pathlib import Path
from typing import List, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tqdm import tqdm

from google import genai
from google.genai import types

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("[!] 错误: 请确保 .env 中已配置 GEMINI_API_KEY")

client = genai.Client(api_key=api_key)


class SingleDiagnosis(BaseModel):
    index: int = Field(description="对应输入列表中的 index 标识")
    Fail_category: Literal["同音近音", "吞字漏字", "多字插入", "同义替换", "严重幻觉", "其他"]
    description: str = Field(description="多项错词请用 '|' 分隔")


class BatchDiagnosisResponse(BaseModel):
    results: List[SingleDiagnosis]


def diagnose_batch_records(items: list[dict], max_retries: int = 3) -> list[dict]:
    items_text = json.dumps(items, ensure_ascii=False, indent=2)
    prompt = f"""
    作为 ASR 数据分析专家，请对以下 JSON 数组中的每一项进行错误归因诊断。
    待诊断列表: {items_text}
    输出要求：
    1. 保留原有 index。
    2. 【同音近音】或【同义替换】时，description 使用 "预期词 -> 实际词" 格式，多项用 '|' 分隔。
    3. 【吞字漏字】或【多字插入】时，明确指出多/少了什么字。
    4. 严重幻觉或其他情况用 20 字以内简述。
    """
    for attempt in range(max_retries):
        try:
            chat = client.chats.create(model="gemini-1.5-flash")
            response = chat.send_message(
                message=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchDiagnosisResponse,
                    temperature=0.0,
                ),
            )
            res_data = json.loads(response.text)
            return res_data.get("results", [])
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt < max_retries - 1:
                    tqdm.write("[!] 触发限流，休眠 60 秒后重试...")
                    time.sleep(60)
                    continue
            tqdm.write(f"[!] Batch 诊断失败: {e}")
            return []
    return []


def generate_single_sheet_summary(df: pd.DataFrame, output_path: Path):
    total_count = len(df)
    pass_count = (df["Match"] == "Pass").sum()
    fail_count = (df["Match"] == "Fail").sum()
    acc = (pass_count / total_count) if total_count > 0 else 0.0

    summary_rows = [
        {"统计维度 / 归因细节": "◆ 1. 整体识别 Acc 统计 ◆", "数量": "", "占比": ""},
        {"统计维度 / 归因细节": "总样本数", "数量": total_count, "占比": "100.00%"},
        {"统计维度 / 归因细节": "Pass (一致)", "数量": pass_count, "占比": f"{pass_count/total_count:.2%}" if total_count else "0.00%"},
        {"统计维度 / 归因细节": "Fail (不一致)", "数量": fail_count, "占比": f"{fail_count/total_count:.2%}" if total_count else "0.00%"},
        {"统计维度 / 归因细节": "整体一致率 (Acc)", "数量": f"{acc:.2%}", "占比": "-"},
        {"统计维度 / 归因细节": "", "数量": "", "占比": ""},
        {"统计维度 / 归因细节": "◆ 2. Fail 错误归因层级拆解 ◆", "数量": "", "占比(占Fail总数)": ""},
    ]

    if fail_count > 0:
        fail_df = df[df["Match"] == "Fail"].copy()
        cat_counts = fail_df["Fail_category"].value_counts(dropna=False)
        for cat_name, c_count in cat_counts.items():
            cat_display = str(cat_name) if pd.notna(cat_name) else "未分类"
            summary_rows.append({
                "统计维度 / 归因细节": f"【{cat_display}】",
                "数量": c_count,
                "占比(占Fail总数)": f"{c_count/fail_count:.2%}"
            })
            desc_items = []
            for desc in fail_df[fail_df["Fail_category"] == cat_name]["description"].dropna():
                desc_str = str(desc).strip()
                if desc_str in ["解析失败", "API限流失败", "None"]:
                    continue
                desc_items.extend([p.strip() for p in desc_str.split("|") if p.strip()])
            if desc_items:
                for desc_item, d_count in pd.Series(desc_items).value_counts().items():
                    summary_rows.append({
                        "统计维度 / 归因细节": f"    └─ {desc_item}",
                        "数量": d_count,
                        "占比(占Fail总数)": f"{d_count/fail_count:.2%}"
                    })

    summary_df = pd.DataFrame(summary_rows)

    # 防御性清洗，防止 Excel 公式注入
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(
                lambda x: f"'{x}" if isinstance(x, str) and str(x).startswith(('=', '+', '-', '@')) else x
            )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总报告", index=False)
        df.to_excel(writer, sheet_name="诊断明细", index=False)

    print(f"[+] 报表保存至: {output_path.resolve()}")


def process_in_batches(df: pd.DataFrame, output_path: Path, batch_size: int = 10, chunk_save_size: int = 50):
    if "Fail_category" not in df.columns:
        df["Fail_category"] = None
    if "description" not in df.columns:
        df["description"] = None

    target_mask = (df["Match"] == "Fail") & (df["Fail_category"].isna() | (df["Fail_category"] == ""))
    target_indices = df[target_mask].index.tolist()

    if target_indices:
        print(f"[*] 待诊断共 {len(target_indices)} 条。Batch Size: {batch_size}")
        all_batches = []
        for i in range(0, len(target_indices), batch_size):
            batch_ids = target_indices[i:i + batch_size]
            batch_payload = []
            for idx in batch_ids:
                exp = str(df.at[idx, "Norm_Exp"]) if "Norm_Exp" in df.columns and pd.notna(df.at[idx, "Norm_Exp"]) else str(df.at[idx, "Expected"])
                act = str(df.at[idx, "Norm_Act"]) if "Norm_Act" in df.columns and pd.notna(df.at[idx, "Norm_Act"]) else str(df.at[idx, "Actual"])
                batch_payload.append({"index": idx, "expected": exp, "actual": act})
            all_batches.append(batch_payload)

        processed_count = 0
        for batch_items in tqdm(all_batches, desc="Batch 诊断进度", colour="green"):
            results = diagnose_batch_records(batch_items)
            for res in results:
                idx = res.get("index")
                if idx in df.index:
                    df.at[idx, "Fail_category"] = res.get("Fail_category")
                    df.at[idx, "description"] = res.get("description")
            processed_count += len(batch_items)
            if processed_count >= chunk_save_size:
                df.to_excel(output_path, index=False)
                processed_count = 0
            time.sleep(1.0)
    else:
        print("[*] 没有需要诊断的 Fail 记录。")

    generate_single_sheet_summary(df, output_path)


def main():
    parser = argparse.ArgumentParser(description="Gemini ASR 归因诊断工具")
    parser.add_argument("-i", "--input", default="ASR_recognized.xlsx", help="输入 Excel 路径")
    parser.add_argument("-o", "--output", default=None, help="输出 Excel 路径 (默认覆盖输入)")
    parser.add_argument("-b", "--batch_size", type=int, default=10, help="单次 API 打包条数")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"[!] 错误: 找不到输入文件 {input_path}")

    output_path = Path(args.output) if args.output else input_path
    df = pd.read_excel(input_path)

    # 若未衍生 Norm 列，自动生成
    if "Norm_Exp" not in df.columns:
        print("[*] 正在衍生 Norm_Exp 列...")
        df["Norm_Exp"] = df["Expected"].apply(lambda x: str(x) if pd.notna(x) else "")
    if "Norm_Act" not in df.columns:
        print("[*] 正在衍生 Norm_Act 列...")
        df["Norm_Act"] = df["Actual"].apply(lambda x: str(x) if pd.notna(x) else "")

    process_in_batches(df, output_path, batch_size=args.batch_size)


if __name__ == "__main__":
    main()