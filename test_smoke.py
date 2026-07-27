"""Quick smoke test for the /api/compute endpoint — both geohash6 and 7."""
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)

for prec in [6, 7]:
    resp = client.post(
        "/api/compute",
        json={
            "precision": prec,
            "polygons": [
                [[39.910, 116.385], [39.910, 116.395], [39.918, 116.395], [39.918, 116.385]],
                [[39.922, 116.400], [39.922, 116.408], [39.928, 116.408], [39.928, 116.400]],
            ],
        },
    )
    data = resp.json()
    print(f"--- geohash{prec} ---")
    print(f"  Status: {resp.status_code}")
    print(f"  Total cells: {len(data['cells'])}")
    for c in data["cells"][:6]:
        print(f"    {c['geohash']}  center={c['center']}")
    if len(data["cells"]) > 6:
        print(f"    ... ({len(data['cells']) - 6} more)")
    print()
