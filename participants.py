"""
This script couples mri and phenotypic data
"""

import os
import re
import argparse
import numpy as np
import pandas as pd
import datetime as dt


def clean_cog_dates(val):
    if type(val) in [int, float]:
        if np.isnan(val):
            return pd.NaT
    elif re.fullmatch(r'\A[0-9]{2}.[0-9]{2}.[0-9]{4}\Z', val):
        return dt.datetime.strptime(val, '%d.%m.%Y')
    else:
        return ValueError(f'Could not convert {val} to date')


def clean_edss(val):
    val = str(val)
    if re.fullmatch(r'\A[0-9],[0-9]\Z', val):
        return float(val.replace(',', '.'))
    elif val == 'nan':
        return np.nan
    else:
        return ValueError(f'Could not convert EDSS score: {val}')


def get_lowest_lag(df, lag_colname):
    # Get the lowest time lag
    lowest_lag_df = pd.DataFrame()
    for imed in df['IMED'].unique():
        df_imed = df[df['IMED'] == imed]
        min_lag = df_imed[lag_colname].min()
        row_to_extract = df_imed[df_imed[lag_colname] == min_lag].iloc[[0]]  # Take first one if multiple
        lowest_lag_df = pd.concat([lowest_lag_df, row_to_extract])
    lowest_lag_df = lowest_lag_df.reset_index(drop=True)
    return lowest_lag_df


def merge_data(path_to_cog_df, path_to_mri_df, path_to_phenotypic_df, unique_subjects,
               unique_subject_criterion, max_lag_cog_mri, max_lag_edss_mri):

    # Load dataframes
    df_cog = pd.read_csv(path_to_cog_df, sep=';')
    df_mri = pd.read_excel(path_to_mri_df, sheet_name='MR_dates')
    df_pheno_1 = pd.read_excel(path_to_phenotypic_df, sheet_name=1)
    df_pheno_2 = pd.read_excel(path_to_phenotypic_df, sheet_name=3)

    # Clean dataframes
    # Note: In cog dataframe, some values were strings, others were numbers.
    df_cog['psycho_date'] = df_cog['psycho_date'].apply(clean_cog_dates)
    df_cog['IMED'] = df_cog['IMED'].apply(lambda x: int(x) if re.fullmatch(r'[0-9]{1,4}(\.[0-9])?', str(x)) else np.nan)
    df_mri = df_mri.rename(columns={'iMedID': 'IMED'})
    df_pheno_1 = df_pheno_1.rename(columns={'Patient ID': 'IMED'})
    df_pheno_2 = df_pheno_2.rename(columns={'Patient ID': 'IMED'})
    df_pheno_2['edss'] = df_pheno_2['EDSS_score'].apply(clean_edss)

    # Merge cog and MRI dataframes
    df = pd.merge(left=df_cog, right=df_mri, how='outer', on='IMED')
    df['abs_days_cog_mri'] = (df['psycho_date'] - df['DatumVys']).apply(
        lambda x: abs(x.days) if not pd.isnull(x) else np.nan
    )

    # Filter on max lag between cognition and MRI
    df = df[df['abs_days_cog_mri'] <= max_lag_cog_mri]
    df['max_lag_cog_mri'] = [max_lag_cog_mri]*df.shape[0]

    # Merge with EDSS dataframe
    df = pd.merge(left=df, right=df_pheno_2, how='left', on='IMED')
    df['abs_days_edss_mri'] = (df['EDSS_date'] - df['DatumVys']).apply(
        lambda x: abs(x.days) if not pd.isnull(x) else np.nan
    )

    # Filter on max lag between EDSS and MRI
    df = df[df['abs_days_edss_mri'] <= max_lag_edss_mri]
    df['max_lag_edss_mri'] = [max_lag_edss_mri]*df.shape[0]

    # Merge with df that contains birthdate and gender
    df = pd.merge(left=df, right=df_pheno_1, how='left', on='IMED')

    # Get unique psychological assessments
    df = df.loc[df[['IMED', 'psycho_date']].drop_duplicates().index].reset_index()

    # Select only one row per subject if desired
    if unique_subjects:
        if unique_subject_criterion == 'cog':
            df = get_lowest_lag(df, 'abs_days_cog_mri')
        elif unique_subject_criterion == 'edss':
            df = get_lowest_lag(df, 'abs_days_edss_mri')
        else:
            raise ValueError('Please choose a value for "--unique_subject_criterion" argument')

    # Get most recent pre-scan value for MS course
    ms_course_date_cols_dict = {int(re.findall('[0-9]+', col)[0]):col
                                for col in df.columns if col.startswith('Date MSCourse ')}
    ms_course_date_cols = [ms_course_date_cols_dict.get(key) for key in sorted(ms_course_date_cols_dict.keys())]

    course_dates = []
    course_values = []
    for i, row in df.iterrows():
        latest_date = np.nan
        latest_course = np.nan
        for date_col in ms_course_date_cols:
            course_col = date_col.replace('Date ', '').replace(' ', '')
            date = row[date_col]
            course = row[course_col]
            if str(date) != 'NaT':
                if date < row['DatumVys']:
                    latest_date = date
                    latest_course = course
        course_dates.append(latest_date)
        course_values.append(latest_course)
    df['latest_prescan_ms_course_date'] = course_dates
    df['latest_prescan_ms_course_value'] = course_values

    # Calculate age and disease duration
    df['age'] = (df['DatumVys'] - df['Birth Date']).apply(lambda x: x.days/365.2425)
    df['disease_duration'] = df['DatumVys'].apply(lambda x: x.year) - df['Date of onset'].apply(lambda x: x.year)

    ######################
    # SDMT z-normalisation
    ######################
    age_colname = 'age'  # Appears to be more or less equal to 'age_psy_assessment_calc'
    edu_years_colname = 'edu_years'
    sdmt_colname = 'sdmt90_total'

    # Clean edu_years and age columns
    df[edu_years_colname] = df[edu_years_colname].apply(clean_numeric_col)
    df[age_colname] = df[age_colname].apply(clean_numeric_col)

    # Create dummy variable for education level
    df['edu_dummy'] = df[edu_years_colname].apply(to_edu_dummy)

    # Calculate z-score
    df['z_sdmt'] = df.apply(lambda x: regression_based_z_normalisation(x[age_colname], x['edu_dummy'], x[sdmt_colname]), axis=1)

    # Cognitive impaired?
    df['imp_sdmt'] = df['z_sdmt'] <= -1

    # Delete columns
    df.drop(['sex', 'Last Name', 'First Name', 'Birth Date', 'Maiden Name', 'Active', 'Birth City', 'Birth Country', 'Address', 'City', 'Zip Code', 'State', 'Country', 'Home Phone', 'Work Phone',
             'Patient Code', 'Other Number', 'Email', 'Doctor in Charge', 'Deceased', 'Decease Date', 'Death Cause', 'Health Insurance', 'Health Insurance Code', 'Keywords', 'Clinical Study Code',
             'Marital Status', 'Education', 'Employment', 'Entry in the clinic'], axis='columns', inplace=True)

    # Add columns
    df['sex'] = df['Gender']

    # Rename columns
    df = df.rename(columns = {'Dominant Hand': 'handedness'})

    return df


