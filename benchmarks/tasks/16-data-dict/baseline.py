def workload(records, keys):
    return [next((value for key, value in records if key == wanted), None) for wanted in keys]
