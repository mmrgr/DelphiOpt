def workload(values):
    result = []
    index = 0
    while index < len(values):
        result.append((index, values[index]))
        index += 1
    return result
