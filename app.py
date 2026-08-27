# ============================================================
# app.py
# BUS ROUTE OVERLAP & RATIONALIZATION TOOL - STREAMLIT APP
# ============================================================
#
# Streamlit port of the original Jupyter/ipywidgets tool.
# Preserves both tabs, drawing, upload, the results map,
# Excel export, and the 98x98 (N x N) self-overlap matrix.
#
# Run with:
#   streamlit run app.py
#
# ============================================================

import streamlit as st
from streamlit_folium import st_folium

import analysis as core
import map_utils

# ------------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------------

st.set_page_config(
    page_title="Bus Route Overlap & Rationalization Tool",
    page_icon="\U0001F68C",
    layout="wide",
)

st.markdown(
    """
    <div style="background:#1F4E78;color:white;padding:18px 25px;
                border-radius:8px;margin-bottom:12px;">
        <div style="font-size:25px;font-weight:bold;">
            \U0001F68C BUS ROUTE OVERLAP & RATIONALIZATION TOOL
        </div>
        <div style="font-size:13px;margin-top:5px;opacity:.9;">
            Streamlit edition
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

TOLERANCE_OPTIONS = {"10 m": 10, "25 m": 25, "50 m": 50, "75 m": 75, "100 m": 100}


# ------------------------------------------------------------
# SESSION STATE
# ------------------------------------------------------------

def _init_state():
    defaults = {
        "proposed_route_gdf": None,
        "current_result": None,
        "current_tolerance": None,
        "network_matrix_result": None,
        "network_pairs_result": None,
        "route_id": "NEW-001",
        "origin": "Mirpur",
        "destination": "Jatrabari",
        "drawn_geometry_source": None,  # "upload" | "draw" | "existing"
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


# ------------------------------------------------------------
# DATA LOADING (cached)
# ------------------------------------------------------------

@st.cache_resource(show_spinner="Loading route network...")
def _load_data(data_dir: str):
    return core.load_network_data(data_dir)


with st.sidebar:
    st.markdown("### Network data")
    data_dir = st.text_input(
        "Data folder",
        value=st.session_state.get("data_dir", "./data"),
        help=(
            "Folder containing Official_Bus_Routes_98.shp, "
            "Official_Bus_Stops_98.shp, Bus_Corridors.shp, and "
            "(optionally) 98_Overlap_Matrix.xlsx"
        ),
    )
    st.session_state["data_dir"] = data_dir

    load_clicked = st.button("Load / reload network", use_container_width=True)

if "routes" not in st.session_state or load_clicked:
    try:
        routes, stops, corridors, overlap_matrix = _load_data(data_dir)
        st.session_state["routes"] = routes
        st.session_state["stops"] = stops
        st.session_state["corridors"] = corridors
        st.session_state["overlap_matrix"] = overlap_matrix
    except Exception as e:
        st.error(f"Could not load network data: {e}")
        st.stop()

routes = st.session_state["routes"]
stops = st.session_state["stops"]
corridors = st.session_state["corridors"]

with st.sidebar:
    st.success(
        f"Existing routes: {len(routes)}\n\n"
        f"Bus stops: {len(stops)}\n\n"
        f"Corridors: {len(corridors)}"
    )
    st.caption(f"Analysis CRS: {core.ANALYSIS_CRS}")
    st.markdown("---")
    st.caption("Data Source: BRR Project-2026, Dhaka Transport Coordination Authority")   
    st.caption("Author: A. T. M Neamul, GIS Expert and Data Analyst")
    st.caption("Email: sujon.kuet@gmail.com")


# ------------------------------------------------------------
# SHARED RESULT RENDERING
# ------------------------------------------------------------

def _section_header(title: str):
    st.markdown(
        f'<div style="background:#1F4E78;color:white;padding:10px;'
        f'font-size:18px;font-weight:bold;margin-top:15px;">{title}</div>',
        unsafe_allow_html=True,
    )


def render_results(result: dict, proposed_gdf, tolerance: float):
    summary = result["summary"]

    _section_header("ANALYSIS SUMMARY")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Route length", f'{summary["Length_km"]:.1f} km')
    c2.metric("Exact overlap", f'{summary["Exact_Overlap_km"]:.1f} km')
    c3.metric("Near overlap", f'{summary["Near_Overlap_km"]:.1f} km')
    c4.metric("Overlapping routes", f'{summary["Overlapping_Routes"]}')
    c5.metric("Conflict score", f'{summary["Conflict_Score"]}/100', summary["Conflict_Level"])

    map_col, table_col = st.columns([3, 2])

    with map_col:
        _section_header("MAP")
        result_map = map_utils.build_results_map(routes, stops, corridors, proposed_gdf, result, tolerance)
        st_folium(result_map, width=None, height=620, returned_objects=[], key="results_map")

    with table_col:
        _section_header("OVERLAPPING ROUTES")
        route_results = result["route_results"]
        if len(route_results) == 0:
            st.info("No significant overlapping routes detected.")
        else:
            table = route_results[["Route_ID", "Operator", "Overlap_km", "Overlap_%", "Severity"]].copy()
            table.columns = ["Route", "Operator", "Overlap (km)", "Overlap (%)", "Severity"]
            table["Overlap (km)"] = table["Overlap (km)"].round(2)
            table["Overlap (%)"] = table["Overlap (%)"].round(1)
            st.dataframe(table.head(15), use_container_width=True, hide_index=True)

        _section_header("RECOMMENDATION")
        box_color = (
            "#F8D7DA" if summary["Conflict_Level"] in ["HIGH", "VERY HIGH"]
            else "#FFF3CD" if summary["Conflict_Level"] == "MEDIUM"
            else "#D4EDDA"
        )
        st.markdown(
            f'<div style="background:{box_color};padding:15px;border-radius:6px;'
            f'font-size:15px;">{result["recommendation"]}</div>',
            unsafe_allow_html=True,
        )

    _section_header("AFFECTED BUS STOPS")
    stop_table = core.build_affected_stops_table(result["affected_stops"])
    if len(stop_table) == 0:
        st.info("No affected bus stops found.")
    else:
        st.caption(f"Unique affected bus stops: {len(stop_table)}")
        st.dataframe(stop_table, use_container_width=True, hide_index=True)

    _section_header("AFFECTED MAIN CORRIDORS")
    corridor_results = result["corridor_results"]
    if len(corridor_results) == 0:
        st.info("No corridor overlap detected.")
    else:
        st.dataframe(corridor_results.round(2), use_container_width=True, hide_index=True)

    st.download_button(
        "\U0001F4E5 Export results to Excel",
        data=core.export_result_to_excel(result),
        file_name=f'Bus_Route_Rationalization_{summary["Route"]}.xlsx',
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )


# ------------------------------------------------------------
# TABS
# ------------------------------------------------------------

tab1, tab2 = st.tabs(["\U0001F195 New / Custom Route", "\U0001F501 Existing Network Self-Overlap"])


# ============================================================
# TAB 1 - NEW / CUSTOM ROUTE
# ============================================================

with tab1:
    with st.expander("\u2139 How to use this tab"):
        st.markdown(
            "1. Fill in Route ID / Origin / Destination.\n"
            "2. Either **upload** a route file, or draw a polyline on the map below "
            "and click **Use drawn route**.\n"
            "3. Choose a matching tolerance.\n"
            "4. Click **ANALYZE**."
        )

    input_col, map_col = st.columns([1, 2])

    with input_col:
        st.session_state["route_id"] = st.text_input("Route ID", value=st.session_state["route_id"])
        st.session_state["origin"] = st.text_input("Origin", value=st.session_state["origin"])
        st.session_state["destination"] = st.text_input(
            "Destination", value=st.session_state["destination"]
        )

        st.markdown("**Route geometry**")
        uploaded_file = st.file_uploader(
            "Upload route (GeoJSON, GeoPackage, or zipped Shapefile)",
            type=["geojson", "json", "zip", "gpkg"],
            key="route_upload",
        )

        if uploaded_file is not None:
            try:
                st.session_state["proposed_route_gdf"] = core.read_route_file(
                    uploaded_file,
                    st.session_state["route_id"],
                    st.session_state["origin"],
                    st.session_state["destination"],
                )
                st.session_state["drawn_geometry_source"] = "upload"
                length_km = st.session_state["proposed_route_gdf"].geometry.iloc[0].length / 1000
                st.success(f"Route loaded successfully\n\nLength: {length_km:.2f} km")
            except Exception as e:
                st.session_state["proposed_route_gdf"] = None
                st.error(f"Route loading error: {e}")

        tolerance_label = st.selectbox(
            "Matching tolerance", list(TOLERANCE_OPTIONS.keys()), index=2, key="tab1_tolerance_label"
        )
        tolerance = TOLERANCE_OPTIONS[tolerance_label]

        analyze_clicked = st.button("\U0001F50D ANALYZE", type="primary", use_container_width=True, key="tab1_analyze")
        refresh_clicked = st.button("\U0001F504 Refresh / Reset", use_container_width=True, key="tab1_refresh")

    with map_col:
        st.markdown("**Draw a route (optional)** \u2014 use the polyline tool, top-left of the map.")
        input_map = map_utils.build_input_map(routes, corridors, enable_draw=True)
        draw_output = st_folium(input_map, width=None, height=480, key="draw_map")

        drawn_feature = draw_output.get("last_active_drawing") if draw_output else None

        if drawn_feature is not None and drawn_feature.get("geometry", {}).get("type") == "LineString":
            use_drawn = st.button("\u2705 Use drawn route", use_container_width=True, key="use_drawn_route")
            if use_drawn:
                try:
                    st.session_state["proposed_route_gdf"] = core.route_from_drawn_geojson(
                        drawn_feature,
                        st.session_state["route_id"],
                        st.session_state["origin"],
                        st.session_state["destination"],
                    )
                    st.session_state["drawn_geometry_source"] = "draw"
                    length_km = st.session_state["proposed_route_gdf"].geometry.iloc[0].length / 1000
                    st.success(f"Drawn route loaded \u2014 length: {length_km:.2f} km")
                except Exception as e:
                    st.error(f"Could not read the drawn shape: {e}")

    if refresh_clicked:
        st.session_state["proposed_route_gdf"] = None
        st.session_state["current_result"] = None
        st.session_state["drawn_geometry_source"] = None
        st.session_state["route_id"] = "NEW-001"
        st.session_state["origin"] = "Mirpur"
        st.session_state["destination"] = "Jatrabari"
        st.rerun()

    if analyze_clicked:
        if st.session_state["proposed_route_gdf"] is None:
            st.warning("Please upload a route, or draw one and click 'Use drawn route' first.")
        else:
            with st.spinner("Analyzing against the existing network..."):
                result = core.run_analysis(
                    routes,
                    stops,
                    corridors,
                    st.session_state["proposed_route_gdf"],
                    tolerance,
                    st.session_state["route_id"],
                    st.session_state["origin"],
                    st.session_state["destination"],
                )
            st.session_state["current_result"] = result
            st.session_state["current_tolerance"] = tolerance
            st.success("Analysis complete \u2014 proposed route analyzed against the existing network.")

    if st.session_state["current_result"] is not None and st.session_state["proposed_route_gdf"] is not None:
        render_results(
            st.session_state["current_result"],
            st.session_state["proposed_route_gdf"],
            st.session_state["current_tolerance"],
        )


# ============================================================
# TAB 2 - EXISTING NETWORK SELF-OVERLAP
# ============================================================

with tab2:
    with st.expander("\u2139 How to use this tab"):
        st.markdown(
            "**Single route:** pick a route and click **Analyze vs network**.\n\n"
            "**Whole network:** click **Compute full overlap matrix** to compare "
            "every route against every other route."
        )

    st.markdown("**Check one route vs the network**")

    route_ids = core.get_route_ids(routes)
    col_a, col_b, col_c = st.columns([2, 1, 1])

    with col_a:
        selected_id = st.selectbox("Route", route_ids, key="existing_route_dropdown")
    with col_b:
        tolerance_label_2 = st.selectbox(
            "Tolerance", list(TOLERANCE_OPTIONS.keys()), index=2, key="tab2_tolerance_label"
        )
        tolerance_2 = TOLERANCE_OPTIONS[tolerance_label_2]
    with col_c:
        st.write("")
        st.write("")
        analyze_existing_clicked = st.button(
            "\U0001F50D Analyze vs network", type="primary", use_container_width=True, key="tab2_analyze"
        )

    if analyze_existing_clicked:
        try:
            proposed_gdf, origin_val, dest_val = core.route_from_existing(routes, selected_id)
            with st.spinner(f"Comparing {selected_id} against the rest of the network..."):
                result = core.run_analysis(
                    routes,
                    stops,
                    corridors,
                    proposed_gdf,
                    tolerance_2,
                    selected_id,
                    origin_val,
                    dest_val,
                    exclude_route_id=selected_id,
                )
            st.session_state["existing_result"] = result
            st.session_state["existing_proposed_gdf"] = proposed_gdf
            st.session_state["existing_tolerance"] = tolerance_2
        except Exception as e:
            st.error(str(e))

    if st.session_state.get("existing_result") is not None:
        render_results(
            st.session_state["existing_result"],
            st.session_state["existing_proposed_gdf"],
            st.session_state["existing_tolerance"],
        )

    st.markdown("---")
    st.markdown("**Check the whole network at once**")

    compute_matrix_clicked = st.button(
        f"\U0001F4CA Compute full {len(route_ids)}\u00d7{len(route_ids)} overlap matrix",
        use_container_width=True,
        key="compute_matrix",
    )

    if compute_matrix_clicked:
        progress_bar = st.progress(0, text="Computing full overlap matrix...")

        def _progress_cb(done, total):
            pct = int(done / total * 100) if total else 100
            progress_bar.progress(pct, text=f"Computing full overlap matrix... ({done}/{total} pairs)")

        matrix, pairs_df = core.compute_full_overlap_matrix(
            routes, tolerance_2, progress_callback=_progress_cb
        )
        st.session_state["network_matrix_result"] = matrix
        st.session_state["network_pairs_result"] = pairs_df
        progress_bar.progress(100, text="Matrix computed.")
        st.success(f"Matrix computed. {len(pairs_df)} route pairs exceed the overlap threshold.")

    if st.session_state["network_pairs_result"] is not None:
        _section_header(f"TOP OVERLAPPING ROUTE PAIRS (Network-Wide, tolerance {tolerance_2} m)")
        pairs_df = st.session_state["network_pairs_result"]

        if len(pairs_df) == 0:
            st.info("No significant overlaps found across the network at this tolerance.")
        else:
            table = pairs_df.head(30).copy()
            table["Overlap_km"] = table["Overlap_km"].round(2)
            table["Exact_km"] = table["Exact_km"].round(2)
            table["Overlap_%"] = table["Overlap_%"].round(1)
            st.dataframe(table, use_container_width=True, hide_index=True)

        st.download_button(
            "\U0001F4E5 Export full matrix",
            data=core.export_matrix_to_excel(
                st.session_state["network_matrix_result"], st.session_state["network_pairs_result"]
            ),
            file_name="Overlap_Matrix_Updated.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
