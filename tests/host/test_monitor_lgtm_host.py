"""PR-M1 host floors: the live RAM and disk check for the local LGTM store.

`just accept` runs this on the clean-distro host only; CI never collects
`tests/host`, because the hosted runner is smaller than the registered
20 GB floors in `deploy/monitor/lgtm/parameters.json`.
"""

import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def test_host_meets_the_registered_ram_and_disk_floors() -> None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        pytest.skip("host RAM undeterminable without /proc/meminfo")
    total_kb = int(re.search(r"MemTotal:\s+(\d+)", meminfo.read_text()).group(1))  # type: ignore[union-attr]
    assert total_kb * 1024 / 1e9 > 20
    assert shutil.disk_usage(ROOT).free / 1e9 > 20
