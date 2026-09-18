from io import StringIO


def workload(lines):
    output = StringIO()
    for line in lines:
        output.write(line)
        output.write('\n')
    return output.getvalue()
