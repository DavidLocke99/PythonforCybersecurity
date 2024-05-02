#!/usr/bin/env python3
# ASCII generator
# Uses chr() to create ASCII characters
# By David  05/02

# loop through numbers 0-127
for number in range (128):
    letter = chr(number)
    #print number and chr() of number
    print(f"{number} - '{letter}'")
