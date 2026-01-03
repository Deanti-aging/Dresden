#!/usr/bin/env python3
"""
Automated generation of participants.tsv from BIDS dataset and clinical data.
"""

import os
import re
import pandas as pd
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 配置日志记录：设置日志级别、格式和输出目标
logging.basicConfig(
    level=logging.INFO,  # 设置日志级别为 INFO，会记录 INFO 及以上级别的日志（如 WARNING、ERROR）
    format='%(asctime)s - %(levelname)s - %(message)s',  # 日志格式：时间 - 日志级别 - 消息内容
    handlers=[
        logging.FileHandler('participants_generation.log', encoding='utf-8'),  # 将日志写入文件，使用 UTF-8 编码支持中文等字符
        logging.StreamHandler()  # 同时将日志输出到控制台（标准输出）
    ]
)
logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器，便于后续在代码中记录日志

# 定义路径常量
BIDS_DATA_DIR = Path("/home/xingwang/Dresden_dataset/bids_data")      # BIDS 格式数据的根目录
CLINICAL_DATA_DIR = Path("/home/xingwang/Dresden_dataset/raw/clinical_data")  # 原始临床数据所在目录
OUTPUT_FILE = BIDS_DATA_DIR / "participants.tsv"  # 最终生成的 participants.tsv 文件路径（BIDS 规范要求）

# 定义需要读取的 Excel 文件名映射字典
# 键（key）表示数据类型或变量名，值（value）是对应的 Excel 文件名
EXCEL_FILES = {
    'sDOB': 'sDOB_Gender_Year diagnosis.xlsx',     # 包含出生日期(sDOB)、性别、诊断年份等信息
    'sdmt': 'PST_SDMT.xlsx',                       # Symbol Digit Modalities Test (SDMT) 认知测试结果
    '9hpt': '9HPT.xlsx',                           # 9-Hole Peg Test (9HPT) 手部功能测试结果
    'edss': 'EDSS.xlsx',                           # Expanded Disability Status Scale (EDSS) 神经功能障碍评分
    't25fw': 'T25FW.xlsx',                         # Timed 25-Foot Walk (T25FW) 步行能力测试
    'education': 'Education_MSType.xlsx'           # 教育程度和多发性硬化类型（MS Type）信息
}


def extract_date_from_timestamp(timestamp_str: str) -> Optional[str]:
    """
    从 Unix 时间戳中提取日期，返回格式为 YYYYMMDD 的字符串。

    参数:
        timestamp_str (str): Unix 时间戳（单位：秒），通常以字符串形式传入

    返回:
        str | None:
            - 成功时返回 'YYYYMMDD'
            - 输入非法或转换失败时返回 None
    """
    try:
        # 将时间戳字符串转换为整数
        # 如果 timestamp_str 不是纯数字，会抛出 ValueError
        timestamp = int(timestamp_str)

        # 将 Unix 时间戳转换为 datetime 对象（本地时间）
        dt = datetime.fromtimestamp(timestamp)

        # 将 datetime 格式化为 YYYYMMDD 字符串
        return dt.strftime('%Y%m%d')

    except (ValueError, TypeError):
        # 捕获：
        # - ValueError：无法将字符串转换为整数
        # - TypeError：timestamp_str 为 None 或类型不正确
        return None


def extract_date_from_datetime(datetime_str: str) -> Optional[str]:
    """
    从 datetime 字符串中提取日期，返回格式为 YYYYMMDD。

    支持的输入格式包括：
    1) 'Tue, 15 Aug 2017 09:11:07 +0000'
    2) 'YYYY-MM-DD'

    参数:
        datetime_str (str): datetime 字符串

    返回:
        str | None:
            - 成功时返回 'YYYYMMDD'
            - 解析失败或输入非法时返回 None
    """
    try:
        # 第一种尝试：
        # 处理格式如 'Tue, 15 Aug 2017 09:11:07 +0000'
        # 由于格式串不包含时区信息 (+0000)，
        # 先通过 split(' +') 去掉时区部分
        dt = datetime.strptime(
            datetime_str.split(' +')[0],
            '%a, %d %b %Y %H:%M:%S'
        )

        # 将 datetime 转换为 YYYYMMDD 格式
        return dt.strftime('%Y%m%d')

    except (ValueError, AttributeError):
        try:
            # 第二种尝试：
            # 处理简单日期格式 'YYYY-MM-DD'
            dt = datetime.strptime(datetime_str, '%Y-%m-%d')

            # 转换为 YYYYMMDD
            return dt.strftime('%Y%m%d')

        except (ValueError, AttributeError):
            # 所有解析方式都失败，返回 None
            return None


def extract_date_from_visitdate(visitdate_str: str) -> Optional[str]:
    """
    从访问日期字符串中提取日期，并统一格式为 yyyymmdd。
    输入示例: '14/10/2021'
    输出示例: '20211014'
    """
    try:
        # 按照 日/月/年 (dd/mm/yyyy) 的格式解析字符串为 datetime 对象
        dt = datetime.strptime(visitdate_str, '%d/%m/%Y')

        # 将 datetime 对象格式化为 yyyymmdd 字符串
        return dt.strftime('%Y%m%d')

    except (ValueError, AttributeError):
        # 如果格式不匹配或输入不是字符串，则返回 None
        return None



def calculate_age(dob_str: str, session_date: str) -> Optional[float]:
    """
    根据出生日期和 session 日期计算年龄（单位：年）。
    
    参数：
    - dob_str: 出生日期字符串，格式 dd.mm.yyyy（如 '15.08.1995'）
    - session_date: session 日期字符串，格式 yyyymmdd（如 '20211014'）
    
    返回：
    - 年龄（float，单位：年），或 None（解析失败时）
    """
    try:
        # 解析出生日期（格式：日.月.年）
        dob = datetime.strptime(dob_str, '%d.%m.%Y')

        # 解析 session 日期（格式：年月日）
        session_dt = datetime.strptime(session_date, '%Y%m%d')

        # 计算出生日期到 session 日期之间的天数差
        days_diff = (session_dt - dob).days

        # 将天数转换为年龄（年）
        # 使用 365.2425 天/年（回归年），更符合科研计算标准
        age = days_diff / 365.2425

        return age

    except (ValueError, AttributeError):
        # 如果日期格式不正确或输入为空，则返回 None
        return None



