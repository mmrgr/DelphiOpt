def workload(values):
    result = []
    for value in values:
        result.append(value if value >= 0 else -value)
    return result
