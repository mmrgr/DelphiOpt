import json
import time
import tracemalloc

from baseline import workload

args = ([(str(i), i) for i in range(3000)], [str(i % 3000) for i in range(4000)])
tracemalloc.start()
started = time.perf_counter()
result = workload(*args)
runtime_ms = (time.perf_counter() - started) * 1000
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(json.dumps({"runtime_ms": runtime_ms, "memory_mb": peak / 1_048_576, "result_digest": hash(str(result))}))
