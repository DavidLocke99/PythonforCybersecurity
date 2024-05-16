#!/usr/bin/env python3
# Script that scans web server logs for status codes
# Use RegEx to find and report on most frequent status messages
# By 5/14 David Locke

import os
import re

#set up pattern to match
re_pattern = r'^\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}'


file_path=os.path.dirname(__file__)

# prompt for filename
log_file=input("which file to analyze? ")
#open file
f=open(file_path+"/"+log_file, "r")

results_dict = {}

#read file line by line
while True:
    line=f.readline()
    if not line:
        break
    m = re.search(re_pattern, line) 
    if m:
        #print(m.group())
        item = m.group()
        # is item in dcictonary
        if item in results_dict.keys():
            # if Y add 1 to count
            results_dict[item] = results_dict[item]+1
        else:    
            # else add to dictionary
            results_dict[item]=1


for w in sorted(results_dict, key = results_dict.get, reverse=False
):

    print(w, results_dict[w])