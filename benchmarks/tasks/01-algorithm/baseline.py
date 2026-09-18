def workload(values, wanted):
    return sum(1 for value in values if value in wanted)