def get_participants_and_sessions(bids_dir: Path) -> Dict[str, List[str]]:
    """
    从 BIDS 目录结构中提取所有 participant（sub-xxx）及其 session 日期。
    
    返回格式：
    {
        "sub-001": ["20211014", "20221020"],
        ...
    }
    """
    participants = {}

    # 检查 BIDS 根目录是否存在
    if not bids_dir.exists():
        logger.error(f"BIDS data directory does not exist: {bids_dir}")
        return participants

    # 匹配 sub-<subject_id> 目录（只允许数字 ID）
    sub_pattern = re.compile(r'^sub-(\d+)$')

    # 匹配 ses-<序号>_<日期> 目录，如 ses-01_20211014
    ses_pattern = re.compile(r'^ses-(\d+)_(\d{8})$')

    # 遍历 BIDS 根目录下的所有条目
    for item in bids_dir.iterdir():
        # 只处理目录
        if not item.is_dir():
            continue

        # 判断是否为合法的 participant 目录
        match = sub_pattern.match(item.name)
        if match:
            participant_id = item.name  # 保留 sub-xxx 形式
            sessions = []

            # 遍历该 participant 下的 session 目录
            for ses_item in item.iterdir():
                if ses_item.is_dir():
                    ses_match = ses_pattern.match(ses_item.name)
                    if ses_match:
                        # 提取 session 日期（yyyymmdd）
                        session_date = ses_match.group(2)
                        sessions.append(session_date)

            # 若该 participant 有 session，则加入结果
            if sessions:
                participants[participant_id] = sorted(sessions)

    logger.info(f"Found {len(participants)} participants")
    return participants



def load_excel_file(file_path: Path) -> Optional[pd.DataFrame]:
    """
    从指定路径加载 Excel 文件，并返回对应的 pandas DataFrame。
    
    参数:
        file_path (Path): 要加载的 Excel 文件的路径（应为 pathlib.Path 对象）。
    
    返回:
        pd.DataFrame 或 None: 
            - 如果文件存在且成功读取，返回包含数据的 DataFrame；
            - 如果文件不存在或读取过程中出错，返回 None。
    """
    # 检查文件是否存在
    if not file_path.exists():
        # 如果文件不存在，记录一条警告日志，并返回 None
        logger.warning(f"Excel file not found: {file_path}")
        return None
    
    try:
        # 使用 pandas 读取 Excel 文件（支持 .xls 和 .xlsx）
        df = pd.read_excel(file_path)
        
        # 记录成功加载的日志，包括文件名和行数，便于调试和监控
        logger.info(f"Loaded {file_path.name}: {len(df)} rows")
        
        # 返回读取到的数据框
        return df
    
    except Exception as e:
        # 捕获所有可能的异常（如文件损坏、格式错误、缺少依赖库等）
        # 记录错误日志，包含具体的异常信息，便于排查问题
        logger.error(f"Error loading {file_path}: {e}")
        
        # 出错时返回 None，避免程序崩溃
        return None


def get_participant_id_from_dresden_id(dresden_id: str) -> str:
    """
    将德累斯顿 ID（Dresden ID）转换为符合 BIDS 规范的参与者 ID 格式（即 'sub-{id}' 形式）。
    
    BIDS（Brain Imaging Data Structure）是一种神经影像数据组织标准，
    要求所有受试者 ID 必须以 'sub-' 开头，例如：sub-01、sub-123 等。
    
    该函数确保输入的 ID 最终符合这一格式。
    
    参数:
        dresden_id (str): 原始的德累斯顿 ID，可能已带 'sub-' 前缀，也可能没有，
                          甚至可能包含前后空格。
    
    返回:
        str: 标准化的 BIDS 参与者 ID，格式为 'sub-{原始ID}'。
    """
    # 将输入强制转为字符串（防止传入 int、float 等非字符串类型）
    # 并去除首尾的空白字符（如空格、换行符等），避免因格式问题导致错误
    dresden_id = str(dresden_id).strip()
    
    # 检查当前 ID 是否已经以 'sub-' 开头
    # 如果不是，则在前面加上 'sub-' 前缀，使其符合 BIDS 规范
    if not dresden_id.startswith('sub-'):
        return f"sub-{dresden_id}"
    
    # 如果已经是以 'sub-' 开头，则直接返回原字符串（无需修改）
    return dresden_id



def process_participant_id_field(participants: Dict[str, List[str]]) -> pd.DataFrame:
    """
    根据参与者字典的键（keys）生成一个包含 'participant_id' 列的 DataFrame。
    
    该函数假设输入字典的每个 key 就是一个标准化的参与者 ID（如 'sub-01'），
    而对应的 value（List[str]）可能是该参与者的会话、任务或其他相关数据，
    但在此函数中仅使用 key 来构建参与者列表。
    
    参数:
        participants (Dict[str, List[str]]): 
            一个字典，键为参与者 ID（如 'sub-01'），值为与该参与者相关的字符串列表
            （例如：['ses-2023', 'ses-2024'] 或任务名等，此处不使用）。
    
    返回:
        pd.DataFrame: 一个单列 DataFrame，列名为 'participant_id'，
                      每一行对应一个唯一的参与者 ID。
    """
    # 提取字典的所有键（即所有参与者 ID），并转换为列表
    participant_ids = list(participants.keys())
    
    # 记录日志：输出总共有多少名参与者，便于监控和调试
    logger.info(f"Total participants: {len(participant_ids)}")
    
    # 创建一个 pandas DataFrame，只包含一列 'participant_id'
    # 列的值就是上面提取的参与者 ID 列表
    df = pd.DataFrame({'participant_id': participant_ids})
    
    # 返回生成的 DataFrame
    return df


def process_session_field(participants: Dict[str, List[str]], df: pd.DataFrame) -> pd.DataFrame:
    """
    为已有的 DataFrame 添加 'session' 列，该列包含每个参与者对应的所有会话（session）ID，
    多个会话用英文逗号 ',' 连接成一个字符串。
    
    假设：
      - `participants` 是一个字典，键为 participant_id（如 'sub-01'），
        值为该参与者拥有的所有 session ID 列表（如 ['ses-2023', 'ses-2024']）。
      - `df` 是一个已包含 'participant_id' 列的 DataFrame（通常由前一步生成）。
    
    参数:
        participants (Dict[str, List[str]]): 
            参与者到其会话列表的映射字典。
        df (pd.DataFrame): 
            当前 DataFrame，必须包含 'participant_id' 列。
    
    返回:
        pd.DataFrame: 在原 DataFrame 上新增一列 'session'，返回更新后的 DataFrame。
    """
    # 遍历 DataFrame 中每一行的 'participant_id'
    # 对每个 participant_id（记为 pid），从 participants 字典中取出对应的会话列表，
    # 然后用 ','.join(...) 将列表中的多个 session 合并为一个逗号分隔的字符串
    # 例如：['ses-2023', 'ses-2024'] → "ses-2023,ses-2024"
    sessions = [','.join(participants[pid]) for pid in df['participant_id']]
    
    # 将生成的 sessions 列表作为新列 'session' 添加到 DataFrame 中
    df['session'] = sessions
    
    # 返回更新后的 DataFrame
    return df


