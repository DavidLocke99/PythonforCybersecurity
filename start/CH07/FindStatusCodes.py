#!/usr/bin/env python3
# Script that scans web server logs for status codes
# Use RegEx to find and report on most frequent status messages
# By 5/14 David Locke

import os
import re

#set up pattern to match
re_pattern = r'\s\d\d\d\s'


file_path=os.path.dirname(__file__)

# prompt for filename
log_file=input("which file to analyze? ")
#open file
f=open(file_path+"/"+log_file, "r")

#read file line by line
while True:
    line=f.readline()
    if not line:
        break
    m = re.search(re_pattern, line) 
    if m:
        print(m.group())
