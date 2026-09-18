from baseline import workload

assert workload([('a', 1), ('b', 2)], ['b', 'x']) == [2, None]
print('tests passed')
