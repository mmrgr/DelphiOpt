from baseline import workload

assert workload([('a', 1), ('b', 2)]) == {'a': 1, 'b': 2}
print('tests passed')
