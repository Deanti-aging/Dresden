"""
将转换后的NIfTI文件组织为符合BIDS标准的目录结构

BIDS格式:
    dataset/
    ├── sub-{subject_id}/
    │   ├── ses-{session_number}_{session_date}/
    │   │   └── anat/
    │   │       ├── sub-{subject_id}_ses-{session_number}_{session_date}_T1w.nii.gz
    │   │       ├── sub-{subject_id}_ses-{session_number}_{session_date}_T1w.json
    │   │       ├── sub-{subject_id}_ses-{session_number}_{session_date}_FLAIR.nii.gz
    │   │       └── sub-{subject_id}_ses-{session_number}_{session_date}_FLAIR.json
    
    其中 session_number 是从 01 开始的两位数字编号，按每个受试者的session日期排序自动分配

使用方法:
    python organize_to_bids.py --input_dir ./nifti_output --output_dir ./bids_dataset
"""

import os
import re
import shutil
import argparse
import json
from pathlib import Path
from tqdm import tqdm
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('organize_to_bids.log'),
        logging.StreamHandler()
    ]
)


def detect_modality_from_filename(filename):
    """
    从文件名中检测模态类型
    
    Args:
        filename: 文件名或路径
        
    Returns:
        modality: 'T1w' 或 'FLAIR' 或 None
    """
    filename_upper = filename.upper()
    
    # 检测FLAIR
    if 'FLAIR' in filename_upper:
        return 'FLAIR'
    
    # 检测T1
    if 'T1' in filename_upper or '3DT1' in filename_upper:
        return 'T1w'
    
    return None


def detect_modality_from_json(json_path):
    """
    从 dcm2niix 生成的 JSON sidecar 文件中智能推断 MRI 扫描模态类型
    
     目标：自动识别是 T1 加权（T1w）还是 FLAIR（Fluid-Attenuated Inversion Recovery）序列
     为什么重要？→ 后续处理流程（如脑提取、配准）需按模态定制参数
    
    Args:
        json_path (str or Path): dcm2niix 生成的 .json sidecar 文件路径
                                 例如: "sub-001/anat/sub-001_T1w.json"
    
    Returns:
        str or None: 
            - 'T1w'  : T1-weighted imaging（T1加权）
            - 'FLAIR': Fluid-Attenuated Inversion Recovery（液体衰减反转恢复）
            - None   : 无法识别（日志已记录警告）
    """
    try:
        #  安全打开 JSON 文件，指定 UTF-8 编码（防中文/特殊字符乱码）
        #    with open(...) 自动关闭文件，避免资源泄漏
        with open(json_path, 'r', encoding='utf-8') as f:
            #  解析 JSON 为 Python 字典（metadata）
            metadata = json.load(f)
        
        #  第一层判断：优先看 SeriesDescription（序列描述，最可靠！）
        #    DICOM 标签 (0008,103E)，通常由技师命名，如 "T1_MPRAGE", "3D FLAIR"
        series_desc = metadata.get('SeriesDescription', '').upper()  # 转大写，统一匹配
        if 'FLAIR' in series_desc:
            #  匹配 "FLAIR", "3D_FLAIR", "FLAIR_SAG" 等 → 明确是 FLAIR
            return 'FLAIR'
        if 'T1' in series_desc:
            #  匹配 "T1", "T1W", "T1_MPRAGE", "T1_SAG" → 推断为 T1 加权
            #     注意：不严格要求 "T1W"，因部分设备只写 "T1"
            return 'T1w'
        
        #  第二层判断：若 SeriesDescription 不明确，查 ImageType（DICOM 标签 0008,0008）
        #    示例值: ["ORIGINAL", "PRIMARY", "M", "ND", "NORM", "T1"]
        #    注意：ImageType 是列表，需转为字符串再搜索
        image_type = metadata.get('ImageType', [])
        if isinstance(image_type, list):
            #  将列表拼成空格分隔字符串（如 "ORIGINAL PRIMARY M ND NORM T1"）
            image_type_str = ' '.join(image_type).upper()
            if 'FLAIR' in image_type_str:
                return 'FLAIR'
            if 'T1' in image_type_str:
                return 'T1w'
        #  极少数情况 ImageType 是字符串（非标准），当前逻辑跳过（可扩展）
        
        #  第三层判断：最后看 ProtocolName（协议名，DICOM 标签 0018,1030）
        #    示例: "T1-3D", "FLAIR-2D", "MPRAGE"
        protocol = metadata.get('ProtocolName', '').upper()
        if 'FLAIR' in protocol:
            return 'FLAIR'
        if 'T1' in protocol:
            return 'T1w'
        
        #  若以上三处均未匹配 → 无法识别（可能是 T2w, DWI, fMRI 等）
        #    注意：函数不报错，而是静默返回 None（调用方决定如何处理）
        
    except FileNotFoundError:
        #  文件不存在 → 常见于 dcm2niix 未生成 JSON（如 -b n）
        logging.warning(f" JSON 文件不存在: {json_path}")
    except json.JSONDecodeError as e:
        #  JSON 格式损坏（如写入中断）
        logging.warning(f" JSON 解析失败 ({json_path}): {e}")
    except Exception as e:
        #  其他意外（权限问题、磁盘错误等）
        logging.warning(f" 无法读取 JSON 文件 {json_path}: {type(e).__name__}: {e}")
    
    #  最终兜底：所有路径都未识别出 T1w/FLAIR → 返回 None
    #    调用方应检查此返回值，避免后续流程误用模态
    return None