def process_age_field(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 添加 'age' 列，表示每个参与者在每次会话时的年龄。
    
    年龄通过以下步骤计算：
      1. 从临床数据目录中读取包含出生日期（sDOB）的 Excel 文件；
      2. 根据 participant_id（如 'sub-5000017'）匹配 Excel 中的 'ID Dresden' 列；
      3. 获取该参与者的出生日期；
      4. 对该参与者拥有的每一个 session_date，调用 calculate_age 计算当时年龄；
      5. 多个年龄值用逗号连接（与 session 列一一对应）。
    
    如果无法获取出生日期或计算失败，则对应位置填空字符串 ''。
    
    参数:
        participants (Dict[str, List[str]]): 
            参与者 ID 到其会话日期列表的映射，例如 {'sub-5000017': ['20231005', '20240110']}
        df (pd.DataFrame): 
            当前 DataFrame，必须包含 'participant_id' 列
        clinical_data_dir (Path): 
            临床数据所在目录路径，用于定位 Excel 文件
    
    返回:
        pd.DataFrame: 添加了 'age' 列的更新版 DataFrame
    """
    
    # 构建出生日期 Excel 文件的完整路径
    # EXCEL_FILES['sDOB'] 应该是一个文件名，如 "sDOB_data.xlsx"
    excel_path = clinical_data_dir / EXCEL_FILES['sDOB']
    
    # 安全加载 Excel 文件（若文件不存在或读取出错，load_excel_file 会返回 None）
    excel_df = load_excel_file(excel_path)
    
    # 如果 Excel 文件加载失败（None），则所有 age 字段设为空字符串，并返回
    if excel_df is None:
        df['age'] = ''  # 为所有行添加空 age 列
        return df
    
    # 初始化两个列表：
    # - ages: 存储每个 participant_id 对应的年龄字符串（可能含多个，用逗号分隔）
    # - missing_age_participants: 记录哪些参与者缺失年龄信息，用于日志警告
    ages = []
    missing_age_participants = []
    
    # 遍历 DataFrame 中的每一个 participant_id
    for participant_id in df['participant_id']:
        # 从 BIDS 格式的 ID（如 'sub-5000017'）中提取纯数字部分 '5000017'
        numeric_id = participant_id.replace('sub-', '')
        
        # 在 Excel 数据中查找 'ID Dresden' 列等于 numeric_id 的行
        # 注意：先将该列转为字符串并去除空格，确保匹配鲁棒性
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果找不到匹配的行，说明该参与者在临床数据中无记录
        if matching_rows.empty:
            ages.append('')  # 年龄留空
            missing_age_participants.append(participant_id)
            continue  # 跳过后续处理
        
        # 从匹配的第一行中提取出生日期字段
        # 字段名是：'Study date of Birth (sDOB: 01.01.yyyy)'
        dob_value = matching_rows.iloc[0]['Study date of Birth (sDOB: 01.01.yyyy)']
        
        # 检查出生日期是否为空或 NaN
        if pd.isna(dob_value) or dob_value == '':
            ages.append('')
            missing_age_participants.append(participant_id)
            continue
        
        # 获取该参与者的所有会话日期（来自 participants 字典）
        session_dates = participants[participant_id]
        age_values = []  # 用于存储本次参与者各会话对应的年龄字符串
        
        # 对每个会话日期，计算当时的年龄
        for session_date in session_dates:
            # 调用外部函数 calculate_age（需已实现），传入出生日期和会话日期
            # 假设 session_date 是字符串格式（如 '20231005' 或 '2023-10-05'）
            age = calculate_age(str(dob_value), session_date)
            
            if age is not None:
                # 保留两位小数，转为字符串（如 "25.34"）
                age_values.append(f"{age:.2f}")
            else:
                # 如果计算失败（如日期格式无效），填空字符串
                age_values.append('')
        
        # 将该参与者的所有年龄值用逗号连接，形成一个字符串
        # 例如：['25.34', '26.12'] → "25.34,26.12"
        ages.append(','.join(age_values))
        
        # 如果所有年龄都为空（即 age_values 全是空字符串），则视为缺失
        if all(not v for v in age_values):
            missing_age_participants.append(participant_id)
    
    # 将生成的 ages 列添加到 DataFrame 中
    df['age'] = ages
    
    # 如果有参与者缺失年龄信息，记录警告日志
    if missing_age_participants:
        logger.warning(f"Missing age for participants: {missing_age_participants}")
    
    # 返回更新后的 DataFrame
    return df


def process_sex_field(df: pd.DataFrame, clinical_data_dir: Path) -> pd.DataFrame:
    """
    为 DataFrame 添加 'sex' 列，表示每位参与者的性别信息。
    
    性别数据从临床 Excel 文件（通常与出生日期在同一文件）中读取，
    根据 participant_id 匹配 'ID Dresden' 列，并提取 'Gender' 字段。
    所有性别值会被标准化为小写字符串（如 'male', 'female'）。
    
    参数:
        df (pd.DataFrame): 
            输入 DataFrame，必须包含 'participant_id' 列（格式如 'sub-5000017'）
        clinical_data_dir (Path): 
            临床数据所在目录路径
    
    返回:
        pd.DataFrame: 添加了 'sex' 列的更新版 DataFrame
    """
    
    # 构建临床 Excel 文件的完整路径（此处复用 sDOB 文件，因其通常包含 Gender 列）
    excel_path = clinical_data_dir / EXCEL_FILES['sDOB']
    
    # 安全加载 Excel 文件；若失败（文件缺失/损坏），返回带空 sex 列的 df
    excel_df = load_excel_file(excel_path)
    
    if excel_df is None:
        # 如果无法加载 Excel，所有参与者的 sex 设为空字符串
        df['sex'] = ''
        return df
    
    # 初始化列表：用于存储每个 participant_id 对应的性别值
    sexes = []
    missing_sex_participants = []  # 记录缺失性别的参与者 ID，用于日志
    
    # 遍历 DataFrame 中的每一个 participant_id
    for participant_id in df['participant_id']:
        # 从 BIDS 格式 ID（如 'sub-5000017'）中提取纯数字部分 '5000017'
        numeric_id = participant_id.replace('sub-', '')
        
        # 在 Excel 数据中查找 'ID Dresden' 列匹配 numeric_id 的行
        # 注意：将该列转为字符串并去除首尾空格，提高匹配鲁棒性
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果没有找到匹配行，说明该参与者在临床数据中无记录
        if matching_rows.empty:
            sexes.append('')  # 性别留空
            missing_sex_participants.append(participant_id)
            continue  # 跳过后续处理
        
        # 从匹配的第一行中提取 'Gender' 列的值
        gender_value = matching_rows.iloc[0]['Gender']
        
        # 检查性别值是否为空或 NaN
        if pd.isna(gender_value) or gender_value == '':
            sexes.append('')
            missing_sex_participants.append(participant_id)
        else:
            # 将性别值转为字符串，去除首尾空格，并统一转为小写
            # 例如：'Male' → 'male'，' FEMALE ' → 'female'
            gender_str = str(gender_value).strip().lower()
            sexes.append(gender_str)
    
    # 将生成的性别列表作为新列 'sex' 添加到 DataFrame 中
    df['sex'] = sexes
    
    # 如果存在缺失性别的参与者，记录警告日志以便后续排查
    if missing_sex_participants:
        logger.warning(f"Missing sex for participants: {missing_sex_participants}")
    
    # 返回更新后的 DataFrame
    return df


def process_is_ms_field(df: pd.DataFrame, clinical_data_dir: Path) -> pd.DataFrame:
    """
    为 DataFrame 添加 'is_ms' 列，用于标记参与者是否患有多发性硬化症（Multiple Sclerosis, MS）。
    
    判断逻辑：
      - 如果临床数据中存在 'Date of Diagnosis (year)' 字段且非空，
        则认为该参与者是 MS 患者，标记为 '1'；
      - 否则（字段为空、NaN 或找不到该参与者），标记为空字符串 ''。
    
    注意：此函数假设所有出现在临床数据中且有诊断年份的参与者均为 MS 患者。
    
    参数:
        df (pd.DataFrame): 
            输入 DataFrame，必须包含 'participant_id' 列（格式如 'sub-5000017'）
        clinical_data_dir (Path): 
            临床数据所在目录路径
    
    返回:
        pd.DataFrame: 添加了 'is_ms' 列的更新版 DataFrame
    """
    
    # 构建临床 Excel 文件的完整路径（复用 sDOB 文件，因其通常包含诊断信息）
    excel_path = clinical_data_dir / EXCEL_FILES['sDOB']
    
    # 尝试加载 Excel 文件；若失败（文件不存在/损坏等），返回带空 is_ms 列的 df
    excel_df = load_excel_file(excel_path)
    
    if excel_df is None:
        # 无法获取临床数据，所有参与者的 is_ms 设为空字符串
        df['is_ms'] = ''
        return df
    
    # 初始化两个列表：
    # - is_ms_values: 存储每个 participant_id 对应的 'is_ms' 值（'1' 或 ''）
    # - missing_is_ms_participants: 记录无法确定是否为 MS 的参与者 ID，用于日志警告
    is_ms_values = []
    missing_is_ms_participants = []
    
    # 遍历 DataFrame 中的每一个 participant_id
    for participant_id in df['participant_id']:
        # 从 BIDS 格式 ID（如 'sub-5000017'）中提取纯数字部分 '5000017'
        numeric_id = participant_id.replace('sub-', '')
        
        # 在 Excel 数据中查找 'ID Dresden' 列匹配 numeric_id 的行
        # 注意：先转为字符串并去除首尾空格，提高匹配鲁棒性
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果没有找到匹配行，说明该参与者不在临床数据中
        if matching_rows.empty:
            is_ms_values.append('')  # 无法判断，留空
            missing_is_ms_participants.append(participant_id)
            continue  # 跳过后续处理
        
        # 从匹配的第一行中提取 'Date of Diagnosis (year)' 字段（诊断年份）
        diagnosis_year = matching_rows.iloc[0]['Date of Diagnosis (year)']
        
        # 检查诊断年份是否为空或 NaN
        if pd.isna(diagnosis_year) or diagnosis_year == '':
            # 无诊断年份 → 无法确认是否为 MS 患者
            is_ms_values.append('')
            missing_is_ms_participants.append(participant_id)
        else:
            # 有诊断年份 → 视为 MS 患者，标记为 '1'
            # 使用字符串 '1' 而非整数 1，便于后续写入 TSV/CSV 并保持字段一致性
            is_ms_values.append('1')
    
    # 将生成的 is_ms 值列表作为新列添加到 DataFrame 中
    df['is_ms'] = is_ms_values
    
    # 如果有参与者缺失 is_ms 信息，记录警告日志以便数据核查
    if missing_is_ms_participants:
        logger.warning(f"Missing is_ms for participants: {missing_is_ms_participants}")
    
    # 返回更新后的 DataFrame
    return df


def process_sdmt_field(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 添加 'sdmt' 列，表示每位参与者在每次会话中完成的 SDMT（Symbol Digit Modalities Test）得分。
    
    SDMT 是一种常用于评估认知功能（尤其是信息处理速度）的神经心理学测试。
    本函数从专门的 SDMT Excel 文件中，根据 participant_id 和 session_date 精确匹配得分。
    
    输出格式：
      - 每个 participant_id 对应一个字符串，包含与其所有 session 一一对应的 SDMT 得分，
        多个得分用英文逗号 ',' 分隔（与 'session' 列顺序严格对齐）。
      - 若某次会话无对应 SDMT 数据，则该位置为空字符串 ''。
    
    参数:
        participants (Dict[str, List[str]]): 
            participant_id 到其会话日期列表的映射，例如 {'sub-5000017': ['20231005', '20240110']}
        df (pd.DataFrame): 
            必须包含 'participant_id' 列的 DataFrame
        clinical_data_dir (Path): 
            临床数据目录路径
    
    返回:
        pd.DataFrame: 添加了 'sdmt' 列的更新版 DataFrame
    """
    
    # 构建 SDMT 专用 Excel 文件的完整路径（通常与 sDOB 文件不同）
    excel_path = clinical_data_dir / EXCEL_FILES['sdmt']
    
    # 尝试加载 SDMT 数据文件；若失败，所有 sdmt 字段设为空，并返回
    excel_df = load_excel_file(excel_path)
    
    if excel_df is None:
        df['sdmt'] = ''
        return df
    
    # 初始化两个列表：
    # - sdmt_values: 存储每个 participant_id 对应的 SDMT 得分字符串（如 "45,50"）
    # - missing_sdmt_sessions: 记录缺失 SDMT 数据的具体 (participant_session) 组合，用于日志
    sdmt_values = []
    missing_sdmt_sessions = []
    
    # 遍历 DataFrame 中的每个 participant_id
    for participant_id in df['participant_id']:
        # 提取纯数字 ID（去除 'sub-' 前缀）
        numeric_id = participant_id.replace('sub-', '')
        
        # 获取该参与者的所有会话日期（来自 participants 字典）
        session_dates = participants[participant_id]
        
        # 在 SDMT Excel 数据中查找所有匹配该 numeric_id 的行
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果该参与者在 SDMT 文件中完全无记录
        if matching_rows.empty:
            # 为该参与者的每一个会话都填空字符串
            sdmt_values.append(','.join([''] * len(session_dates)))
            # 记录所有缺失的会话
            missing_sdmt_sessions.extend([f"{participant_id}_{sd}" for sd in session_dates])
            continue
        
        # 初始化当前参与者的 SDMT 得分列表（按 session_dates 顺序填充）
        session_sdmt = []
        
        # 遍历该参与者的每一个会话日期
        for session_date in session_dates:
            found = False  # 标记是否找到匹配的评估记录
            
            # 在 matching_rows 中逐行查找：是否有评估日期与 session_date 匹配
            for idx, row in matching_rows.iterrows():
                assessment_date_str = row['Assessment Started At']
                
                # 跳过空的评估时间
                if pd.isna(assessment_date_str):
                    continue
                
                # 使用自定义函数从原始时间戳（如 "2023-10-05 14:30:00"）中提取日期部分
                # 假设 extract_date_from_datetime 返回格式如 "20231005"
                assessment_date = extract_date_from_datetime(str(assessment_date_str))
                
                # 如果提取的评估日期与当前会话日期一致，则视为匹配
                if assessment_date == session_date:
                    # 获取 'Total Number Correct' 列的值（即 SDMT 得分）
                    total_correct = row['Total Number Correct']
                    
                    # 处理空值或 NaN
                    if pd.isna(total_correct) or total_correct == '':
                        session_sdmt.append('')
                    else:
                        # 转为字符串存储（便于后续 join）
                        session_sdmt.append(str(total_correct))
                    
                    found = True
                    break  # 找到匹配后跳出内层循环（如果一个 session_date 匹配到多个 Assessment Started At 日期相同的记录，只取第一个）
            
            # 如果遍历完所有匹配行仍未找到对应 session_date 的记录
            if not found:
                session_sdmt.append('')  # 该会话无 SDMT 数据
                missing_sdmt_sessions.append(f"{participant_id}_{session_date}")
        
        # 将该参与者的所有 SDMT 得分用逗号连接成一个字符串
        sdmt_values.append(','.join(session_sdmt))
    
    # 将生成的 sdmt 字符串列表作为新列添加到 DataFrame
    df['sdmt'] = sdmt_values
    
    # 如果存在缺失的 SDMT 会话，记录警告日志（仅显示前 10 条，避免日志过长）
    if missing_sdmt_sessions:
        logger.warning(f"Missing sdmt for sessions: {missing_sdmt_sessions[:10]}...")
    
    # 返回更新后的 DataFrame
    return df


def process_9hpt_fields(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 添加三个字段：
      - '9hpt_dom': 每次会话中优势手（dominant hand）完成 9-Hole Peg Test 的时间（秒）
      - '9hpt_ndom': 非优势手（non-dominant hand）的完成时间
      - 'handedness': 参与者的优势手（'left' 或 'right'）

    9-HPT（Nine-Hole Peg Test）是一种评估上肢精细运动功能的标准化测试。
    本函数从 9HPT 专用 Excel 文件中，根据 participant_id 和 session_date 匹配记录，
    并根据 'Dominant Hand' 和 'Hand Used' 字段判断哪只手是优势手/非优势手。

    输出格式：
      - '9hpt_dom' 和 '9hpt_ndom' 为逗号分隔字符串，顺序与 session 列严格对齐
      - 若某次会话无有效数据，则对应位置为空字符串 ''
      - 'handedness' 一旦确定即保留（不被后续会话覆盖）

    参数:
        participants (Dict[str, List[str]]): 
            participant_id 到其会话日期列表的映射，如 {'sub-5000017': ['20231005']}
        df (pd.DataFrame): 
            输入 DataFrame，必须包含 'participant_id' 列；可选已存在 'handedness'
        clinical_data_dir (Path): 
            临床数据目录路径

    返回:
        pd.DataFrame: 添加/更新了 '9hpt_dom', '9hpt_ndom', 'handedness' 三列的 DataFrame
    """
    
    # 构建 9HPT 专用 Excel 文件路径
    excel_path = clinical_data_dir / EXCEL_FILES['9hpt']
    
    # 尝试加载 9HPT 数据文件
    excel_df = load_excel_file(excel_path)
    
    # 如果文件加载失败，所有相关字段设为空并返回
    if excel_df is None:
        df['9hpt_dom'] = ''
        df['9hpt_ndom'] = ''
        df['handedness'] = ''
        return df
    
    # 初始化三列为空字符串（确保列存在）
    df['9hpt_dom'] = ''
    df['9hpt_ndom'] = ''
    df['handedness'] = ''
    
    # 记录缺失 9HPT 数据的 (participant_session) 组合，用于日志
    missing_9hpt_sessions = []
    
    # 遍历 DataFrame 中的每个 participant_id（使用 enumerate 获取行索引 idx）
    for idx, participant_id in enumerate(df['participant_id']):
        # 提取纯数字 ID（去除 'sub-' 前缀）
        numeric_id = participant_id.replace('sub-', '')
        
        # 获取该参与者的所有会话日期
        session_dates = participants[participant_id]
        
        # 在 9HPT Excel 数据中查找所有匹配该 numeric_id 的行
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果该参与者在 9HPT 文件中无任何记录
        if matching_rows.empty:
            # 所有会话的 dom/ndom/handedness 均设为空
            df.at[idx, '9hpt_dom'] = ','.join([''] * len(session_dates))
            df.at[idx, '9hpt_ndom'] = ','.join([''] * len(session_dates))
            df.at[idx, 'handedness'] = ''
            # 记录所有缺失的会话
            missing_9hpt_sessions.extend([f"{participant_id}_{sd}" for sd in session_dates])
            continue
        
        # 初始化当前参与者的 dom/ndom 时间列表（按 session_dates 顺序填充）
        session_dom = []
        session_ndom = []
        
        # 读取当前行已有的 handedness（可能由其他函数预先设置）
        # 如果尚未设置（空字符串），则在找到有效数据时赋值
        handedness = df.at[idx, 'handedness']
        
        # 遍历该参与者的每一个会话日期
        for session_date in session_dates:
            found = False  # 标记是否找到匹配的评估记录
            
            # 在 matching_rows 中逐行查找：是否有评估日期与 session_date 匹配
            for row_idx, row in matching_rows.iterrows():
                assessment_date_str = row['Assessment Started At']
                
                # 跳过空的评估时间
                if pd.isna(assessment_date_str):
                    continue
                
                # 提取标准化日期（如 "20231005"）
                assessment_date = extract_date_from_datetime(str(assessment_date_str))
                
                # 如果日期匹配
                if assessment_date == session_date:
                    # 安全提取并标准化 'Dominant Hand' 字段（应为 'left'/'right'）
                    dominant_hand = (
                        str(row['Dominant Hand']).strip().lower() 
                        if pd.notna(row['Dominant Hand']) else ''
                    )
                    
                    # 安全提取 'Hand Used' 字段（表示本次测试用的是哪只手）
                    hand_used = (
                        str(row['Hand Used']).strip().lower() 
                        if pd.notna(row['Hand Used']) else ''
                    )
                    
                    # 提取左右手完成时间（保留原始类型，后续转字符串）
                    left_time = row['Left Hand Time'] if pd.notna(row['Left Hand Time']) else ''
                    right_time = row['Right Hand Time'] if pd.notna(row['Right Hand Time']) else ''
                    
                    # 关键逻辑：只有当 'Hand Used' 与 'Dominant Hand' 一致时，
                    # 才认为本次测试提供了有效的 dom/ndom 配对数据
                    if hand_used == dominant_hand:
                        if hand_used == 'left':
                            # 左手是优势手 → left_time 为 dom，right_time 为 ndom
                            session_dom.append(str(left_time) if left_time != '' else '')
                            session_ndom.append(str(right_time) if right_time != '' else '')
                            # 如果 handedness 尚未设置，则推断为 'left'
                            if not handedness:
                                handedness = 'left'
                        elif hand_used == 'right':
                            # 右手是优势手 → right_time 为 dom，left_time 为 ndom
                            session_dom.append(str(right_time) if right_time != '' else '')
                            session_ndom.append(str(left_time) if left_time != '' else '')
                            if not handedness:
                                handedness = 'right'
                        else:
                            # dominant_hand 不是 'left'/'right'（如空、'ambidextrous' 等）
                            session_dom.append('')
                            session_ndom.append('')
                    else:
                        # Hand Used 与 Dominant Hand 不一致 → 无法可靠分配 dom/ndom
                        # （例如：优势手是右手，但这次只测了左手）
                        session_dom.append('')
                        session_ndom.append('')
                    
                    found = True
                    break  # 找到第一个匹配记录即停止（⚠️ 注意：存在重复时仅用第一条）
            
            # 如果未找到匹配的评估记录
            if not found:
                session_dom.append('')
                session_ndom.append('')
                missing_9hpt_sessions.append(f"{participant_id}_{session_date}")
        
        # 将当前参与者的所有会话结果写入 DataFrame 对应行
        df.at[idx, '9hpt_dom'] = ','.join(session_dom)
        df.at[idx, '9hpt_ndom'] = ','.join(session_ndom)
        df.at[idx, 'handedness'] = handedness  # 更新 handedness（可能仍为空）
    
    # 如果存在缺失的 9HPT 会话，记录警告日志（最多显示前 10 条）
    if missing_9hpt_sessions:
        logger.warning(f"Missing 9hpt for sessions: {missing_9hpt_sessions[:10]}...")
    
    return df


def process_edss_field(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 中的每个受试者（participant）生成 'edss' 字段。
    
    EDSS（Expanded Disability Status Scale）是多发性硬化症患者残疾程度的临床评分。
    该函数从指定 Excel 文件中读取 EDSS 数据，并根据受试者 ID 和随访日期（session date）
    匹配对应的 EDSS 分数，最终将结果以逗号分隔字符串的形式填入 df['edss'] 列中。
    
    参数：
        participants (Dict[str, List[str]]): 
            字典，键为受试者 ID（如 'sub-001'），值为该受试者所有 session 的日期列表（格式如 '2023-05-15'）。
        df (pd.DataFrame): 
            输入的主数据框，必须包含 'participant_id' 列。
        clinical_data_dir (Path): 
            临床数据所在目录路径。
    
    返回：
        pd.DataFrame: 添加了 'edss' 列的 df。
    """
    
    # 构建 EDSS 数据 Excel 文件的完整路径
    excel_path = clinical_data_dir / EXCEL_FILES['edss']
    
    # 尝试加载 Excel 文件（假设 load_excel_file 是自定义函数，处理文件不存在或读取错误等情况）
    excel_df = load_excel_file(excel_path)
    
    # 如果无法加载 EDSS 数据，则为所有受试者填充空字符串
    if excel_df is None:
        df['edss'] = ''
        return df
    
    # 用于存储每个受试者对应各 session 的 EDSS 值（最终每行一个逗号分隔字符串）
    edss_values = []
    # 记录缺失 EDSS 数据的 session（用于日志警告）
    missing_edss_sessions = []
    
    # 遍历主数据框中的每个受试者
    for participant_id in df['participant_id']:
        # 去掉 'sub-' 前缀，得到纯数字 ID（如 'sub-123' → '123'）
        numeric_id = participant_id.replace('sub-', '')
        # 获取该受试者的所有 session 日期列表
        session_dates = participants[participant_id]
        
        # 在 EDSS 表中查找 ID Dresden 列匹配当前 numeric_id 的所有行
        # 注意：先转换为字符串并去除首尾空格，确保匹配准确
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果没有找到任何匹配的受试者记录
        if matching_rows.empty:
            # 为该受试者的所有 session 填充空字符串（数量等于 session 数量）
            edss_values.append(','.join([''] * len(session_dates)))
            # 记录所有缺失的 session（格式：sub-xxx_yyyy-mm-dd）
            missing_edss_sessions.extend([
                f"{participant_id}_{sd}" for sd in session_dates
            ])
            continue  # 跳过后续处理
        
        # 存储当前受试者每个 session 对应的 EDSS 值
        session_edss = []
        
        # 遍历该受试者的每一个 session 日期
        for session_date in session_dates:
            found = False  # 标记是否在 EDSS 表中找到匹配的 visit date
            
            # 遍历所有匹配该受试者的 EDSS 行（可能有多次随访记录）
            for idx, row in matching_rows.iterrows():
                visitdate_str = row['Visitdate']
                # 如果 Visitdate 为空，跳过
                if pd.isna(visitdate_str):
                    continue
                
                # 将 Visitdate 字符串解析为标准日期格式（如 '2023-05-15'）
                # extract_date_from_visitdate 是自定义函数，处理不同日期格式
                visit_date = extract_date_from_visitdate(str(visitdate_str))
                
                # 如果解析后的日期与当前 session 日期一致
                if visit_date == session_date:
                    score_edss = row['scoreEdss']
                    # 处理 EDSS 分数为空或 NaN 的情况
                    if pd.isna(score_edss) or score_edss == '':
                        session_edss.append('')
                    else:
                        # 转为字符串（保留原始精度，避免 float 显示问题）
                        session_edss.append(str(score_edss))
                    found = True
                    break  # 找到匹配项后跳出内层循环
            
            # 如果遍历完所有行都没找到匹配的 visit date
            if not found:
                session_edss.append('')  # 当前 session 无 EDSS 数据
                missing_edss_sessions.append(f"{participant_id}_{session_date}")
        
        # 将该受试者所有 session 的 EDSS 值用逗号连接成一个字符串
        edss_values.append(','.join(session_edss))
    
    # 将生成的 EDSS 字符串列表赋值给 df 的新列 'edss'
    df['edss'] = edss_values
    
    # 如果存在缺失的 session，记录警告日志（最多显示前 10 个）
    if missing_edss_sessions:
        logger.warning(f"Missing edss for sessions: {missing_edss_sessions[:10]}...")
    
    return df


def process_t25fw_field(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 中的每个受试者生成 't25fw' 字段。
    
    T25FW（Timed 25-Foot Walk）是一项评估多发性硬化症患者行走功能的标准化测试，
    记录患者走完 25 英尺所需的时间（单位通常为秒）。
    
    本函数从指定的 Excel 文件中读取 T25FW 数据，并根据受试者 ID 和 session 日期
    匹配对应的“Walk Duration”值，最终将结果以逗号分隔的字符串形式填入 df['t25fw'] 列。
    
    参数：
        participants (Dict[str, List[str]]): 
            字典，键为受试者 ID（如 'sub-001'），值为该受试者所有 session 的日期列表（格式如 '2023-05-15'）。
        df (pd.DataFrame): 
            输入的主数据框，必须包含 'participant_id' 列。
        clinical_data_dir (Path): 
            临床数据所在目录路径。
    
    返回：
        pd.DataFrame: 添加了 't25fw' 列的 df。
    """
    
    # 构建 T25FW 数据 Excel 文件的完整路径（EXCEL_FILES 是预定义的文件名映射字典）
    excel_path = clinical_data_dir / EXCEL_FILES['t25fw']
    
    # 尝试加载 Excel 文件（load_excel_file 应能处理文件缺失或读取错误，并返回 None）
    excel_df = load_excel_file(excel_path)
    
    # 如果无法加载 T25FW 数据，则为所有受试者填充空字符串
    if excel_df is None:
        df['t25fw'] = ''
        return df
    
    # 存储每个受试者对应各 session 的 T25FW 值（每项为逗号分隔字符串）
    t25fw_values = []
    # 记录缺失 T25FW 数据的 session（用于日志警告）
    missing_t25fw_sessions = []
    
    # 遍历主数据框中的每个受试者
    for participant_id in df['participant_id']:
        # 去除 'sub-' 前缀，得到纯数字 ID（例如 'sub-123' → '123'）
        numeric_id = participant_id.replace('sub-', '')
        # 获取该受试者的所有 session 日期列表
        session_dates = participants[participant_id]
        
        # 在 T25FW 表中查找 'ID Dresden' 列匹配当前 numeric_id 的所有行
        # 注意：先转换为字符串并去除首尾空格，避免因格式问题匹配失败
        matching_rows = excel_df[
            excel_df['ID Dresden'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果没有找到任何匹配的受试者记录
        if matching_rows.empty:
            # 为该受试者的所有 session 填充空字符串（数量等于 session 数量）
            t25fw_values.append(','.join([''] * len(session_dates)))
            # 记录所有缺失的 session（格式：sub-xxx_yyyy-mm-dd）
            missing_t25fw_sessions.extend([
                f"{participant_id}_{sd}" for sd in session_dates
            ])
            continue  # 跳过后续处理
        
        # 存储当前受试者每个 session 对应的 T25FW 时间值
        session_t25fw = []
        
        # 遍历该受试者的每一个 session 日期
        for session_date in session_dates:
            found = False  # 标记是否在 T25FW 表中找到匹配的评估日期
            
            # 遍历所有匹配该受试者的 T25FW 行（可能有多次评估记录）
            for idx, row in matching_rows.iterrows():
                assessment_date_str = row['Assessment Started At']
                # 如果评估开始时间为空，跳过该行
                if pd.isna(assessment_date_str):
                    continue
                
                # 从完整的 datetime 字符串中提取日期部分（如 '2023-05-15 14:30:00' → '2023-05-15'）
                # extract_date_from_datetime 是自定义函数，负责标准化日期格式
                assessment_date = extract_date_from_datetime(str(assessment_date_str))
                
                # 如果提取的日期与当前 session 日期一致
                if assessment_date == session_date:
                    walk_duration = row['Walk Duration']
                    # 处理 Walk Duration 为空、NaN 或空字符串的情况
                    if pd.isna(walk_duration) or walk_duration == '':
                        session_t25fw.append('')
                    else:
                        # 转为字符串（保留原始数值格式，避免浮点显示问题）
                        session_t25fw.append(str(walk_duration))
                    found = True
                    break  # 找到匹配项后立即跳出内层循环
            
            # 如果遍历完所有匹配行仍未找到对应日期的记录
            if not found:
                session_t25fw.append('')  # 当前 session 无 T25FW 数据
                missing_t25fw_sessions.append(f"{participant_id}_{session_date}")
        
        # 将该受试者所有 session 的 T25FW 值用逗号连接成一个字符串
        t25fw_values.append(','.join(session_t25fw))
    
    # 将生成的 T25FW 字符串列表赋值给 df 的新列 't25fw'
    df['t25fw'] = t25fw_values
    
    # 如果存在缺失的 session，记录警告日志（最多显示前 10 个）
    if missing_t25fw_sessions:
        logger.warning(f"Missing t25fw for sessions: {missing_t25fw_sessions[:10]}...")
    
    return df


def process_education_field(
    participants: Dict[str, List[str]], 
    df: pd.DataFrame, 
    clinical_data_dir: Path
) -> pd.DataFrame:
    """
    为 DataFrame 中的每个受试者生成 'education' 字段。
    
    此处的 'education' 通常指受试者的受教育年限（如 12 年、16 年等），属于人口学或基线信息。
    尽管教育程度一般不会随时间变化，但本函数仍按 session 日期对齐数据（可能用于一致性处理或验证）。
    
    数据来源：指定目录下的教育信息 Excel 文件，通过 'mpi' 字段匹配受试者 ID，
    并通过 'encdate'（Unix 时间戳）匹配 session 日期。
    
    参数：
        participants (Dict[str, List[str]]): 
            字典，键为受试者 ID（如 'sub-001'），值为该受试者所有 session 的日期列表（格式如 '2023-05-15'）。
        df (pd.DataFrame): 
            输入的主数据框，必须包含 'participant_id' 列。
        clinical_data_dir (Path): 
            临床数据所在目录路径。
    
    返回：
        pd.DataFrame: 添加了 'education' 列的 df。
    """
    
    # 构建教育信息 Excel 文件的完整路径（EXCEL_FILES 是预定义的文件名映射字典）
    excel_path = clinical_data_dir / EXCEL_FILES['education']
    
    # 尝试加载 Excel 文件；若失败（如文件不存在或读取错误），load_excel_file 应返回 None
    excel_df = load_excel_file(excel_path)
    
    # 如果无法加载教育数据，则为所有受试者填充空字符串
    if excel_df is None:
        df['education'] = ''
        return df
    
    # 存储每个受试者对应各 session 的教育年限值（最终每行一个逗号分隔字符串）
    education_values = []
    # 记录缺失教育数据的 session（用于日志警告）
    missing_education_sessions = []
    
    # 遍历主数据框中的每个受试者
    for participant_id in df['participant_id']:
        # 去除 'sub-' 前缀，得到纯数字 ID（例如 'sub-123' → '123'）
        numeric_id = participant_id.replace('sub-', '')
        # 获取该受试者的所有 session 日期列表
        session_dates = participants[participant_id]
        
        # 在教育数据表中查找 'mpi' 列匹配当前 numeric_id 的所有行
        # 注意：先转换为字符串并去除首尾空格，避免因格式问题（如前导空格）导致匹配失败
        matching_rows = excel_df[
            excel_df['mpi'].astype(str).str.strip() == numeric_id
        ]
        
        # 如果没有找到任何匹配的受试者记录
        if matching_rows.empty:
            # 为该受试者的所有 session 填充空字符串（数量等于 session 数量）
            education_values.append(','.join([''] * len(session_dates)))
            # 记录所有缺失的 session（格式：sub-xxx_yyyy-mm-dd）
            missing_education_sessions.extend([
                f"{participant_id}_{sd}" for sd in session_dates
            ])
            continue  # 跳过后续处理
        
        # 存储当前受试者每个 session 对应的教育年限
        session_education = []
        
        # 遍历该受试者的每一个 session 日期
        for session_date in session_dates:
            found = False  # 标记是否在教育表中找到匹配的评估日期
            
            # 遍历所有匹配该受试者的教育记录行（理论上可能有多次录入，但教育年限通常不变）
            for idx, row in matching_rows.iterrows():
                encdate_str = row['encdate']
                # 如果 encdate（就诊/录入时间戳）为空，跳过该行
                if pd.isna(encdate_str):
                    continue
                
                # 从 Unix 时间戳字符串中提取标准日期（如 '1620123456' → '2021-05-04'）
                # extract_date_from_timestamp 是自定义函数，负责将时间戳转为 'YYYY-MM-DD' 格式
                enc_date = extract_date_from_timestamp(str(encdate_str))
                
                # 如果提取的日期与当前 session 日期一致
                if enc_date == session_date:
                    educ = row['educ']  # 获取教育年限字段
                    # 处理 educ 为空、NaN 或空字符串的情况
                    if pd.isna(educ) or educ == '':
                        session_education.append('')
                    else:
                        # 转为字符串（保留原始值，如整数 12 或浮点 12.0）
                        session_education.append(str(educ))
                    found = True
                    break  # 找到匹配项后立即跳出内层循环
            
            # 如果遍历完所有匹配行仍未找到对应日期的记录
            if not found:
                session_education.append('')  # 当前 session 无教育数据
                missing_education_sessions.append(f"{participant_id}_{session_date}")
        
        # 将该受试者所有 session 的教育值用逗号连接成一个字符串
        education_values.append(','.join(session_education))
    
    # 将生成的教育字符串列表赋值给 df 的新列 'education'
    df['education'] = education_values
    
    # 如果存在缺失的 session，记录警告日志（最多显示前 10 个）
    if missing_education_sessions:
        logger.warning(f"Missing education for sessions: {missing_education_sessions[:10]}...")
    
    return df


def main():
    """
    主函数：生成 BIDS 兼容的 participants.tsv 文件。
    
    功能概述：
      1. 从 BIDS 数据目录中扫描所有受试者及其 session；
      2. 依次处理各类临床/人口学字段（如年龄、性别、EDSS、T25FW 等）；
      3. 将所有字段合并到一个 DataFrame 中；
      4. 按照预定义顺序排列列；
      5. 保存为制表符分隔的 TSV 文件。
    
    依赖全局变量（应在脚本其他位置定义）：
      - BIDS_DATA_DIR: BIDS 格式数据根目录（Path 对象）
      - CLINICAL_DATA_DIR: 临床 Excel 数据所在目录（Path 对象）
      - OUTPUT_FILE: 输出文件路径（如 Path("participants.tsv")）
      - logger: 已配置的日志记录器
    """
    
    logger.info("Starting participants.tsv generation...")
    
    # 从 BIDS 目录结构中自动提取所有受试者 ID 及其对应的 session 日期列表
    # 返回格式：{'sub-001': ['2023-01-15', '2023-06-20'], 'sub-002': [...], ...}
    participants = get_participants_and_sessions(BIDS_DATA_DIR)
    
    # 如果未找到任何受试者，记录错误并退出
    if not participants:
        logger.error("No participants found in BIDS directory!")
        return
    
    # 初始化空的 pandas DataFrame，用于逐步添加各字段
    df = pd.DataFrame()
    
    # ———————— 逐个处理各字段 ————————
    
    logger.info("Processing participant_id field...")
    # 生成 'participant_id' 列（如 sub-001, sub-002...）
    df = process_participant_id_field(participants)
    
    logger.info("Processing session field...")
    # 生成 'session' 列，每个受试者对应多个 session，值为逗号分隔的日期字符串
    df = process_session_field(participants, df)
    
    logger.info("Processing age field...")
    # 从临床数据中提取每个 session 对应的年龄（可能基于出生日期和 session 日期动态计算）
    df = process_age_field(participants, df, CLINICAL_DATA_DIR)
    
    logger.info("Processing sex field...")
    # 提取性别信息（通常为静态字段，但按 session 重复填充以保持结构一致）
    df = process_sex_field(df, CLINICAL_DATA_DIR)
    
    logger.info("Processing is_ms field...")
    # 标记是否为多发性硬化症患者（MS vs HC），通常为二元标签（如 'yes'/'no' 或 1/0）
    df = process_is_ms_field(df, CLINICAL_DATA_DIR)
    
    logger.info("Processing sdmt field...")
    # SDMT（Symbol Digit Modalities Test）认知测试得分
    df = process_sdmt_field(participants, df, CLINICAL_DATA_DIR)
    
    logger.info("Processing 9hpt fields...")
    # 9-Hole Peg Test（九孔 peg 测试）：分别处理优势手（dominant）和非优势手（non-dominant）
    # 同时可能包含 'handedness'（利手）字段
    df = process_9hpt_fields(participants, df, CLINICAL_DATA_DIR)
    
    logger.info("Processing edss field...")
    # EDSS（Expanded Disability Status Scale）残疾评分
    df = process_edss_field(participants, df, CLINICAL_DATA_DIR)
    
    logger.info("Processing t25fw field...")
    # T25FW（Timed 25-Foot Walk）行走时间测试
    df = process_t25fw_field(participants, df, CLINICAL_DATA_DIR)
    
    logger.info("Processing education field...")
    # 教育年限（如 12 年、16 年等）
    df = process_education_field(participants, df, CLINICAL_DATA_DIR)
    
    # ———————— 列顺序标准化 ————————
    
    # 定义最终 TSV 文件的列顺序，确保符合 BIDS 或项目规范
    column_order = [
        'participant_id', 'session', 'age', 'sex', 'is_ms', 'sdmt',
        '9hpt_dom', '9hpt_ndom', 'handedness', 'edss', 't25fw', 'education'
    ]
    
    # 按指定顺序重排 DataFrame 的列
    # 注意：若某列不存在会报错，因此需确保所有字段处理函数都已正确执行
    df = df[column_order]
    
    # ———————— 保存结果 ————————
    
    # 将 DataFrame 保存为制表符分隔的 TSV 文件，不包含行索引，使用 UTF-8 编码
    df.to_csv(OUTPUT_FILE, sep='\t', index=False, encoding='utf-8')
    
    # 记录成功日志
    logger.info(f"Successfully generated participants.tsv at {OUTPUT_FILE}")
    logger.info(f"Total participants: {len(df)}")
    logger.info("Generation complete!")


if __name__ == "__main__":
    main()

