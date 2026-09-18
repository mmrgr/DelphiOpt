#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parent
target = root / (sys.argv[1] if len(sys.argv) > 1 else "MODIFIED_FILE.txt")
shutil.copy2(root / "ORIGINAL_FILE.txt", target)
print(f"rollback: restored {target.name}")
