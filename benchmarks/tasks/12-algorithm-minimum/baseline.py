def workload(values):
    return [min(values[:index]) for index in range(1, len(values) + 1)]
