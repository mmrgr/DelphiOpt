import json

def workload(records):
    return [json.dumps(record, separators=(',', ':')) for record in records]
