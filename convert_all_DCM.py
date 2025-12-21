"""
This script converts all DICOM folders to research format, including:
- NIfTI (.nii.gz)
- JSON (.json)
"""

import os
import re
import time
import argparse
import numpy as np
from tqdm import tqdm
import nibabel as nib
import datetime as dt
from scipy import ndimage
from matplotlib.image import imsave


def get_brain_slice_images(nifti_path, output_dir_path=None):
    """ Get PNG images of brain slices in all directions of a NIfTI
    Note: if 4D, take first entry of last dimension

    :param nifti_path: str, path to NIfTI file
    :param output_dir_path: str, path to output directory. If None, this will be the path to the NIfTI parent directory.
    """
    # Load NIfTI
    img = nib.load(nifti_path).get_fdata()

    # If 4 dimensions, take first time-point (assuming time dimension is last dimension)
    if img.ndim == 4:
        img = img[:, :, :, 0]

    if img.ndim == 3:
        # Get slices in all directions
        slice_1 = img[img.shape[0]//2, :, :]
        slice_2 = img[:, img.shape[1]//2, :]
        slice_3 = img[:, :, img.shape[2]//2]

        # Save images
        if output_dir_path is None:
            output_dir_path = os.path.dirname(nifti_path)
        for i, img_slice in enumerate([slice_1, slice_2, slice_3]):
            filename = os.path.basename(nifti_path).replace('.nii.gz', f'_slice_{i+1}.png')
            img_slice_rotated = ndimage.rotate(img_slice, 90)
            imsave(os.path.join(output_dir_path, filename), img_slice_rotated, cmap='gray')


def get_time_diff(start_time, end_time):
    """
    Source: https://www.notdefined.tech/blog/how-to-track-runtime-of-a-python-script/
    """
    runtime = end_time - start_time

    if runtime < 60:
        return f'Runtime: {runtime:.2f} seconds'
    elif runtime < 3600:  # Less than one hour
        minutes = runtime / 60
        return f'Runtime: {minutes:.2f} minutes'
    else:
        hours = runtime / 3600
        return f'Runtime: {hours:.2f} hours'


if __name__ == "__main__":
    # Define paths
    parser = argparse.ArgumentParser()
    parser.add_argument('--root_path_output', default='/home/data/Prague/dcm2niix_outputs/',
                        type=str, help='Root path for dcm2niix outputs')
    args = parser.parse_args()

    # Define input path
    root_path_input = '/home/data/Prague/DICOM_collection/'

    # Initialisations
    start_time = time.time()
    log_txt = ''
    existing_subjects_sessions = {}
    for root, dirs, files in os.walk(args.root_path_output):
        if re.findall('sub-Prague[0-9]{6}', root) and re.findall('ses-[0-9]{8}', root):
            subject = re.findall('sub-Prague[0-9]{6}', root)[0]
            session = re.findall('ses-[0-9]{8}', root)[0]
            if subject not in existing_subjects_sessions.keys():
                existing_subjects_sessions[subject] = [session]
            else:
                existing_subjects_sessions[subject] += [session]

    print(existing_subjects_sessions)

    # Get all DICOM folders
    print('Listing all DICOM folders...')
    all_dicom_folder_paths = {}
    for (root, dirs, files) in os.walk(root_path_input):
        if re.findall('\ACZ-Prg_[0-9]{6}.[0-9]{8}\Z', root.split('/')[-1]):
            if '/T1/' in root:
                modality = 'T1w'
            elif '/FLAIR/' in root:
                modality = 'FLAIR'
            all_dicom_folder_paths.update({root: modality})

    # DICOM to NIFTI conversion
    print('DICOM to NIfTI conversion...')
    for i, (dicom_dir_path, modality) in tqdm(enumerate(all_dicom_folder_paths.items())):  # tdqm for progress bar
        #if i == 10:
        #   break
        subject_id_orig = re.findall(r'CZ-Prg_[0-9]{6}.[0-9]{8}', dicom_dir_path)[0]
        subject_id_new = f"sub-Prague{subject_id_orig.split('_')[1].split('.')[0]}"  # Only keep the subject number
        session = f"ses-{subject_id_orig.split('_')[1].split('.')[1]}"
        if subject_id_new in existing_subjects_sessions.keys():
            if session in existing_subjects_sessions[subject_id_new]:
                print(f'Skipping subject {subject_id_new}, session {session}')
                continue
        subject_path = os.path.join(args.root_path_output, subject_id_new)
        session_path = os.path.join(subject_path, session)
        modality_path = os.path.join(session_path, modality)

        # Create a sub-folder for subject that will contain all MRI sessions
        if not os.path.exists(subject_path):
            os.mkdir(subject_path)
        if not os.path.exists(session_path):
            os.mkdir(session_path)
        if not os.path.exists(modality_path):
            os.mkdir(modality_path)

        # DICOM to NIfTI conversion
        # Note: -o output flag (output dir), -z zips the file (y = "yes"), dicom path to convert added last
        try:
            os.system(f'dcm2niix -o {modality_path} -z y {dicom_dir_path}')
        except ValueError as e:
            log_txt += f'{"#"*30}\nA problem occurred for: {dicom_dir_path}\n\n{e}\n\n'

    # List all MRI series and make subdirectories
    series_dir_paths = []
    for root, dirs, files in os.walk(args.root_path_output):
        for file in files:
            if file.endswith('.nii.gz') and root.split('/')[-1].startswith('ses-'):
                nifti_path = os.path.join(root, file)
                series_dir_path = os.path.join(os.path.dirname(nifti_path), file.removesuffix('.nii.gz'))
                series_dir_paths.append(series_dir_path)
                if not os.path.exists(series_dir_path):
                    os.makedirs(series_dir_path)

    # Collect all files in subdirectories per MRI series
    for series_dir_path in tqdm(series_dir_paths):
        for extension in ['.nii.gz', '.json']:
            file_path_old = series_dir_path + extension
            file_path_new = os.path.join(series_dir_path, series_dir_path.split(os.sep)[-1] + extension)
            if os.path.exists(file_path_old):
                os.system(f'mv {file_path_old} {file_path_new}')
                if extension == '.nii.gz':
                    try:
                        get_brain_slice_images(file_path_new)
                    except np.exceptions.DTypePromotionError as e:
                        log_txt += f'{"#"*30}\nNo snapshots created for: {file_path_new}\n\n{e}\n\n'

    # Get time difference, add to log file and save log
    end_time = time.time()
    time_diff = get_time_diff(start_time, end_time)
    log_txt += f'Script time: {time_diff}'
    log_txt_path = os.path.join(args.root_path_output, f'log_{dt.datetime.now().strftime("%Y%m%d-%H%M%S")}.txt')
    with open(log_txt_path, 'w') as file:
        file.write(log_txt)
