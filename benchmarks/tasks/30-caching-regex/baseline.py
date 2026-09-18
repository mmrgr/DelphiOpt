import re

def workload(values):
    return [bool(re.compile(r'^[a-z]+$').match(value)) for value in values]
