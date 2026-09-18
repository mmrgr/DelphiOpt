from threading import Event

def workload(values):
    return sum(1 for value in values if Event().is_set() or value >= 0)