def extract_subject_id_from_path(path):
    """
    从路径中提取受试者ID
    
    路径格式: .../mri_data/{subject_id}/{date}/raw/...
    例如: 396_500000017
    """
    parts = Path(path).parts
    for part in parts:
        if re.match(r'\d+_\d+', part):  # 匹配类似 396_500000017 的格式
            return part
    return None


def build_session_mapping(input_path):
    """
    扫描输入目录，为每个受试者的session建立编号映射
    
    Args:
        input_path: 输入根目录路径
        
    Returns:
        dict: {(subject_id, session_date): session_label} 映射
              例如: {("396_500000017", "20180212"): "01_20180212", ...}
    """
    session_mapping = {}
    
    # 扫描所有受试者目录
    input_path_obj = Path(input_path)
    
    # 找到所有符合 subject_id 格式的目录
    subject_dirs = []
    for item in input_path_obj.iterdir():
        if item.is_dir() and re.match(r'\d+_\d+', item.name):
            subject_dirs.append(item)
    
    logging.info(f"找到 {len(subject_dirs)} 个受试者目录")
    
    # 对每个受试者，收集所有session日期并排序
    for subject_dir in subject_dirs:
        subject_id = subject_dir.name
        
        # 收集该受试者的所有session日期
        session_dates = []
        for item in subject_dir.iterdir():
            if item.is_dir() and re.match(r'^\d{8}$', item.name):
                session_dates.append(item.name)
        
        # 按日期排序（确保session编号按时间顺序）
        session_dates.sort()
        
        # 为每个session分配编号（从01开始）
        for idx, session_date in enumerate(session_dates, start=1):
            session_label = f"{idx:02d}_{session_date}"  # 格式：01_20180212
            session_mapping[(subject_id, session_date)] = session_label
            logging.debug(f"  受试者 {subject_id}, session {session_date} → {session_label}")
    
    logging.info(f"建立了 {len(session_mapping)} 个session映射")
    return session_mapping


def format_bids_filename(subject_id, session_label, modality):
    """
    生成BIDS格式的文件名
    
    Args:
        subject_id: 受试者ID (例如: 500000017，已经处理过的BIDS格式ID)
        session_label: 会话标签 (例如: 01_20180212)
        modality: 模态类型 ('T1w' 或 'FLAIR')
    
    Returns:
        BIDS格式的文件名 (例如: sub-500000017_ses-01_20180212_T1w)
    """
    bids_subject = f"sub-{subject_id}"
    bids_session = f"ses-{session_label}"
    
    return f"{bids_subject}_{bids_session}_{modality}"


