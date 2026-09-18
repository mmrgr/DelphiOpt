def workload(values):
    result = []
    for value in values:
        if value % 2 == 0:
            result.append(value)
    return result
