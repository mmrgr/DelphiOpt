import json
import time
import tracemalloc

from target import count_matches


def main() -> None:
    values = list(range(3500))
    wanted = list(range(1750))
    tracemalloc.start()
    started = time.perf_counter()
    answer = 0
    iterations = 5
    for _ in range(iterations):
        answer = count_matches(values, wanted)
    runtime_ms = (time.perf_counter() - started) * 1000 / iterations
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({"runtime_ms": runtime_ms, "memory_mb": peak / 1_048_576, "answer": answer, "workload": "held-out-demo"}))


if __name__ == "__main__":
    main()
