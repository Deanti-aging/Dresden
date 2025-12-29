"""
将Dresden数据集的DICOM文件转换为NIfTI格式，保持原始文件夹架构

使用方法:
    python dicom_to_nifti.py --input_dir ./raw/mri_data --output_dir ./nifti_output
"""

import os
import argparse
import subprocess
from pathlib import Path
from tqdm import tqdm
import logging


# 配置全局日志系统（仅首次调用生效）
# 此配置决定了日志的输出级别、格式、以及输出目标（文件 + 控制台）
logging.basicConfig(
    # 设置日志的最低记录级别为 INFO
    # ↓ 只有 INFO、WARNING、ERROR、CRITICAL 级别的日志会被记录，DEBUG 被忽略
    level=logging.INFO,
    
    # 定义每条日志的显示格式：
    # %(asctime)s   → 日志记录时间（如：2025-12-22 15:30:45,123）
    # %(levelname)s → 日志级别名称（如：INFO、WARNING）
    # %(message)s   → 用户实际写入的日志内容
    format='%(asctime)s - %(levelname)s - %(message)s',
    
    # 指定日志的输出“处理器”（handlers）——可同时输出到多个地方
    handlers=[
        # 1️ 将日志写入文件 'dicom_to_nifti.log'（与脚本同目录）
        #    → 方便后续排查问题，保留完整执行记录
        logging.FileHandler('dicom_to_nifti.log'),
        
        # 2️ 将日志同时输出到控制台（终端/stdout）
        #    → 方便实时观察程序运行状态
        #     注意：默认 StreamHandler 使用 sys.stderr；若想用 stdout，可写成：
        #       logging.StreamHandler(sys.stdout)
        logging.StreamHandler()
    ]
)


def check_dcm2niix():
    """检查dcm2niix是否已安装"""
    try:
        # 尝试运行命令：dcm2niix -h （即显示帮助信息）
        result = subprocess.run(
            ['dcm2niix', '-h'],      # 要执行的命令：等价于终端输入 `dcm2niix -h`
            capture_output=True,     # 捕获标准输出（stdout）和标准错误（stderr）
            text=True                # 以字符串（而非 bytes）形式返回输出
        )
        # 如果命令成功执行（返回码为 0），说明 dcm2niix 已安装且可用
        return result.returncode == 0

    except FileNotFoundError:
        # 如果系统找不到 'dcm2niix' 命令（例如未安装或不在 PATH 中），抛出此异常
        return False



