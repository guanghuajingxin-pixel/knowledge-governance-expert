import sys
from pathlib import Path

# Make kb_common importable when running pytest from services/kb-common/
# against tests at the repo root.
_repo_root = Path(__file__).resolve().parent.parent
_kb_common = _repo_root / "services" / "kb-common"
if str(_kb_common) not in sys.path:
    sys.path.insert(0, str(_kb_common))
