from collections import Counter

def find_duplicates(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 读取所有行，并去除每行末尾的换行符和首尾空格
            lines = [line.strip() for line in f if line.strip()]
        
        # 使用 Counter 统计每行出现的次数
        counts = Counter(lines)
        
        # 筛选出出现次数大于 1 的行
        duplicates = {line: count for line, count in counts.items() if count > 1}
        
        if not duplicates:
            print("文件中没有发现重复的行。")
            return

        print(f"{'重复内容':<40} | {'出现次数'}")
        print("-" * 55)
        for line, count in duplicates.items():
            print(f"{line:<40} | {count}")

    except FileNotFoundError:
        print("错误：找不到指定的文件。")
    except Exception as e:
        print(f"发生错误: {e}")

# 请在此处填入你的 txt 文件路径
file_path = r'records\text.txt'
find_duplicates(file_path)