def convert_dicom_to_nifti(dicom_dir, output_dir):
    """
    将单个 DICOM 目录转换为 NIfTI 格式（使用 dcm2niix 工具）
    
    Args:
        dicom_dir (str): 包含 DICOM 文件的源目录路径（可含子目录）
        output_dir (str): 用于保存 .nii.gz 和 .json 文件的目标目录路径
    
    Returns:
        tuple: (success: bool, message: str)
            - success: 转换是否成功
            - message: 成功时为 stdout 输出；失败时为错误信息
    """
    #  创建输出目录（若已存在则不报错）
    #    exist_ok=True 表示：目录存在时不抛异常，安全创建
    os.makedirs(output_dir, exist_ok=True)
    
    #  构建 dcm2niix 命令行参数列表
    #    使用列表形式避免 shell 注入风险（比字符串拼接更安全）
    try:
        cmd = [
            'dcm2niix',                 # 调用 dcm2niix 可执行程序
        
            '-o', output_dir,           # 指定输出目录（必须是已存在路径，但 dcm2niix 也能自动创建）
            
            '-z', 'y',                  # 启用 gzip 压缩 → 输出 .nii.gz（节省空间）
                                    #    'n' 表示不压缩（输出 .nii），'y' 是默认值
            
            '-b', 'y',                  # 生成 BIDS 兼容的 JSON 侧车文件（包含元数据，如 TR/TE 等）
                                    #    'o' 表示仅当有 BIDS 字段时才生成；'n' 表示不生成
            
            '-s', 'y',                  # 单文件输出（Single file mode）
                                    #    → 将同一扫描序列的所有 DICOM 切片合并为一个 3D/4D NIfTI 文件
                                    #    'n' 表示每个 DICOM 切片单独输出（基本不用）
            
            '-m', 'y',                  # 合并 2D 切片（Merge 2D slices into 3D）
                                    #    自动检测并组合成体积数据；对动态/功能像尤其重要
            
            '-f', '%d_%s',              # 自定义输出文件名模板：
                                    #    %d → SeriesDescription（序列描述）
                                    #    %s → SeriesNumber（序列编号）
                                    #    示例：'T1_MPRAGE_0003.nii.gz'
                                    #    其他常用占位符：
                                    #      %p: ProtocolName, %i: ImageType, %t: DateTime
            
            dicom_dir                   # 输入目录路径（必须放在最后）
        ]
        
        #  执行命令：
        #    capture_output=True → 捕获 stdout 和 stderr（替代手动 pipe）
        #    text=True           → 以字符串形式返回输出（而非 bytes）
        #    check=True          → 若命令返回非 0 退出码，自动抛出 CalledProcessError 异常
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=True  #  关键！让失败立即抛异常，便于统一处理
        )
        
        #  成功：返回 True + 标准输出（通常含转换详情，如“Convert 120 images”）
        return True, result.stdout

    #  情况1：dcm2niix 执行失败（如 DICOM 损坏、权限问题、参数错误等）
    #           subprocess.run(..., check=True) 会在 returncode ≠ 0 时抛出此异常
    except subprocess.CalledProcessError as e:
        # e.cmd: 命令本身
        # e.returncode: 退出码（dcm2niix: 1=错误，0=成功）
        # e.stdout / e.stderr: 输出内容（注意：即使失败，也可能有有用信息）
        error_msg = (
            f"dcm2niix 转换失败（退出码 {e.returncode}）\n"
            f"命令: {' '.join(e.cmd)}\n"
            f"Stderr: {e.stderr.strip()}\n"
            f"Stdout: {e.stdout.strip()}"
        )
        return False, error_msg

    #  情况2：其他未预期异常（如内存不足、路径非法、dcm2niix 未安装等）
    except Exception as e:
        # 通用兜底异常（如 FileNotFoundError 实际也会被捕获到这里，但建议单独处理更清晰）
        return False, f"未预期错误: {type(e).__name__}: {str(e)}"



