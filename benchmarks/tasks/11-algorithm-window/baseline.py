def workload(values, width):
    return [max(values[i:i + width]) for i in range(len(values) - width + 1)]
