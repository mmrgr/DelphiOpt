def workload(lines):
    total = 0
    for line in lines:
        total += int(line.split(',')[1])
    return total
