import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_usecases import audit  # noqa: E402

CATALOG = Path(__file__).resolve().parents[1] / "usecases" / "catalog.yaml"


def test_catalog_passes_audit():
    errors, stats = audit(CATALOG)
    assert errors == [], errors
    assert stats["entries"] >= 100
