import json


def workload(records):
    return '\n'.join(json.dumps(record, sort_keys=True) for record in records)
