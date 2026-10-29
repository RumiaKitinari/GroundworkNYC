import math 
import os
import csv

# STEP 1: Get the data in "current restaurants"
cur_path = os.path.dirname(__file__)
data_path = os.path.relpath('..\\data\\raw\\c_rest\\current_restaurants.csv', cur_path)
csvfile = open(data_path, 'r').readlines()
split_interval = math.ceil(len(csvfile) / 8) # Split the file into 8

# STEP 2: Splits the file into 8
filename = 1
split_interval = math.ceil(len(csvfile) / 8) # Split the file into 8
for i in range(len(csvfile)):
    if i % split_interval == 0:
        new_path = os.path.relpath(f'..\\data\\raw\\c_rest\\current_restaurants_{filename}.csv')
        if(i == 0):
            open(new_path, 'w+').writelines(csvfile[i:i+split_interval])
        else:
            open(new_path, 'w+').writelines(csvfile[0:1] + csvfile[i:i+split_interval])
        filename += 1

print(f"{filename - 1} files created in data/raw/c_rest.") 


# ARCHIVED:
# csvfile = open(os.path.join(data_path, 'current_restaurants.csv'), 'r').readlines()

# Source - https://stackoverflow.com/a/49452109
# Posted by ryantuck, modified by community. See post 'Timeline' for change history
# Retrieved 2026-10-08, License - CC BY-SA 4.0

# def split_csv(source_filepath, dest_folder, split_file_prefix,
#                 split_interval):
#     """
#     Split a source csv into multiple csvs of equal numbers of records,
#     except the last file.

#     Includes the initial header row in each split file.

#     Split files follow a zero-index sequential naming convention like so:

#         `{split_file_prefix}_0.csv`
#     """
#     if split_interval <= 0:
#         raise Exception('split_interval must be > 0')

#     with open(source_filepath, 'r') as source:
#         reader = csv.reader(source)
#         headers = next(reader)

#         file_idx = 0
#         records_exist = True

#         while records_exist:
#             i = 0
#             target_filename = f'{split_file_prefix}.csv'
#             target_filepath = os.path.join(dest_folder, target_filename)
#             split_interval = math.ceil(len(csvfile) / 8) # Split the file into 8

#             with open(target_filepath, 'w') as target:
#                 split_interval = math.ceil(len(target) / 8) # Split the file into 8
#                 writer = csv.writer(target)

#                 while i % split_interval:
#                     if i == 0:
#                         writer.writerow(headers)

#                     try:
#                         writer.writerow(next(reader))
#                         i += 1
#                     except StopIteration:
#                         records_exist = False
#                         break

#             if i == 0:
#                 # we only wrote the header, so delete that file
#                 os.remove(target_filepath)

#             file_idx += 1

# split_csv(data_path, data_path, "current_restaurants", split_interval)