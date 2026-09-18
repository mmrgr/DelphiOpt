from __future__ import annotations

import json
from pathlib import Path

TASKS = {
    "01-algorithm": {
        "category": "algorithm",
        "title": "quadratic membership scan",
        "opportunity": "convert the lookup collection to a set before the loop",
        "code": "def workload(values, wanted):\n    return sum(1 for value in values if value in wanted)\n",
        "test": "assert workload([1, 2, 2, 4], [2, 4]) == 3\nassert workload([], [1]) == 0",
        "setup": "args = (list(range(4000)), list(range(2000)))",
    },
    "02-loops": {
        "category": "loops",
        "title": "loop-invariant recomputation",
        "opportunity": "hoist max(values) outside the comprehension",
        "code": "def workload(values):\n    return [value / max(values) for value in values]\n",
        "test": "assert workload([1, 2, 4]) == [0.25, 0.5, 1.0]",
        "setup": "args = (list(range(1, 2500)),)",
    },
    "03-data-structures": {
        "category": "data-structures",
        "title": "quadratic ordered deduplication",
        "opportunity": "track seen values in a set while preserving list order",
        "code": "def workload(values):\n    result = []\n    for value in values:\n        if value not in result:\n            result.append(value)\n    return result\n",
        "test": "assert workload([3, 1, 3, 2, 1]) == [3, 1, 2]",
        "setup": "args = (list(range(1200)) + list(range(1200)),)",
    },
    "04-strings": {
        "category": "string-processing",
        "title": "repeated immutable string concatenation",
        "opportunity": "collect fragments and join once",
        "code": "def workload(values):\n    result = ''\n    for value in values:\n        result += str(value) + ','\n    return result\n",
        "test": "assert workload([1, 2, 3]) == '1,2,3,'",
        "setup": "args = (list(range(10000)),)",
    },
    "05-numerical": {
        "category": "numerical-computing",
        "title": "indexed dot-product loop",
        "opportunity": "use zip or a vectorized backend to remove repeated indexing",
        "code": "def workload(left, right):\n    total = 0.0\n    for index in range(len(left)):\n        total += left[index] * right[index]\n    return total\n",
        "test": "assert workload([1.0, 2.0], [3.0, 4.0]) == 11.0",
        "setup": "args = ([float(i) for i in range(30000)], [0.5] * 30000)",
    },
    "06-memory": {
        "category": "memory-allocation",
        "title": "repeated list copying during flatten",
        "opportunity": "extend one list instead of allocating on every chunk",
        "code": "def workload(chunks):\n    result = []\n    for chunk in chunks:\n        result = result + chunk\n    return result\n",
        "test": "assert workload([[1, 2], [], [3]]) == [1, 2, 3]",
        "setup": "args = ([[value] * 10 for value in range(1200)],)",
    },
    "07-io": {
        "category": "io",
        "title": "many small in-memory writes",
        "opportunity": "join formatted lines before writing",
        "code": "from io import StringIO\n\n\ndef workload(lines):\n    output = StringIO()\n    for line in lines:\n        output.write(line)\n        output.write('\\n')\n    return output.getvalue()\n",
        "test": "assert workload(['a', 'b']) == 'a\\nb\\n'",
        "setup": "args = ([str(i) for i in range(30000)],)",
    },
    "08-serialization": {
        "category": "serialization",
        "title": "record-by-record JSON encoding",
        "opportunity": "batch serialization and avoid repeated encoder setup",
        "code": "import json\n\n\ndef workload(records):\n    return '\\n'.join(json.dumps(record, sort_keys=True) for record in records)\n",
        "test": "assert workload([{'b': 2, 'a': 1}]) == '{\"a\": 1, \"b\": 2}'",
        "setup": "args = ([{'id': i, 'value': str(i)} for i in range(5000)],)",
    },
    "09-concurrency": {
        "category": "concurrency",
        "title": "lock acquisition in every iteration",
        "opportunity": "aggregate locally and acquire the lock once",
        "code": "from threading import Lock\n\n\ndef workload(values):\n    lock = Lock()\n    total = 0\n    for value in values:\n        with lock:\n            total += value\n    return total\n",
        "test": "assert workload([1, 2, 3]) == 6",
        "setup": "args = (list(range(50000)),)",
    },
    "10-caching": {
        "category": "caching",
        "title": "repeated recursive subproblems",
        "opportunity": "memoize fibonacci subproblems",
        "code": "def workload(value):\n    if value < 2:\n        return value\n    return workload(value - 1) + workload(value - 2)\n",
        "test": "assert workload(0) == 0\nassert workload(10) == 55",
        "setup": "args = (28,)",
    },
}


def main() -> None:
    root = Path(__file__).parent / "tasks"
    for task_id, task in TASKS.items():
        directory = root / task_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "baseline.py").write_text(task["code"], encoding="utf-8")
        (directory / "tests.py").write_text(f"from baseline import workload\n\n{task['test']}\nprint('tests passed')\n", encoding="utf-8")
        benchmark = f"""import json
import time
import tracemalloc

from baseline import workload

{task['setup']}
tracemalloc.start()
started = time.perf_counter()
result = workload(*args)
runtime_ms = (time.perf_counter() - started) * 1000
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(json.dumps({{"runtime_ms": runtime_ms, "memory_mb": peak / 1_048_576, "result_digest": hash(str(result))}}))
"""
        (directory / "benchmark.py").write_text(benchmark, encoding="utf-8")
        metadata = {
            "id": task_id,
            "category": task["category"],
            "title": task["title"],
            "known_optimization_opportunity": task["opportunity"],
            "language": "python",
            "test_command": "python tests.py",
            "benchmark_command": "python benchmark.py",
            "expected_evidence": ["correctness", "warmup", "repeated runtime samples", "held-out input"],
        }
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
