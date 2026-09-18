def workload(values):
    result = {}
    for key, value in values:
        result = {**result, key: value}
    return result
