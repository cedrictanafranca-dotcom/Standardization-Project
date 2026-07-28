"""Smoke test for the corrections module.
Run: .venv/Scripts/python.exe test_corrections.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import corrections as cq

# load_demo_corrections returns 5 items
demo = cq.load_demo_corrections()
assert len(demo) == 5, len(demo)
assert all(c["status"] == "pending" for c in demo)
assert all(c["source"] == "demo" for c in demo)
print("load_demo_corrections: OK")

# make_correction builds a valid dict
c = cq.make_correction(
    field_key="positions_designations",
    field_display="Positions / Designations",
    raw_value="General Manager",
    original="Other / Unclassified",
    proposed="Executive Management",
    country="Argentina",
    submitted_by="Test",
)
assert c["status"] == "pending"
assert c["id"]
assert c["proposed"] == "Executive Management"
print("make_correction: OK")

# add_to_queue / deduplication
# Use a temp queue file to avoid touching real data
import json, tempfile, os
from unittest.mock import patch

tmp = Path(tempfile.mktemp(suffix=".json"))
with patch.object(cq, "QUEUE_FILE", tmp):
    added = cq.add_to_queue([c])
    assert added == 1, added
    added_again = cq.add_to_queue([c])  # duplicate — should be skipped
    assert added_again == 0, added_again
    queue = cq.load_queue()
    assert len(queue) == 1
    tmp.unlink()
print("add_to_queue dedup: OK")

# _norm
assert cq._norm("  General  Manager  ") == "General Manager"
assert cq._norm(None) == ""
print("_norm: OK")

print("\nAll checks passed.")
