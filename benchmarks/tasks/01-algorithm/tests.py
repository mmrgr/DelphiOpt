from baseline import workload

assert workload([1, 2, 2, 4], [2, 4]) == 3
assert workload([], [1]) == 0
print('tests passed')