def organize_to_bids(input_root, output_root):
    """
    将NIfTI文件组织为BIDS格式
    
    Args:
        input_root: 输入根目录 (包含转换后的NIfTI文件)
        output_root: 输出根目录 (BIDS格式数据集)
    """
    input_path = Path(input_root)
    output_path = Path(output_root)
    
    # 检查输入目录是否存在
    if not input_path.exists():
        logging.error(f"输入目录不存在: {input_path}")
        return
    
    # 创建BIDS根目录
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 创建dataset_description.json (BIDS要求)
    dataset_description = {
        # === BIDS 标准字段（按规范保留，空值处理）===
        "Name": "Dresden Dataset",
        "BIDSVersion": "1.9.0",
        "DatasetType": "raw",
        "License": "",                 # 空字符串
        "Authors": [],                 # 空列表（BIDS 要求 array）
        "Acknowledgements": "",
        "HowToAcknowledge": "",
        "Funding": [],                 # 空列表（BIDS 要求 array）
        "EthicsApprovals": [],         # 空列表（BIDS 要求 array）
        "ReferencesAndLinks": [],      # 空列表（BIDS 要求 array）
        "DatasetDOI": "",
        "GeneratedBy": [],             # 空列表（BIDS 要求 array）

        # === 你要求的扩展字段（非标准 BIDS，但可添加）===
        "PI": "",                      # 格式建议："Name <email@example.com>"，留空
        "ContactPerson": "",           # 同上，留空
        "OtherInvestigators": "",      # 字符串，逗号分隔，留空
        "OneLiner": "",                # 一行描述，留空
        "BIDSCreators": ["Xinguang Wang"],  #  唯一非空扩展字段
        "CodeLink": "",                # AIMS-VUB GitHub 链接，留空
        "TimeFrame": "",               # 如 "2020-01 to 2023-12"，留空
        "MainCentre": "",              # 主要中心，留空
        "OtherCentres": "",            # 其他中心，留空
        "TrialRegistry": "",           # 试验注册号，留空
        "ProtocolPaper": "",           # 研究设计论文 DOI/URL，留空
        "RawDataPath": "",             # 原始数据路径，留空
        "DataSharing": ""              # 共享机构，逗号分隔，留空
    }
    
    dataset_desc_path = output_path / "dataset_description.json"
    #  以「写入模式」打开文件（若文件已存在则覆盖；不存在则创建）
    #   encoding='utf-8' → 确保中文/特殊字符不乱码（BIDS 允许 Name/Authors 含 Unicode）
    #   with open(...) as f → 自动管理文件资源（写完自动关闭，防泄漏）
    with open(dataset_desc_path, 'w', encoding='utf-8') as f:
            #  将 Python 字典 dataset_description 序列化为 JSON 格式并写入文件
        #    参数详解：
        #      - dataset_description: 一个 dict，包含 BIDS 要求的字段（见下方示例）
        #      - f: 文件句柄（目标文件）
        #      - indent=2: 生成「美化格式」JSON（2空格缩进），方便人工阅读/检查
        #        （对比：indent=None → 单行紧凑格式，机器友好但难读）
        json.dump(dataset_description, f, indent=2)
    
    logging.info(f"创建dataset_description.json: {dataset_desc_path}")
    
    # 创建CHANGES文件 (BIDS版本控制文件)
    # 格式说明：每个条目由版本号、日期和Git提交号（前7个字符）组成
    # 版本格式：vX.Y，更改内容前有两个空格和一个连字符
    # 示例格式：
    # v1.0 YYYY-MM-DD xxxxxxx
    # - Initial release.
    changes_path = output_path / "CHANGES"
    # 仅在文件不存在时创建（避免覆盖已有的版本历史）
    if not changes_path.exists():
        with open(changes_path, 'w', encoding='utf-8') as f:
            # 创建空文件（只保留架构模板，用户可自行添加版本条目）
            # BIDS CHANGES文件是纯文本格式，无实际内容，用户根据需要添加版本条目
            pass
        logging.info(f"创建CHANGES文件（空模板）: {changes_path}")
    else:
        logging.info(f"CHANGES文件已存在，跳过创建: {changes_path}")

    # 创建 issues.tsv 文件（BIDS 问题追踪文件）
    # 字段说明：
    # - type: "general" 或 "specific"
    # - participant_id: "sub-<label>" 或空（留空表示不适用）
    # - session: "ses-<label>" 或空（留空表示不适用）
    # - issue: 具体问题描述
    issues_path = output_path / "issues.tsv"
    if not issues_path.exists():
        with open(issues_path, 'w', encoding='utf-8', newline='') as f:
            # 写入表头（制表符分隔）
            f.write("type\tparticipant_id\tsession\tissue\n")
            # 可选：添加一个示例行（注释掉的），帮助用户理解格式
            # f.write("general\t\t\tInitial dataset import — needs curation.\n")
        logging.info(f"创建 issues.tsv 文件（空模板，含表头）: {issues_path}")
    else:
        logging.info(f"issues.tsv 文件已存在，跳过创建: {issues_path}")

    #  建立session编号映射（在处理文件之前）
    logging.info("正在扫描目录结构以建立session映射...")
    session_mapping = build_session_mapping(input_path)
    
    #  批量扫描所有 .nii.gz 文件（递归搜索 input_path 下所有子目录）
    #    rglob('*.nii.gz') = recursive glob，确保不漏掉任何 NIfTI 文件
    nifti_files = list(input_path.rglob('*.nii.gz'))
    logging.info(f" 共找到 {len(nifti_files)} 个 NIfTI 文件（含 .nii.gz）")

    processed_count = 0  # 成功处理并复制到 BIDS 目录的文件数
    skipped_count = 0    # 因信息缺失/错误跳过的文件数
    
    #  使用 tqdm 显示进度条（友好反馈长时间任务）
    for nifti_file in tqdm(nifti_files, desc=" 组织 BIDS 结构"):
        try:
            #  计算文件相对于 input_path 的路径（用于解析原始目录层级）
            #    例：input_path = "./nifti_output"
            #         nifti_file = "./nifti_output/396_500000017/20180212/raw/T1_MPRAGE_0003.nii.gz"
            #    → relative_path = "396_500000017/20180212/raw/T1_MPRAGE_0003.nii.gz"
            relative_path = nifti_file.relative_to(input_path)
            parts = relative_path.parts  # 拆分为元组：('396_500000017', '20180212', 'raw', 'T1_MPRAGE_0003.nii.gz')
            
            #  解析关键元数据：受试者ID + 会话日期
            #    Dresden 原始结构典型模式：
            #       {subject_id}/{date}/raw/*.nii.gz
            #       其中 subject_id = "396_500000017"（病人ID_扫描协议ID）
            #            date = "20180212"（YYYYMMDD 格式）
            subject_id = None
            session_date = None
            
            #  遍历路径各段，查找符合 "数字_数字" 格式的 subject_id（如 "396_500000017"）
            for i, part in enumerate(parts):
                if re.match(r'\d+_\d+', part):  # 正则：至少1位数字 + '_' + 至少1位数字
                    subject_id = part
                    # 猜测下一段是否为8位数字日期（YYYYMMDD）
                    if i + 1 < len(parts):
                        potential_date = parts[i + 1]
                        if re.match(r'^\d{8}$', potential_date):  # 严格匹配8位数字
                            session_date = potential_date
                        else:
                            # 容错：若下一段不是日期，再试隔一段（防中间有 'raw' 等目录）
                            if i + 2 < len(parts) and re.match(r'^\d{8}$', parts[i + 2]):
                                session_date = parts[i + 2]
                    break  # 找到第一个匹配即停止（通常只有一个 subject_id）
            
            #  若未提取到必要信息 → 记录警告并跳过该文件
            if not subject_id or not session_date:
                logging.warning(f" 无法解析路径元数据: {relative_path}")
                logging.debug(f"  路径分段: {parts}")  # DEBUG 级别，避免 INFO 日志过载
                skipped_count += 1
                continue
            
            #  模态识别：双重保险策略（JSON > 文件名）
            json_file = nifti_file.with_suffix('.json')  # 同名 .json 文件路径
            modality = None
            
            # 1 优先从 dcm2niix 生成的 JSON sidecar 中识别（最可靠！）
            if json_file.exists():
                modality = detect_modality_from_json(json_file)
            
            # 2️ 若 JSON 缺失/未识别 → 回退到文件名分析（你定义的备用函数）
            if not modality:
                modality = detect_modality_from_filename(nifti_file.name)
            
            #  模态仍未知 → 跳过（避免生成非法 BIDS 文件）
            if not modality:
                logging.warning(f" 无法确定模态类型: {nifti_file.name}")
                skipped_count += 1
                continue
            
            #  从session映射中获取session标签（格式：01_20180212）
            session_key = (subject_id, session_date)
            if session_key not in session_mapping:
                logging.warning(f" 未找到session映射: {subject_id}/{session_date}")
                skipped_count += 1
                continue
            
            session_label = session_mapping[session_key]  # 例如: "01_20180212"
            
            #  构建 BIDS 合规目录结构
            #    BIDS 要求：sub-<ID>/ses-<ID>/anat/
            #    注意：subject_id 中的 '396_' 必须转为 ''（防 BIDS 解析错误）
            bids_subject_id = subject_id.replace('396_', '')  # "396_500000017" → "500000017"
            bids_subject = f"sub-{bids_subject_id}"
            bids_session = f"ses-{session_label}"  # 例如: "ses-01_20180212"
            
            # 创建目录链：output_path/sub-500000017/ses-01_20180212/anat/
            bids_anat_dir = output_path / bids_subject / bids_session / "anat"
            bids_anat_dir.mkdir(parents=True, exist_ok=True)  # exist_ok=True：目录存在不报错
            
            #  生成标准 BIDS 文件名（调用你定义的格式化函数）
            #    例：format_bids_filename("500000017", "01_20180212", "T1w")
            #        → "sub-500000017_ses-01_20180212_T1w"
            bids_basename = format_bids_filename(bids_subject_id, session_label, modality)
            bids_nifti_path = bids_anat_dir / f"{bids_basename}.nii.gz"
            bids_json_path = bids_anat_dir / f"{bids_basename}.json"
            
            #  复制 NIfTI 文件（保留元数据：shutil.copy2 拷贝 mtime/atime）
            if not bids_nifti_path.exists():
                shutil.copy2(nifti_file, bids_nifti_path)
                logging.debug(f" 复制 NIfTI → {bids_nifti_path.name}")
            else:
                logging.warning(f" 目标已存在，跳过: {bids_nifti_path.name}")
            
            #  复制配套 JSON sidecar（如存在）
            if json_file.exists():
                if not bids_json_path.exists():
                    shutil.copy2(json_file, bids_json_path)
                    logging.debug(f" 复制 JSON → {bids_json_path.name}")
                else:
                    logging.warning(f" 目标 JSON 已存在，跳过: {bids_json_path.name}")
            
            # 计数+1
            processed_count += 1
            
        #  捕获任意异常（防单文件错误导致整个流程中断）
        except Exception as e:
            logging.error(f" 处理失败 {nifti_file}: {type(e).__name__}: {e}")
            skipped_count += 1
    
    logging.info(f"处理完成: 成功 {processed_count}, 跳过 {skipped_count}")
    
    # 创建README (BIDS推荐)
    readme_path = output_path / "README.txt"  # ← 关键修改：加 .txt 扩展名
    if not readme_path.exists():
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write("Dresden Dataset\n")
            f.write("===============\n\n")
            f.write("This dataset has been organized according to the Brain Imaging Data Structure (BIDS) specification.\n\n")
            f.write("For more information about BIDS, visit: https://bids.neuroimaging.io/\n")  # ← 移除了末尾多余空格
        logging.info(f"创建README文件: {readme_path}")


def main():
    parser = argparse.ArgumentParser(
        description='将NIfTI文件组织为符合BIDS标准的目录结构'
    )
    parser.add_argument(
        '--input_dir',
        type=str,
        default='/home/xingwang/Dresden/nifti_data',
        help='输入目录路径 (包含转换后的NIfTI文件)'
    )
    parser.add_argument(
        '--output_dir',
        type=str,
        default='/home/xingwang/Dresden/bids_data',
        help='输出BIDS数据集目录路径'
    )
    
    args = parser.parse_args()
    
    logging.info("开始组织BIDS结构...")
    logging.info(f"输入目录: {args.input_dir}")
    logging.info(f"输出目录: {args.output_dir}")
    
    organize_to_bids(args.input_dir, args.output_dir)
    
    logging.info("BIDS组织完成！")


if __name__ == "__main__":
    main()

