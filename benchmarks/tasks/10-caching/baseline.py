def workload(value):
    if value < 2:
        return value
    return workload(value - 1) + workload(value - 2)
