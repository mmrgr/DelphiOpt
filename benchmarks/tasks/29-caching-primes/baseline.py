def is_prime(value):
    if value < 2:
        return False
    return all(value % divisor for divisor in range(2, int(value ** 0.5) + 1))

def workload(values):
    return [is_prime(value) for value in values]