def process_dresden_dataset(input_root, output_root):
    """
    批量处理 Dresden 数据集的 DICOM → NIfTI 转换，
    严格保持原始文件夹层级结构（如: subject/date/raw/ → subject/date/raw/）
    
    Args:
        input_root (str or Path): 输入根目录路径（原始 DICOM 数据根目录）
                                  例如: "./raw/mri_data"
        output_root (str or Path): 输出根目录路径（NIfTI 文件保存根目录）
                                   例如: "./nifti_output"
    """
    #  将输入/输出路径统一转为 pathlib.Path 对象（更安全、跨平台、易操作）
    #    Path 运算符 / 重载了，专用于路径拼接 —— 比 os.path.join() 更简洁、Pythonic
    input_path = Path(input_root)
    output_path = Path(output_root)
    
    #  检查输入根目录是否存在 —— 提前拦截明显错误，避免后续无效扫描
    if not input_path.exists():
        logging.error(f"错误: 输入目录不存在: {input_path}")
        return  # 直接退出，不继续执行
    
    #  用于收集所有待转换的 DICOM 目录信息（列表 of dict）
    # 每个元素记录：输入路径、输出路径、受试者ID、扫描日期 → 后续转换+日志用
    dicom_dirs = []
    
    #  开始遍历数据集目录结构（按 Dresden 标准组织）：
    #    mri_data/
    #    ├── sub-001/
    #    │   └── 20230101/
    #    │       └── raw/              ← 我们要找的 DICOM 目录
    #    │           ├── IM-0001-0001.dcm
    #    │           └── ...
    #    └── sub-002/
    #        └── 20230105/
    #            └── raw/
    logging.info(" 正在扫描 DICOM 文件目录（按 subject/date/raw 结构）...")
    # 会立即打印到控制台（终端），同时写入日志文件 dicom_to_nifti.log
    # 因为你之前配置了 logging.basicConfig 同时用了 StreamHandler()（控制台） + FileHandler()（文件）。

    # 遍历根目录下的每个「受试者目录」（如 sub-001, sub-002）
    for subject_dir in input_path.iterdir():
        # input_path.iterdir() 会列出 input_path 这个文件夹「直接包含」的所有文件和子文件夹（不递归！），然后 for 循环一个一个拿出来处理
        
        # 跳过非目录项（如 .DS_Store、README.txt 等文件）
        if not subject_dir.is_dir():
            continue
        
        # 提取受试者ID（即文件夹名，如 "sub-001"）
        subject_id = subject_dir.name
        logging.info(f" 找到受试者: {subject_id}")
        
        # 遍历该受试者下的每个「扫描日期目录」（如 "20230101", "20230105"）
        for date_dir in subject_dir.iterdir():
            if not date_dir.is_dir():
                continue
            
            date_str = date_dir.name  # 如 "20230101"
            
            # Dresden 约定：DICOM 原始数据放在 `date_dir/raw/` 下
            raw_dir = date_dir / 'raw'  # 等价于 os.path.join(date_dir, 'raw')
            
            #  检查 `raw/` 目录是否存在 且 是目录（防缺失）
            if raw_dir.exists() and raw_dir.is_dir():
                #  扫描该 raw 目录下所有 .dcm 文件（不递归子目录）
                #    glob('*.dcm') 只匹配一级目录下的 .dcm（Dresden 通常如此）
                dcm_files = list(raw_dir.glob('*.dcm'))
                
                # 若找到至少一个 DICOM 文件 → 视为有效待转换目录
                if dcm_files:
                    #  计算「相对路径」以保持输出结构一致
                    #    例：输入为 "mri_data/sub-001/20230101/raw"
                    #    相对路径 = "sub-001/20230101/raw"
                    relative_path = raw_dir.relative_to(input_path)
                    
                    #  构建对应输出目录路径：
                    #    output_root + relative_path
                    #    例：output_root = "nifti/"
                    #        → 输出目录为 "nifti/sub-001/20230101/raw"
                    output_dir = output_path / relative_path
                    
                    #  记录该任务信息（供后续批量转换）
                    dicom_dirs.append({
                        'input': raw_dir,      # Path 对象，输入 DICOM 目录
                        'output': output_dir,  # Path 对象，输出 NIfTI 目录
                        'subject': subject_id, # 字符串，如 "sub-001"
                        'date': date_str       # 字符串，如 "20230101"
                    })
    
    #  扫描完成，汇报发现的待处理任务数
    logging.info(f" 共找到 {len(dicom_dirs)} 个含 DICOM 文件的有效目录，准备转换...")
    
    #  初始化统计计数器
    success_count = 0
    fail_count = 0
    
    #  使用 tqdm 显示进度条（美观 + 直观感知进度）
    #    desc="..." 是进度条前缀文字
    for item in tqdm(dicom_dirs, desc=" 转换 DICOM → NIfTI"):
        #  日志记录当前任务（INFO 级别 → 控制台/文件都能看到）
        logging.info(f"⚙️ 正在转换: {item['subject']}/{item['date']}")
        
        #  调用之前定义的转换函数（返回 success:bool, message:str）
        #    注意：convert_dicom_to_nifti 期望 str 路径，所以用 str() 转换 Path
        success, message = convert_dicom_to_nifti(
            str(item['input']),   # 输入目录路径（字符串）
            str(item['output'])   # 输出目录路径（字符串）
        )
        
        #  成功：计数 + 调试级日志（DEBUG 可被 INFO 级别过滤，按需调整）
        if success:
            success_count += 1
            # 使用 logging.debug（默认不会输出，除非 level=DEBUG）
            # 若想在控制台看到，可改为 logging.info 或调整 basicConfig level
            logging.debug(f" 成功: {item['subject']}/{item['date']}")
        #  失败：计数 + 错误级日志（一定会记录！）
        else:
            fail_count += 1
            #  ERROR 级别 → 醒目标红（部分终端）+ 必定写入日志文件（便于事后排查）
            logging.error(f" 失败: {item['subject']}/{item['date']} → 原因: {message}")
    
    #  最终汇总报告（关键！让使用者一目了然结果）
    summary = f"转换完成！成功: {success_count} 例 | 失败: {fail_count} 例"
    if fail_count > 0:
        summary += "（失败详情见日志文件 dicom_to_nifti.log）"
    logging.info(summary)




