def workload(left, right):
    total = 0.0
    for index in range(len(left)):
        total += left[index] * right[index]
    return total
