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

# The original ten fixtures remain the readable core examples. These additional
# near-real workloads make the suite large enough for repeated method-level
# comparisons without pretending that synthetic tasks are production projects.
EXTRA_TASKS = {
    "11-algorithm-window": {
        "category": "algorithm",
        "title": "repeated window maximum",
        "opportunity": "maintain a rolling maximum instead of rescanning each window",
        "code": "def workload(values, width):\n    return [max(values[i:i + width]) for i in range(len(values) - width + 1)]\n",
        "test": "assert workload([1, 3, 2, 5], 2) == [3, 3, 5]",
        "setup": "args = (list(range(1800)), 40)",
    },
    "12-algorithm-minimum": {
        "category": "algorithm",
        "title": "repeated prefix minimum",
        "opportunity": "carry the running minimum through the prefix scan",
        "code": "def workload(values):\n    return [min(values[:index]) for index in range(1, len(values) + 1)]\n",
        "test": "assert workload([3, 1, 2]) == [3, 1, 1]",
        "setup": "args = (list(range(1800, 0, -1)),)",
    },
    "13-algorithm-sort": {
        "category": "algorithm",
        "title": "repeated sort for first element",
        "opportunity": "sort once before repeated reads",
        "code": "def workload(values, count):\n    return [sorted(values)[0] for _ in range(count)]\n",
        "test": "assert workload([3, 1, 2], 2) == [1, 1]",
        "setup": "args = (list(range(1500, 0, -1)), 80)",
    },
    "14-loops-enumerate": {
        "category": "loops",
        "title": "manual index accumulation",
        "opportunity": "iterate directly over values and avoid repeated indexing",
        "code": "def workload(values):\n    result = []\n    index = 0\n    while index < len(values):\n        result.append((index, values[index]))\n        index += 1\n    return result\n",
        "test": "assert workload(['a', 'b']) == [(0, 'a'), (1, 'b')]",
        "setup": "args = ([str(i) for i in range(20000)],)",
    },
    "15-loops-filter": {
        "category": "loops",
        "title": "branch-heavy filter loop",
        "opportunity": "use a compact predicate while preserving the filter semantics",
        "code": "def workload(values):\n    result = []\n    for value in values:\n        if value % 2 == 0:\n            result.append(value)\n    return result\n",
        "test": "assert workload([1, 2, 4]) == [2, 4]",
        "setup": "args = (list(range(50000)),)",
    },
    "16-data-dict": {
        "category": "data-structures",
        "title": "linear key lookup",
        "opportunity": "materialize a dictionary for repeated key membership",
        "code": "def workload(records, keys):\n    return [next((value for key, value in records if key == wanted), None) for wanted in keys]\n",
        "test": "assert workload([('a', 1), ('b', 2)], ['b', 'x']) == [2, None]",
        "setup": "args = ([(str(i), i) for i in range(3000)], [str(i % 3000) for i in range(4000)])",
    },
    "17-data-tuple": {
        "category": "data-structures",
        "title": "repeated tuple membership",
        "opportunity": "use a set for immutable membership candidates",
        "code": "def workload(values, candidates):\n    return [value for value in values if value in tuple(candidates)]\n",
        "test": "assert workload([1, 2, 3], [2, 3]) == [2, 3]",
        "setup": "args = (list(range(5000)), list(range(2500)))",
    },
    "18-strings-split": {
        "category": "string-processing",
        "title": "repeated line splitting",
        "opportunity": "split the source text once and reuse the tokens",
        "code": "def workload(text, words):\n    return [word for word in words if word in text.split()]\n",
        "test": "assert workload('a b c', ['b', 'x']) == ['b']",
        "setup": "args = (' '.join(str(i) for i in range(4000)), [str(i) for i in range(2500)])",
    },
    "19-strings-format": {
        "category": "string-processing",
        "title": "repeated format parsing",
        "opportunity": "precompute stable formatting work outside the loop",
        "code": "def workload(values, prefix):\n    return [prefix + ':' + str(value) for value in values]\n",
        "test": "assert workload([1, 2], 'id') == ['id:1', 'id:2']",
        "setup": "args = (list(range(30000)), 'item')",
    },
    "20-numerical-sum": {
        "category": "numerical-computing",
        "title": "manual numeric sum",
        "opportunity": "use the built-in numeric reduction",
        "code": "def workload(values):\n    total = 0\n    for value in values:\n        total += value\n    return total\n",
        "test": "assert workload([1, 2, 3]) == 6",
        "setup": "args = (list(range(100000)),)",
    },
    "21-numerical-abs": {
        "category": "numerical-computing",
        "title": "manual absolute values",
        "opportunity": "use the built-in absolute-value operation directly",
        "code": "def workload(values):\n    result = []\n    for value in values:\n        result.append(value if value >= 0 else -value)\n    return result\n",
        "test": "assert workload([-2, 1]) == [2, 1]",
        "setup": "args = ([(-1) ** i * i for i in range(50000)],)",
    },
    "22-memory-comprehension": {
        "category": "memory-allocation",
        "title": "unnecessary intermediate list",
        "opportunity": "stream the reduction instead of retaining an intermediate list",
        "code": "def workload(values):\n    squares = [value * value for value in values]\n    return sum(squares)\n",
        "test": "assert workload([1, 2, 3]) == 14",
        "setup": "args = (list(range(70000)),)",
    },
    "23-memory-dict-copy": {
        "category": "memory-allocation",
        "title": "repeated dictionary copy",
        "opportunity": "mutate one accumulator rather than copying on every item",
        "code": "def workload(values):\n    result = {}\n    for key, value in values:\n        result = {**result, key: value}\n    return result\n",
        "test": "assert workload([('a', 1), ('b', 2)]) == {'a': 1, 'b': 2}",
        "setup": "args = ([(str(i), i) for i in range(1800)],)",
    },
    "24-io-buffer": {
        "category": "io",
        "title": "repeated buffer reads",
        "opportunity": "read the buffer once and process the resulting lines",
        "code": "from io import StringIO\n\ndef workload(lines):\n    stream = StringIO('\\n'.join(lines))\n    return [line.upper() for _ in lines for line in [stream.readline().rstrip('\\n')]]\n",
        "test": "assert workload(['a', 'b']) == ['A', 'B']",
        "setup": "args = ([str(i) for i in range(20000)],)",
    },
    "25-io-parse": {
        "category": "io",
        "title": "repeated record parsing",
        "opportunity": "parse delimited input in one pass with local bindings",
        "code": "def workload(lines):\n    total = 0\n    for line in lines:\n        total += int(line.split(',')[1])\n    return total\n",
        "test": "assert workload(['a,2', 'b,3']) == 5",
        "setup": "args = ([f'item,{i}' for i in range(30000)],)",
    },
    "26-serialization-batch": {
        "category": "serialization",
        "title": "repeated JSON encoder setup",
        "opportunity": "reuse serialization options and batch the workload",
        "code": "import json\n\ndef workload(records):\n    return [json.dumps(record, separators=(',', ':')) for record in records]\n",
        "test": "assert workload([{'a': 1}]) == ['{\"a\":1}']",
        "setup": "args = ([{'id': i, 'value': i % 7} for i in range(9000)],)",
    },
    "27-concurrency-lock": {
        "category": "concurrency",
        "title": "lock around immutable reads",
        "opportunity": "move invariant reads outside the critical section",
        "code": "from threading import Lock\n\ndef workload(values):\n    lock = Lock()\n    total = 0\n    for value in values:\n        with lock:\n            total += value * 2\n    return total\n",
        "test": "assert workload([1, 2, 3]) == 12",
        "setup": "args = (list(range(40000)),)",
    },
    "28-concurrency-events": {
        "category": "concurrency",
        "title": "repeated event allocation",
        "opportunity": "reuse synchronization state for the batch operation",
        "code": "from threading import Event\n\ndef workload(values):\n    return sum(1 for value in values if Event().is_set() or value >= 0)\n",
        "test": "assert workload([1, 2, 3]) == 3",
        "setup": "args = (list(range(12000)),)",
    },
    "29-caching-primes": {
        "category": "caching",
        "title": "repeated divisor checks",
        "opportunity": "cache previously classified values and avoid repeated divisor work",
        "code": "def is_prime(value):\n    if value < 2:\n        return False\n    return all(value % divisor for divisor in range(2, int(value ** 0.5) + 1))\n\ndef workload(values):\n    return [is_prime(value) for value in values]\n",
        "test": "assert workload([2, 4, 5]) == [True, False, True]",
        "setup": "args = ([value % 2000 for value in range(14000)],)",
    },
    "30-caching-regex": {
        "category": "caching",
        "title": "repeated pattern compilation",
        "opportunity": "compile the stable pattern once before scanning records",
        "code": "import re\n\ndef workload(values):\n    return [bool(re.compile(r'^[a-z]+$').match(value)) for value in values]\n",
        "test": "assert workload(['abc', '123']) == [True, False]",
        "setup": "args = ([('item' + str(i)) for i in range(18000)],)",
    },
}

ALL_TASKS = {**TASKS, **EXTRA_TASKS}


def main() -> None:
    root = Path(__file__).parent / "tasks"
    for task_id, task in ALL_TASKS.items():
        directory = root / task_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "baseline.py").write_text(task["code"], encoding="utf-8")
        (directory / "tests.py").write_text(f"from baseline import workload\n\n{task['test']}\nprint('tests passed')\n", encoding="utf-8")
        benchmark = f"""import json
import time
import tracemalloc

from baseline import workload

{task["setup"]}
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
