import os
import pandas as pd

def remove_duplicates_by_text(in_file, out_file='去重后结果.xlsx'):
    try:
        # 1. 根据文件后缀名自动读取数据
        if in_file.endswith('.csv'):
            # 如果是 CSV 文件，尝试用 utf-8-sig 读取（防止中文乱码）
            df = pd.read_csv(in_file, encoding='utf-8-sig')
        elif in_file.endswith('.xlsx') or in_file.endswith('.xls'):
            df = pd.read_excel(in_file)
        else:
            print("不支持的文件格式，请使用 .xlsx 或 .csv 文件")
            return

        print(f"成功读取文件，原始数据共 {len(df)} 行。")

        # 2. 处理分类列中的空白（合并单元格导致或空白填充）
        # 将空字符串或纯空格替换为 NaN，以便使用 ffill
        if '分类' in df.columns:
            df['分类'] = df['分类'].replace(r'^\s*$', pd.NA, regex=True)
            # 向下填充：用上一行的分类填补当前的空白
            df['分类'] = df['分类'].ffill()

        # 3. 按 "文本" 列去重，keep='first' 表示保留首次出现的记录
        if '文本' in df.columns:
            # strip() 去除文本首尾多余空格，防止因空格导致去重失败
            df['文本'] = df['文本'].astype(str).str.strip()
            
            df_unique = df.drop_duplicates(subset=['文本'], keep='first')
            print(f"去重完成！保留了首次出现的记录，剩余 {len(df_unique)} 行。")
        else:
            print("错误：文件中未找到 '文本' 列，请检查列名。")
            return

        # 4. 保存为标准 Excel 文件
        df_unique.to_excel(out_file, index=False)
        print(f"结果已成功保存至: {os.path.abspath(out_file)}")

    except Exception as e:
        print(f"处理过程中出现错误: {e}")

# ==================== 参数配置 ====================
# 将你的输入文件路径填写在这里（支持 .xlsx 或 .csv）
in_file = '录音文本_new.xlsx' 

# 运行去重函数
remove_duplicates_by_text(in_file)