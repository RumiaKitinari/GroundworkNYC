import math 
import os

# STEP 1: Get the data in "current restaurants"
cur_path = os.path.dirname(__file__)
data_path = os.path.relpath('..\\data\\raw\\c_rest\\current_restaurants.csv', cur_path)
csvfile = open(data_path, 'r').readlines()

# STEP 2: Splits the file into 8
filename = 1
split_interval = math.ceil(len(csvfile) / 8) # Split the file into 8
for i in range(len(csvfile)):
    if i % split_interval == 0:
        new_path = os.path.relpath(f'..\\data\\raw\\c_rest\\current_restaurants_{filename}.csv')
        open(new_path, 'w+').writelines(csvfile[i:i+split_interval])
        filename += 1

print(f"{filename} files created in data/raw/c_rest.")