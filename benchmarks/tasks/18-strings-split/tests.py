from baseline import workload

assert workload('a b c', ['b', 'x']) == ['b']
print('tests passed')
