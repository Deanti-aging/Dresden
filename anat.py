"""
This script selects T1w and FLAIR NIfTI and JSON metadata files
"""

import os
import argparse


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--root_path_bids', default='/home/data/Prague/BIDS/', type=str,
                        help='Root path to BIDS directory')
    parser.add_argument('--path_nifti_collection', default='/home/data/Prague/dcm2niix_outputs/',
                        type=str, help='Path to folder containing all NIfTIs')
    args = parser.parse_args()

    directory_contents = os.listdir(args.path_nifti_collection)
    for i, element in enumerate(directory_contents):
        if element.endswith('.txt'):
            continue
        else:
            subject = element
            print(f'{i}/{len(directory_contents)}', end='\r')
        subject_path = os.path.join(args.path_nifti_collection, subject)
        for session in os.listdir(subject_path):
            session_path = os.path.join(subject_path, session)
            for modality in os.listdir(session_path):
                modality_path = os.path.join(session_path, modality)
                for file in os.listdir(modality_path):
                    if file.endswith('.json'):
                        filename, file_ext = os.path.splitext(file)
                        break
                old_nifti_path = os.path.join(modality_path, f'{filename}.nii.gz')
                old_json_path = os.path.join(modality_path, f'{filename}.json')
                new_nifti_path = os.path.join(modality_path.replace(args.path_nifti_collection, args.root_path_bids), f'{subject}_{session}_{modality}.nii.gz')
                new_json_path = os.path.join(modality_path.replace(args.path_nifti_collection, args.root_path_bids), f'{subject}_{session}_{modality}.json')

                if not os.path.exists(os.path.dirname(new_nifti_path)):
                    os.makedirs(os.path.dirname(new_nifti_path))
                os.system(f'cp {old_nifti_path} {new_nifti_path}')
                os.system(f'cp {old_json_path} {new_json_path}')
