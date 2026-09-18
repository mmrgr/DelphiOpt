from threading import Lock

def workload(values):
    lock = Lock()
    total = 0
    for value in values:
        with lock:
            total += value * 2
    return total