def main():
    """
    主函数：解析命令行参数 → 检查依赖 → 执行批量转换
    入口点（通常配合 `if __name__ == '__main__': main()` 使用）
    """
    
    #  创建命令行参数解析器（argparse 是 Python 标准库，用于构建 CLI 工具）
    #    description 将在用户运行 `python script.py -h` 时显示
    parser = argparse.ArgumentParser(
        description='将Dresden数据集的DICOM文件转换为NIfTI格式，保持文件夹架构'
    )
    
    #  添加第一个参数：--input_dir
    #    - type=str：参数值必须是字符串
    #    - default=...：若用户未指定，则用此默认路径
    #    - help=...：在帮助信息中显示说明（运行 -h 时可见）
    parser.add_argument(
        '--input_dir',
        type=str,
        default='/home/xingwang/Dresden/raw/mri_data',  #  Dresden 数据集标准路径
        help='输入目录路径 (包含 mri_data 文件夹，结构为 mri_data/{subject}/{date}/raw/)'
    )
    
    #  添加第二个参数：--output_dir
    parser.add_argument(
        '--output_dir',
        type=str,
        default='/home/xingwang/Dresden/nifti_data',  # ✅ 默认输出到同级 nifti_output/
        help='输出目录路径（将自动创建，结构与输入一致）'
    )
    
    #  解析用户传入的命令行参数（如：python convert.py --input_dir ./data）
    #    返回 Namespace 对象，通过 args.xxx 访问参数值
    args = parser.parse_args()
    
    #  【关键前置检查】确认核心依赖 dcm2niix 是否可用
    #    → 调用你之前定义的 check_dcm2niix() 函数（运行 `dcm2niix -h` 测试）
    if not check_dcm2niix():
        #  若未安装：记录多条 ERROR 日志（按你的 logging 配置，会同时输出到终端+日志文件）
        logging.error(" 错误: 未找到 dcm2niix 工具")
        logging.error(" 请安装 dcm2niix: https://github.com/rordenlab/dcm2niix  ")
        #  根据知识库信息，补充 Windows 用户友好安装方式（choco = Chocolatey 包管理器）
        logging.error(" Windows 用户推荐: choco install dcm2niix")
        #  直接退出主流程，避免后续无效操作
        return
    
    #  依赖检查通过，开始正式工作
    logging.info(" 开始转换 DICOM 到 NIfTI...")
    logging.info(f" 输入目录: {args.input_dir}")
    logging.info(f" 输出目录: {args.output_dir}")
    
    #  调用核心批量处理函数（你定义的 process_dresden_dataset）
    #    它会：
    #      1. 扫描 input_dir 下所有 subject/date/raw/ 目录
    #      2. 对每个含 DICOM 的目录调用 convert_dicom_to_nifti()
    #      3. 保持输出目录结构一致 + 统计成功/失败数量
    process_dresden_dataset(args.input_dir, args.output_dir)
    
    #  全部任务结束（注意：即使中间有失败，process_dresden_dataset 也会继续执行其余任务）
    logging.info(" 所有转换任务完成！")
    #  注：这里重复了一次 logging.info("所有转换任务完成！")
    #    → 建议删除其中一行，避免日志冗余（可能是笔误）

if __name__ == "__main__":
    main()

