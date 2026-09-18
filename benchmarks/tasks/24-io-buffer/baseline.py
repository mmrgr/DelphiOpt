from io import StringIO

def workload(lines):
    stream = StringIO('\n'.join(lines))
    return [line.upper() for _ in lines for line in [stream.readline().rstrip('\n')]]