# Z-normalisation functions
def clean_numeric_col(x):
    if type(x) == str:
        if re.findall('\A[0-9]+,[0-9]+\Z', x):
            return float(x.replace(',', '.'))
        elif re.findall('\A[0-9]+\Z', x):
            return float(x)
    elif type(x) in [float, int]:
        return x
    else:
        ValueError(f'Edu years not converted: {x}')


def to_edu_dummy(x):
    if not np.isnan(x) and type(x) in [float, int]:
        if x >= 16:
            return 1
        else:
            return 0
    else:
        return np.nan


def regression_based_z_normalisation(age, edu_dummy, sdmt_90):
    return (sdmt_90
            - 67.18042161
            + 0.0002014472924 * age**3
            - 0.000002358544643 * age**4
            - 3.864964401*edu_dummy) \
            / -8.342252676


def reorder_columns(df, preferred_first_columns):
    for col in preferred_first_columns[::-1]:
        new_cols = [col] + [col_ for col_ in df.columns if col_ != col]
        df = df.reindex(columns = new_cols)
    return df


def to_bids_id(old_id):
    return f"sub-Prague{str(int(old_id)).zfill(6)}"


def to_session_id(date):
    return f"ses-{date.strftime('%Y%m%d')}"



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--max_lag_cog_mri', type=int, default=180, help='Max number of days between cognitive and MRI assessment')
    parser.add_argument('--max_lag_edss_mri', type=int, default=90, help='Max number of days between edss and MRI assessment')
    parser.add_argument('--path_to_cog_df', type=str, help='Path to cognitive dataframe')
    parser.add_argument('--path_to_mri_df', type=str, help='Path to MRI dataframe')
    parser.add_argument('--path_to_phenotypic_df', type=str, help='Path to phenotypic data')
    parser.add_argument('--output_dir_path', type=str, help='Path to output directory')
    parser.add_argument('--unique_subjects', action='store_true', help='Unique subjects?')
    parser.add_argument('--unique_subject_criterion', type=str, default=None, help='Choose from:\n'
                                                                                   '- "cog": lowest cog-mri time lag\n'
                                                                                   '- "edss": lowest edss-mri time lag')
    args = parser.parse_args()

    df = merge_data(args.path_to_cog_df, args.path_to_mri_df, args.path_to_phenotypic_df, args.unique_subjects,
                    args.unique_subject_criterion, args.max_lag_cog_mri, args.max_lag_edss_mri)

    # Print number of subjects and save to dataframe
    print(f'Number of subjects: {df.shape[0]}')
    date_df_creation = dt.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
    df['participant_id'] = df['paciid'].apply(to_bids_id)
    df['session'] = df['DatumVys'].apply(to_session_id)
    df['date_df_creation'] = [date_df_creation]*df.shape[0]
    df['cog_df_used_for_merge'] = [args.path_to_cog_df]*df.shape[0]
    df['mri_df_used_for_merge'] = [args.path_to_mri_df]*df.shape[0]
    df['phenotypic_df_used_for_merge'] = [args.path_to_phenotypic_df]*df.shape[0]
    
    # Reorder columns
    df = reorder_columns(df, ['participant_id', 'session', 'sex', 'age', 'handedness', 'edss', 'disease_duration', 'sdmt_total_90', 'z_sdmt', 'imp_sdmt'])

    df.to_csv(os.path.join(args.output_dir_path, 'participants.tsv'), sep='\t', index=False)
