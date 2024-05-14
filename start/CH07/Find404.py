#!/usr/bin/env python3
# By 5/14 David Locke

import os

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
    #check for 404
    if " 404 " in line:
        #print line
        print(line)
