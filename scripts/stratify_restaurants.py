import os
import csv
from numpy import average, var
from math import sqrt

# Requirements: data/master_tract_features.csv (from Drive)

""" STEP 1: Get the data in "current restaurants" """
cur_path = os.path.dirname(__file__)
data_path = os.path.relpath('..\\data\\master_tract_features.csv', cur_path)
mtf = open(data_path, 'r').readlines()

m_house_inc = []  # median_household_income_2024
pop_dens = []     # population_density_per_sq_mile
rest_q = []       # jobs_accomodation_food_services = Proxy for q.

# STEP 1.1: Find the row number of these variables
mtf_rows = mtf[0].split(",")
ind = [mtf_rows.index("median_household_income_2024"), 
       mtf_rows.index("population_density_per_sq_mile"),
       mtf_rows.index("jobs_accommodation_food_services")]

# STEP 1.2: Extract the cols of income / density / q. restaurants
for i in range(1, len(mtf)):
    row = mtf[i].split(",")
    m_house_inc.append(row[ind[0]])
    pop_dens.append(row[ind[1]])
    rest_q.append(row[ind[2]])


""" STEP 2: Stratify these cols via CT frequency """
# STEP 2.1: Finding a mean / variance
m_house_inc_i = list(map(lambda i: float(i), filter(lambda i: i != '', m_house_inc)))
pop_dens_i = list(map(lambda i: float(i), filter(lambda i: i != '', pop_dens)))
rest_q_i = list(map(lambda i: float(i), filter(lambda i: i != '', rest_q)))

mhi_dist = (average(m_house_inc_i), sqrt(var(m_house_inc_i)))
pd_dist = (average(pop_dens_i), sqrt(var(pop_dens_i)))
rq_dist = (average(rest_q_i), sqrt(var(rest_q_i)))

# STEP 2.2: Using < 1 SD = "Regular", < 1.5 SD
# p-value: 0.674 SD = 50% (25%/side), 1.645 SD = 90% (10%/side)
mhi_cat = [mhi_dist[0]-1.645*mhi_dist[1], mhi_dist[0]-0.674*mhi_dist[1], 
           mhi_dist[0]+0.674*mhi_dist[1], mhi_dist[0]+1.645*mhi_dist[1]]
pd_cat =  [pd_dist[0]-1.645*pd_dist[1], pd_dist[0]-0.674*pd_dist[1], 
           pd_dist[0]+0.674*pd_dist[1], pd_dist[0]+1.645*pd_dist[1]]
rq_cat =  [rq_dist[0]-1.645*rq_dist[1], rq_dist[0]-0.674*rq_dist[1], 
           rq_dist[0]+0.674*rq_dist[1], rq_dist[0]+1.645*rq_dist[1]]

print(mhi_cat)
print(pd_cat)
print(rq_cat)

m_house_inc = []  # median_household_income_2024
pop_dens = []     # population_density_per_sq_mile
rest_q = []       # jobs_accomodation_food_services = Proxy for q.

# WARNING: Values < 0 -> Account for a skewed-normal distribution & find z-score (???)





# Source: https://www.geeksforgeeks.org/python/add-a-column-to-existing-csv-file-in-python/

# # Step 2: Define the values for the new "City" column
# new_city_values = ['New York', 'Los Angeles', 'Chicago', 'San Francisco']

# # Step 3: Add the new "City" column to the DataFrame
# mtf['City'] = new_city_values

# # Step 4: Write the DataFrame back to the CSV file
# mtf.to_csv(cur_path, index=False)