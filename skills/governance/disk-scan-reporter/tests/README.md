# Tests

`test_disk_scan.py` covers classification, exclusions, link handling, depth,
file/time budgets, coverage states, record limits, path privacy, report
rendering, CLI failure status, error categories, allocated size, hardlink
de-duplication, JSON roundtrips, unknown schema rejection, and the no-deletion
contract.

`test_audit_guard.py` covers destructive API detection, allowed write roots,
junction escape rejection, and shallow snapshot comparison.

Run with `python -m unittest discover tests`.
