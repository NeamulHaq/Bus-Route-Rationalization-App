# ============================================================
# analysis.py
# BUS ROUTE OVERLAP & RATIONALIZATION TOOL - CORE LOGIC
# ============================================================
#
# All geometry / overlap / scoring logic from the original
# Jupyter notebook lives here, refactored to be Streamlit-free
# (pure functions that take data in and return data out) so it
# can be unit-tested and reused independently of the UI layer.
#
# ============================================================

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

# ============================================================
# CONSTANTS
# ============================================================

ANALYSIS_CRS = "EPSG:32646"   # UTM 46N - metric CRS used for all length/overlap math
WEB_CRS = "EPSG:4326"         # WGS84 - used for maps and lat/lon output


# ============================================================
# DATA LOADING
# ============================================================

def load_network_data(data_dir: str | Path):
    """
    Load the existing route/stop/corridor network + optional
    pre-computed overlap matrix from a data directory.

    Expects, inside data_dir:
        Official_Bus_Routes_98.shp
        Official_Bus_Stops_98.shp
        Bus_Corridors.shp
        98_Overlap_Matrix.xlsx   (optional)

    Returns
    -------
    routes, stops, corridors : GeoDataFrame (in ANALYSIS_CRS)
    overlap_matrix : DataFrame | None
    """
    data_dir = Path(data_dir)

    routes_path = data_dir / "Official_Bus_Routes_98.shp"
    stops_path = data_dir / "Official_Bus_Stops_98.shp"
    corridors_path = data_dir / "Bus_Corridors.shp"
    matrix_path = data_dir / "98_Overlap_Matrix.xlsx"

    missing = [p.name for p in (routes_path, stops_path, corridors_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing required file(s) in {data_dir}: {', '.join(missing)}"
        )

    routes = gpd.read_file(routes_path)
    stops = gpd.read_file(stops_path)
    corridors = gpd.read_file(corridors_path)

    try:
        overlap_matrix = pd.read_excel(matrix_path, index_col=0)
    except Exception:
        overlap_matrix = None

    routes = routes.to_crs(ANALYSIS_CRS)
    stops = stops.to_crs(ANALYSIS_CRS)
    corridors = corridors.to_crs(ANALYSIS_CRS)

    routes = routes[routes.geometry.notna()].copy()
    stops = stops[stops.geometry.notna()].copy()
    corridors = corridors[corridors.geometry.notna()].copy()

    routes["GIS_Length_km"] = routes.geometry.length / 1000

    return routes, stops, corridors, overlap_matrix


def get_route_ids(routes: gpd.GeoDataFrame) -> list[str]:
    return sorted(routes["Route_ID"].astype(str).str.strip().unique().tolist())


# ============================================================
# GEOMETRY HELPERS
# ============================================================

def normalize_line_geometry(gdf: gpd.GeoDataFrame):
    """Collapse a GeoDataFrame of line features into one LineString."""
    if gdf is None or len(gdf) == 0:
        return None

    gdf = gdf[gdf.geometry.notna()]
    if len(gdf) == 0:
        return None

    geometry = unary_union(gdf.geometry.tolist())

    if geometry.geom_type == "LineString":
        return geometry

    if geometry.geom_type == "MultiLineString":
        parts = list(geometry.geoms)
        if len(parts) == 1:
            return parts[0]

        merged = unary_union(parts)
        if merged.geom_type == "LineString":
            return merged

        # Disconnected parts: fall back to the longest piece
        return max(parts, key=lambda x: x.length)

    return None


def calculate_overlap(proposed_geometry, existing_geometry, tolerance):
    """Exact + buffered ("near") overlap length in km between two lines."""
    exact_geom = proposed_geometry.intersection(existing_geometry)
    exact_km = 0 if exact_geom.is_empty else exact_geom.length / 1000

    existing_buffer = existing_geometry.buffer(tolerance)
    near_geom = proposed_geometry.intersection(existing_buffer)
    near_km = 0 if near_geom.is_empty else near_geom.length / 1000

    return exact_geom, exact_km, near_geom, near_km


# ============================================================
# ROUTE-VS-NETWORK ANALYSIS
# ============================================================

def analyze_overlapping_routes(
    routes: gpd.GeoDataFrame,
    proposed_geometry,
    tolerance: float,
    exclude_route_id: Optional[str] = None,
):
    proposed_length_km = proposed_geometry.length / 1000

    records = []
    overlap_geometries = []

    for _, route in routes.iterrows():
        route_id = str(route["Route_ID"])

        if exclude_route_id is not None and route_id == str(exclude_route_id):
            continue

        exact_geom, exact_km, near_geom, near_km = calculate_overlap(
            proposed_geometry, route.geometry, tolerance
        )

        percentage = (near_km / proposed_length_km * 100) if proposed_length_km > 0 else 0

        if percentage >= 30:
            severity = "HIGH"
        elif percentage >= 15:
            severity = "MEDIUM"
        elif percentage >= 5:
            severity = "LOW"
        else:
            severity = "MINIMAL"

        records.append(
            {
                "Route_ID": route_id,
                "Operator": str(route.get("Operator", "")),
                "Overlap_km": near_km,
                "Exact_km": exact_km,
                "Overlap_%": percentage,
                "Severity": severity,
            }
        )

        if near_km > 0:
            overlap_geometries.append({"Route_ID": route_id, "geometry": near_geom})

    df = pd.DataFrame(records)

    if len(df):
        df = (
            df[df["Overlap_km"] >= 0.05]
            .sort_values("Overlap_km", ascending=False)
            .reset_index(drop=True)
        )

    return df, overlap_geometries


def analyze_stops(stops: gpd.GeoDataFrame, proposed_geometry, tolerance: float):
    buffer = proposed_geometry.buffer(tolerance)
    return stops[stops.geometry.intersects(buffer)].copy()


def analyze_corridors(corridors: gpd.GeoDataFrame, proposed_geometry):
    records = []

    for _, corridor in corridors.iterrows():
        intersection = proposed_geometry.intersection(corridor.geometry)
        if intersection.is_empty:
            continue

        records.append(
            {
                "Corridor": str(corridor.get("Name", "")),
                "Overlap_km": intersection.length / 1000,
            }
        )

    if not records:
        return pd.DataFrame(columns=["Corridor", "Overlap_km"])

    return (
        pd.DataFrame(records)
        .sort_values("Overlap_km", ascending=False)
        .reset_index(drop=True)
    )


# ============================================================
# CONFLICT SCORE + RECOMMENDATION
# ============================================================

def calculate_conflict_score(
    proposed_length_km, overlapping_routes, overlap_km, affected_stops, corridor_overlap_km
):
    if proposed_length_km <= 0:
        return 0, "LOW"

    overlap_percent = overlap_km / proposed_length_km * 100

    network_score = min(overlap_percent, 100) * 0.55
    route_score = min(overlapping_routes * 10, 100) * 0.25
    stop_score = min(affected_stops * 2, 100) * 0.10
    corridor_score = min(corridor_overlap_km * 5, 100) * 0.10

    score = round(min(network_score + route_score + stop_score + corridor_score, 100), 0)

    if score >= 75:
        level = "VERY HIGH"
    elif score >= 55:
        level = "HIGH"
    elif score >= 30:
        level = "MEDIUM"
    else:
        level = "LOW"

    return score, level


def generate_recommendation(score, level, overlap_percent, top_route, corridor_count):
    if level == "VERY HIGH":
        text = (
            "\u26a0 Very high network duplication detected. "
            "Strongly consider revising the proposed route to avoid parallel service."
        )
    elif level == "HIGH":
        text = (
            "\u26a0 High corridor overlap detected. "
            "Consider modifying the proposed route to reduce duplication with existing services."
        )
    elif level == "MEDIUM":
        text = (
            "\u25cf Moderate overlap detected. "
            "Review the overlapping corridors and existing operators before approval."
        )
    else:
        text = (
            "\u2713 Low network overlap detected. "
            "The proposed route has relatively limited duplication with the existing network."
        )

    if top_route:
        text += f" Highest overlap is with route {top_route}."

    if corridor_count > 0:
        text += f" The proposed route intersects {corridor_count} major corridor(s)."

    return text


# ============================================================
# COMPLETE SINGLE-ROUTE ANALYSIS
# ============================================================

def run_analysis(
    routes: gpd.GeoDataFrame,
    stops: gpd.GeoDataFrame,
    corridors: gpd.GeoDataFrame,
    proposed_gdf: gpd.GeoDataFrame,
    tolerance: float,
    route_id: str,
    origin: str,
    destination: str,
    exclude_route_id: Optional[str] = None,
):
    proposed_geometry = proposed_gdf.geometry.iloc[0]
    proposed_length_km = proposed_geometry.length / 1000

    route_results, overlap_geometries = analyze_overlapping_routes(
        routes, proposed_geometry, tolerance, exclude_route_id=exclude_route_id
    )

    affected_stops = analyze_stops(stops, proposed_geometry, tolerance)
    corridor_results = analyze_corridors(corridors, proposed_geometry)

    if len(route_results):
        near_overlap_km = route_results["Overlap_km"].sum()
        exact_overlap_km = route_results["Exact_km"].sum()
    else:
        near_overlap_km = 0
        exact_overlap_km = 0

    near_overlap_km = min(near_overlap_km, proposed_length_km)
    exact_overlap_km = min(exact_overlap_km, proposed_length_km)

    overlap_percent = (near_overlap_km / proposed_length_km * 100) if proposed_length_km > 0 else 0

    score, level = calculate_conflict_score(
        proposed_length_km,
        len(route_results),
        near_overlap_km,
        len(affected_stops),
        corridor_results["Overlap_km"].sum() if len(corridor_results) else 0,
    )

    top_route = route_results.iloc[0]["Route_ID"] if len(route_results) else None

    recommendation = generate_recommendation(
        score, level, overlap_percent, top_route, len(corridor_results)
    )

    summary = {
        "Route": route_id,
        "Origin": origin,
        "Destination": destination,
        "Length_km": proposed_length_km,
        "Exact_Overlap_km": exact_overlap_km,
        "Near_Overlap_km": near_overlap_km,
        "Overlapping_Routes": len(route_results),
        "Affected_Stops": len(affected_stops),
        "Affected_Corridors": len(corridor_results),
        "Conflict_Score": score,
        "Conflict_Level": level,
    }

    return {
        "summary": summary,
        "route_results": route_results,
        "affected_stops": affected_stops,
        "corridor_results": corridor_results,
        "overlap_geometries": overlap_geometries,
        "recommendation": recommendation,
    }


# ============================================================
# NETWORK-WIDE N x N SELF-OVERLAP MATRIX
# ============================================================

def compute_full_overlap_matrix(
    routes: gpd.GeoDataFrame,
    tolerance: float,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    min_overlap_km: float = 0.05,
):
    ids = routes["Route_ID"].astype(str).tolist()
    geoms = routes.geometry.tolist()
    ops = (
        routes["Operator"].astype(str).tolist()
        if "Operator" in routes.columns
        else [""] * len(routes)
    )

    n = len(ids)
    matrix = pd.DataFrame(0.0, index=ids, columns=ids)
    pairs = []

    total_pairs = n * (n - 1) // 2
    done = 0

    for i in range(n):
        geom_i = geoms[i]
        len_i = 0 if geom_i is None or geom_i.is_empty else geom_i.length / 1000

        for j in range(i + 1, n):
            geom_j = geoms[j]

            if geom_i is None or geom_j is None or geom_i.is_empty or geom_j.is_empty:
                done += 1
                continue

            _, exact_km, _, near_km = calculate_overlap(geom_i, geom_j, tolerance)

            len_j = geom_j.length / 1000
            shorter = min(len_i, len_j)
            pct = (near_km / shorter * 100) if shorter > 0 else 0

            matrix.iloc[i, j] = pct
            matrix.iloc[j, i] = pct

            if near_km >= min_overlap_km:
                pairs.append(
                    {
                        "Route_A": ids[i],
                        "Operator_A": ops[i],
                        "Route_B": ids[j],
                        "Operator_B": ops[j],
                        "Overlap_km": near_km,
                        "Exact_km": exact_km,
                        "Overlap_%": pct,
                    }
                )

            done += 1

            if progress_callback is not None and (done % 100 == 0 or done == total_pairs):
                progress_callback(done, total_pairs)

    if progress_callback is not None:
        progress_callback(total_pairs, total_pairs)

    pairs_df = pd.DataFrame(pairs)

    if len(pairs_df):
        pairs_df = pairs_df.sort_values("Overlap_km", ascending=False).reset_index(drop=True)

    return matrix, pairs_df


# ============================================================
# ROUTE FILE READING (uploads)
# ============================================================

def read_route_file(uploaded_file, route_id: str, origin: str, destination: str):
    """
    Build a proposed-route GeoDataFrame from an uploaded file.

    `uploaded_file` is a Streamlit UploadedFile (has .name and
    .getvalue() / .read()), matching the same accepted formats as
    the original tool: .geojson / .json, .zip (shapefile bundle),
    .gpkg.
    """
    filename = uploaded_file.name
    content = uploaded_file.getvalue()
    suffix = Path(filename).suffix.lower()

    if suffix in (".geojson", ".json"):
        gdf = gpd.read_file(io.BytesIO(content))

    elif suffix == ".zip":
        temp_dir = tempfile.mkdtemp()
        zip_path = Path(temp_dir) / filename
        zip_path.write_bytes(content)

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        shp_files = list(Path(temp_dir).glob("*.shp"))
        if not shp_files:
            raise ValueError("No .shp file found inside ZIP.")

        gdf = gpd.read_file(shp_files[0])

    elif suffix == ".gpkg":
        temp_dir = tempfile.mkdtemp()
        gpkg_path = Path(temp_dir) / filename
        gpkg_path.write_bytes(content)
        gdf = gpd.read_file(gpkg_path)

    else:
        raise ValueError("Please upload GeoJSON, GeoPackage, or a ZIP containing a Shapefile.")

    if gdf.crs is None:
        raise ValueError("Uploaded route has no CRS.")

    gdf = gdf.to_crs(ANALYSIS_CRS)
    gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()

    if len(gdf) == 0:
        raise ValueError("Uploaded file does not contain a line route.")

    geometry = normalize_line_geometry(gdf)
    if geometry is None:
        raise ValueError("Unable to create a valid route LineString.")

    return gpd.GeoDataFrame(
        {"Route_ID": [route_id], "Origin": [origin], "Destination": [destination]},
        geometry=[geometry],
        crs=ANALYSIS_CRS,
    )


def route_from_drawn_geojson(drawn_geojson: dict, route_id: str, origin: str, destination: str):
    """
    Build a proposed-route GeoDataFrame from a single drawn GeoJSON
    feature (as returned by streamlit-folium's Draw control, in
    WEB_CRS / EPSG:4326).
    """
    geometry = shape(drawn_geojson["geometry"])

    return gpd.GeoDataFrame(
        {"Route_ID": [route_id], "Origin": [origin], "Destination": [destination]},
        geometry=[geometry],
        crs=WEB_CRS,
    ).to_crs(ANALYSIS_CRS)


def route_from_existing(routes: gpd.GeoDataFrame, selected_id: str):
    """Build a 'proposed route' GeoDataFrame from an existing route ID (Tab 2)."""
    subset = routes[routes["Route_ID"].astype(str).str.strip() == selected_id]

    if len(subset) == 0:
        raise ValueError(f"Route {selected_id} not found.")

    geometry = normalize_line_geometry(subset)
    if geometry is None:
        raise ValueError(f"Could not build a valid geometry for route {selected_id}.")

    origin_val = subset.iloc[0]["Origin"] if "Origin" in subset.columns else ""
    dest_val = subset.iloc[0]["Destination"] if "Destination" in subset.columns else ""

    gdf = gpd.GeoDataFrame(
        {"Route_ID": [selected_id], "Origin": [origin_val], "Destination": [dest_val]},
        geometry=[geometry],
        crs=ANALYSIS_CRS,
    )

    return gdf, str(origin_val), str(dest_val)


# ============================================================
# AFFECTED STOPS TABLE (unique name / lat / lon, WGS84)
# ============================================================

def build_affected_stops_table(affected_stops: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Reduce an affected-stops GeoDataFrame to the unique
    Name / Latitude / Longitude table (EPSG:4326), matching the
    corrected v2 behaviour from the original notebook.
    """
    if affected_stops is None or len(affected_stops) == 0:
        return pd.DataFrame(columns=["Name", "Latitude", "Longitude"])

    stops_web = affected_stops.to_crs(WEB_CRS).copy()
    stops_web["Latitude"] = stops_web.geometry.y.round(6)
    stops_web["Longitude"] = stops_web.geometry.x.round(6)

    name_col = "Name" if "Name" in stops_web.columns else stops_web.columns[0]

    table = stops_web[[name_col, "Latitude", "Longitude"]].rename(columns={name_col: "Name"})

    table = (
        table.drop_duplicates(subset=["Name"], keep="first")
        .sort_values("Name")
        .reset_index(drop=True)
    )

    return table


# ============================================================
# EXCEL EXPORT (single-route analysis)
# ============================================================

def export_result_to_excel(result: dict) -> bytes:
    """Serialize a run_analysis() result dict to an in-memory .xlsx workbook."""
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([result["summary"]]).to_excel(writer, sheet_name="Summary", index=False)

        result["route_results"].to_excel(writer, sheet_name="Overlapping_Routes", index=False)

        build_affected_stops_table(result["affected_stops"]).to_excel(
            writer, sheet_name="Affected_Stops", index=False
        )

        result["corridor_results"].to_excel(writer, sheet_name="Corridors", index=False)

    buffer.seek(0)
    return buffer.getvalue()


def export_matrix_to_excel(matrix: pd.DataFrame, pairs_df: pd.DataFrame) -> bytes:
    """Serialize the full N x N overlap matrix + top-pairs table to .xlsx bytes."""
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrix.to_excel(writer, sheet_name="Overlap_Matrix_pct")
        pairs_df.to_excel(writer, sheet_name="Top_Overlapping_Pairs", index=False)

    buffer.seek(0)
    return buffer.getvalue()
