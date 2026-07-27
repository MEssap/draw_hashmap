"""draw-hashmap: Draw polygons on a map and compute intersecting geohash cells."""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from shapely.geometry import Polygon, box
import geohash

app = FastAPI(title="Draw Hashmap")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ComputeRequest(BaseModel):
    polygons: list[list[list[float]]] = Field(
        description="List of polygons. Each polygon is a list of [lat, lon] vertices."
    )
    precision: int = Field(
        default=6,
        ge=1,
        le=12,
        description="Geohash precision level (6 or 7 recommended for map use).",
    )


class CellInfo(BaseModel):
    geohash: str
    sw: list[float]
    ne: list[float]
    center: list[float]


class ComputeResponse(BaseModel):
    cells: list[CellInfo]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_CANDIDATE_CELLS = 500_000

# ---------------------------------------------------------------------------
# Geohash helpers
# ---------------------------------------------------------------------------


def _get_cells_in_bbox(
    min_lat: float, min_lon: float,
    max_lat: float, max_lon: float,
    precision: int,
) -> set[str]:
    """Return every geohash cell whose bbox overlaps the given lat/lon window.

    Uses two offset sweeps at full cell-dimension step so that every cell
    intersecting the window is found regardless of grid alignment.
    """
    # Reference cell dimensions (constant at a given precision).
    sample = geohash.encode(min_lat, min_lon, precision)
    _, _, lat_err, lon_err = geohash.decode(sample, delta=True)

    cell_h = lat_err * 2   # full cell height  (≈ 0.0055° at precision 6)
    cell_w = lon_err * 2   # full cell width   (≈ 0.0110° at precision 6)

    # Grow the search window by one full cell on each side.
    lat0 = min_lat - cell_h
    lat1 = max_lat + cell_h
    lon0 = min_lon - cell_w
    lon1 = max_lon + cell_w

    cells: set[str] = set()

    def _sweep(lo: float, la0: float) -> None:
        lat = la0
        while lat <= lat1:
            lon = lo
            while lon <= lon1:
                cells.add(geohash.encode(lat, lon, precision))
                lon += cell_w
            lat += cell_h

    _sweep(lon0, lat0)                       # sweep 1
    _sweep(lon0 + cell_w * 0.5, lat0 + cell_h * 0.5)  # sweep 2 — offset

    return cells


def _build_polygons(raw: list[list[list[float]]]) -> list[Polygon]:
    """Convert [[[lat,lon], …], …] → list of valid shapely Polygons."""
    polys: list[Polygon] = []
    for coords in raw:
        if len(coords) < 3:
            continue
        # Ensure the ring is closed.
        if coords[0] != coords[-1]:
            coords = coords + [coords[0]]
        # shapely expects (lon, lat).
        poly = Polygon([(pt[1], pt[0]) for pt in coords])
        if not poly.is_valid:
            poly = poly.buffer(0)  # repair self-intersections / rings
        if not poly.is_empty:
            polys.append(poly)
    return polys


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.post("/api/compute", response_model=ComputeResponse)
def compute(request: ComputeRequest) -> ComputeResponse:
    """Accept one or more polygons; return every intersecting geohash cell."""
    if not request.polygons:
        return ComputeResponse(cells=[])

    shapely_polys = _build_polygons(request.polygons)
    if not shapely_polys:
        return ComputeResponse(cells=[])

    precision = request.precision

    # Overall bounding box (lon, lat) order from shapely.
    all_bounds = [p.bounds for p in shapely_polys]
    min_lon = min(b[0] for b in all_bounds)
    min_lat = min(b[1] for b in all_bounds)
    max_lon = max(b[2] for b in all_bounds)
    max_lat = max(b[3] for b in all_bounds)

    candidates = _get_cells_in_bbox(min_lat, min_lon, max_lat, max_lon, precision)
    if len(candidates) > MAX_CANDIDATE_CELLS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Area too large: {len(candidates):,} candidate cells "
                f"(max {MAX_CANDIDATE_CELLS:,}).  Draw smaller polygons."
            ),
        )

    # Keep only cells that intersect *any* drawn polygon.
    result: list[CellInfo] = []
    for gh in sorted(candidates):
        c_lat, c_lon, lat_err, lon_err = geohash.decode(gh, delta=True)
        cell_box = box(
            c_lon - lon_err, c_lat - lat_err,
            c_lon + lon_err, c_lat + lat_err,
        )
        if any(p.intersects(cell_box) for p in shapely_polys):
            result.append(
                CellInfo(
                    geohash=gh,
                    sw=[c_lat - lat_err, c_lon - lon_err],
                    ne=[c_lat + lat_err, c_lon + lat_err],
                    center=[c_lat, c_lon],
                )
            )

    return ComputeResponse(cells=result)


# ---------------------------------------------------------------------------
# Static files & entry redirect
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
