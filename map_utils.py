# ============================================================
# map_utils.py
# FOLIUM MAP BUILDERS FOR THE STREAMLIT APP
# ============================================================

import geopandas as gpd
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl

from analysis import ANALYSIS_CRS, WEB_CRS

MAP_LEGEND_HTML = """
<div style="
    position: fixed;
    bottom: 25px;
    left: 25px;
    width: 245px;
    z-index: 9999;
    background: white;
    border: 2px solid #555;
    border-radius: 6px;
    padding: 12px;
    font-size: 13px;
    box-shadow: 2px 2px 8px rgba(0,0,0,.25);
">
<b>MAP LEGEND</b><hr>
<span style="color:#2C7BE5;font-size:20px">&#9473;&#9473;</span> Existing Routes<br>
<span style="color:#00A65A;font-size:20px">&#9473;&#9473;</span> Proposed / Selected Route<br>
<span style="color:#E74C3C;font-size:20px">&#9473;&#9473;</span> Overlap Segments<br>
<span style="color:#F39C12;font-size:20px">&#9473;&#9473;</span> Main Corridors<br>
<span style="color:#8E44AD;font-size:18px">&#9679;</span> Bus Stops
</div>
"""


def build_results_map(
    routes: gpd.GeoDataFrame,
    stops: gpd.GeoDataFrame,
    corridors: gpd.GeoDataFrame,
    proposed_gdf: gpd.GeoDataFrame,
    result: dict,
    tolerance: float,
) -> folium.Map:
    """Recreates the original build_map() function as a standalone helper."""

    routes_web = routes.to_crs(WEB_CRS)
    corridors_web = corridors.to_crs(WEB_CRS)
    proposed_web = proposed_gdf.to_crs(WEB_CRS)

    center = proposed_web.geometry.iloc[0].centroid

    m = folium.Map(location=[center.y, center.x], zoom_start=11, tiles=None)

    folium.TileLayer("CartoDB positron", name="Light Basemap").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    folium.GeoJson(
        routes_web.to_json(),
        name="Existing Routes",
        style_function=lambda feature: {"color": "#2C7BE5", "weight": 2, "opacity": 0.45},
        tooltip=folium.GeoJsonTooltip(
            fields=[f for f in ["Route_ID", "Operator"] if f in routes_web.columns],
            aliases=[a for f, a in [("Route_ID", "Route ID"), ("Operator", "Operator")] if f in routes_web.columns],
            sticky=True,
        ),
    ).add_to(m)

    folium.GeoJson(
        corridors_web.to_json(),
        name="Main Corridors",
        style_function=lambda feature: {"color": "#F39C12", "weight": 4, "opacity": 0.65},
        tooltip=folium.GeoJsonTooltip(
            fields=[f for f in ["Name"] if f in corridors_web.columns],
            aliases=["Corridor"],
        ),
    ).add_to(m)

    for item in result["overlap_geometries"]:
        geom = item["geometry"]
        if geom is None or geom.is_empty:
            continue

        overlap_gdf = gpd.GeoDataFrame(
            {"Route_ID": [item["Route_ID"]]}, geometry=[geom], crs=ANALYSIS_CRS
        )
        overlap_web = overlap_gdf.to_crs(WEB_CRS)

        folium.GeoJson(
            overlap_web.to_json(),
            name="Overlap - " + item["Route_ID"],
            style_function=lambda feature: {"color": "#E74C3C", "weight": 7, "opacity": 0.90},
            tooltip="Overlapping route: " + item["Route_ID"],
        ).add_to(m)

    folium.GeoJson(
        proposed_web.to_json(),
        name="PROPOSED / SELECTED ROUTE",
        style_function=lambda feature: {"color": "#00A65A", "weight": 7, "opacity": 1},
        tooltip=folium.GeoJsonTooltip(
            fields=["Route_ID"] if "Route_ID" in proposed_web.columns else [],
            aliases=["Route"],
        ),
    ).add_to(m)

    proposed_buffer = proposed_gdf.copy()
    proposed_buffer["geometry"] = proposed_buffer.geometry.buffer(tolerance)
    proposed_buffer = proposed_buffer.to_crs(WEB_CRS)

    folium.GeoJson(
        proposed_buffer.to_json(),
        name=f"Analysis Buffer ({tolerance} m)",
        style_function=lambda feature: {
            "color": "#00A65A",
            "weight": 1,
            "fillColor": "#00A65A",
            "fillOpacity": 0.08,
        },
    ).add_to(m)

    affected = result["affected_stops"].to_crs(WEB_CRS)
    stop_group = folium.FeatureGroup(name="Affected Bus Stops")

    for _, stop in affected.iterrows():
        stop_name = str(stop.get("Name", "Bus Stop"))
        route_id = str(stop.get("Route_ID", ""))

        folium.CircleMarker(
            location=[stop.geometry.y, stop.geometry.x],
            radius=5,
            color="#8E44AD",
            fill=True,
            fillColor="#8E44AD",
            fillOpacity=0.85,
            tooltip=f"<b>{stop_name}</b><br>Route: {route_id}",
        ).add_to(stop_group)

    stop_group.add_to(m)

    Fullscreen(position="topright").add_to(m)
    MeasureControl(
        position="topright",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
    ).add_to(m)

    m.get_root().html.add_child(folium.Element(MAP_LEGEND_HTML))
    folium.LayerControl(collapsed=False).add_to(m)

    return m


def build_input_map(
    routes: gpd.GeoDataFrame,
    corridors: gpd.GeoDataFrame,
    enable_draw: bool = True,
) -> folium.Map:
    """
    Draw-mode input map (replaces the ipyleaflet DrawControl map).
    Render this with streamlit_folium.st_folium() and read the
    drawn line back from its return value's "last_active_drawing".
    """
    routes_web = routes.to_crs(WEB_CRS)
    corridors_web = corridors.to_crs(WEB_CRS)

    center = routes_web.geometry.unary_union.centroid

    m = folium.Map(location=[center.y, center.x], zoom_start=11, tiles=None)
    folium.TileLayer("OpenStreetMap", opacity=0.4, name="OpenStreetMap").add_to(m)

    folium.GeoJson(
        routes_web.to_json(),
        name="Existing Routes",
        style_function=lambda feature: {"color": "#2C7BE5", "weight": 2, "opacity": 0.35},
    ).add_to(m)

    folium.GeoJson(
        corridors_web.to_json(),
        name="Main Corridors",
        style_function=lambda feature: {"color": "#F39C12", "weight": 4, "opacity": 0.5},
    ).add_to(m)

    if enable_draw:
        Draw(
            export=False,
            position="topleft",
            draw_options={
                "polyline": {"shapeOptions": {"color": "#00A65A", "weight": 5, "opacity": 1.0}},
                "polygon": False,
                "circle": False,
                "circlemarker": False,
                "marker": False,
                "rectangle": False,
            },
            edit_options={"edit": True, "remove": True},
        ).add_to(m)

    Fullscreen(position="topright").add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    return m
