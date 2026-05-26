from pathlib import Path

def rename_files_from_txt(folder, file_ext, names_text):
    """
    根据txt文件内容重命名文件夹内的文件

    Args:
        folder: 包含待重命名文件的文件夹路径
        file_ext: folder下指定的文件扩展名，以点(`.`)开始
        names_text: 包含新文件名的txt文件路径
    """

    # 检查文件夹是否存在
    fp = Path(folder)
    if not fp.exists():
        raise FileNotFoundError(f"错误：文件夹 '{folder}' 不存在")

    # 检查txt文件是否存在
    txtp = Path(names_text)
    if not txtp.exists():
        raise FileNotFoundError(f"错误：txt文件 '{names_text}' 不存在")

    # 读取txt文件中的所有行（新文件名）
    try:
        with open(names_text, 'r', encoding='utf-8') as f:
            new_names = [line.strip() for line in f if not line.startswith('#')]
        print(f"从txt文件中读取了 {len(new_names)} 个文件名")
    except Exception as e:
        print(f"读取txt文件时出错：{e}")
        return

    # 获取文件夹中的所有文件（不包括子文件夹）
    files = list(fp.glob(f'*{file_ext}'))
    if not files:
        raise FileNotFoundError('错误：文件夹内无扩展名为 {file_ext} 的文件')
    # 按文件名排序
    files.sort()
    print(f"在文件夹中找到了 {len(files)} 个扩展名为 {file_ext} 的文件")

    # 检查文件数量是否匹配
    if len(files) != len(new_names):
        print(f"警告：文件数量 ({len(files)}) 与txt中的名称数量 ({len(new_names)}) 不匹配")
        response = input("是否继续？(y/n): ")
        if response.lower() != 'y':
            return

    # 预览重命名操作
    print("\n预览重命名操作：")
    for i in range(min(len(files), len(new_names))):
        old_name = files[i].stem
        new_name = f'{i:02}_{new_names[i]}'
        print(f"{old_name} -> {new_name}")

    # 确认执行
    response = input("\n是否执行重命名？(y/n): ")
    if response.lower() != 'y':
        print("操作已取消")
        return

    # 执行重命名
    success_count = 0
    error_count = 0

    for i in range(min(len(files), len(new_names))):
        old_path = files[i]
        old_name = old_path.stem

        # 创建新文件名
        # file_ext = os.path.splitext(old_name)[1]
        new_name = f'{i:02}' + '_' + new_names[i] + file_ext
        
        # new_path = os.path.join(folder, new_name)
        new_path = fp.joinpath(new_name)

        # 检查新文件名是否已存在
        if new_path.exists() and old_name != new_name:
            print(f"错误：目标文件 '{new_name}' 已存在")
            error_count += 1
            continue

        try:
            old_path.rename(new_path)
            # os.rename(old_path, new_path)
            print(f"成功：{old_name} -> {new_name}")
            success_count += 1
        except Exception as e:
            print(f"重命名 {old_name} 时出错：{e}")
            error_count += 1

    print(f"\n重命名完成：成功 {success_count} 个，失败 {error_count} 个")


def main():
    """
    主函数 - 获取用户输入并执行重命名
    """
    print("=== 文件批量重命名工具 ===")
    print("根据txt文件内容重命名文件夹内的文件\n")

    # 获取文件夹路径
    folder = input("请输入待重命名文件所在的文件夹路径: ").strip()
    # 移除可能存在的引号
    folder = folder.strip('"').strip("'")

    # 获取文件夹内文件扩展名
    file_ext = input("输入文件夹内待重命名文件的扩展名: ").strip()
    # 移除可能存在的引号
    file_ext = file_ext.strip('"').strip("'")

    # 获取txt文件路径
    names_text = input("请输入包含新文件名的txt文件路径: ").strip()
    names_text = names_text.strip('"').strip("'")

    # 执行重命名
    rename_files_from_txt(folder, file_ext, names_text)


# 简化版本 - 直接指定路径（适合在代码中直接使用）
def simple_rename():
    """
    简化版本，直接在代码中指定路径
    """
    folder = r"D:\项目\audio_split\outputs"  # 修改为您的文件夹路径
    file_ext = r".wav"
    names_text = r"D:\项目\audio_split\queries.txt"  # 修改为您的txt文件路径

    rename_files_from_txt(folder, file_ext, names_text)


if __name__ == "__main__":
    # 使用交互式版本
    main()

    # 或者使用简化版本（取消下面的注释）
    # simple_rename()
