# Bus Route Overlap & Rationalization Tool (Streamlit)

A Streamlit port of the original Jupyter/ipywidgets notebook. Same analysis
logic, same two tabs, same maps, drawing, upload, Excel export, and the full
N×N (98×98) network self-overlap matrix — now runnable as a standalone web
app instead of a notebook.

## Project layout

```
bus_route_app/
├── app.py            # Streamlit UI: session state, both tabs, results rendering
├── analysis.py        # Pure analysis logic (geometry, overlap, scoring, matrix, I/O)
├── map_utils.py        # Folium map builders (results map + draw-mode input map)
├── requirements.txt
├── data/               # Put your network shapefiles here (see below)
└── README.md
```

## 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Add your network data

Place these files in the `data/` folder (or point the app at any folder via
the sidebar "Data folder" field):

- `Official_Bus_Routes_98.shp` (+ `.dbf`, `.shx`, `.prj`, …) — needs a
  `Route_ID` field, and optionally `Operator`.
- `Official_Bus_Stops_98.shp` — needs a `Name` field.
- `Bus_Corridors.shp` — needs a `Name` field.
- `98_Overlap_Matrix.xlsx` — optional, precomputed matrix (not required to
  run the app; the app can compute this itself from Tab 2).

Any CRS is fine — the app reprojects everything to `EPSG:32646` internally
for length/overlap math and to `EPSG:4326` for the map.

## 3. Run

```bash
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

## What each tab does

**🆕 New / Custom Route**
- Enter Route ID / Origin / Destination.
- Provide the route geometry either by uploading a file (GeoJSON, GeoPackage,
  or a zipped Shapefile) or by drawing a polyline directly on the map, then
  clicking **Use drawn route**.
- Pick a matching tolerance and click **ANALYZE**.
- Get the results map, overlap table, conflict score, recommendation, the
  unique affected-bus-stops table (Name / Latitude / Longitude, EPSG:4326,
  de-duplicated), affected corridors, and an Excel export.

**🔁 Existing Network Self-Overlap**
- Pick any of the existing routes and compare it against the rest of the
  network (same result view as above).
- Or click **Compute full N×N overlap matrix** to run every route against
  every other route, with a live progress bar, a ranked table of the top
  overlapping pairs, and an Excel export of the full matrix + pairs table.

## Notes on the port from the notebook

- ipywidgets → Streamlit widgets (`st.text_input`, `st.selectbox`,
  `st.file_uploader`, `st.button`, session state for everything the notebook
  used module-level globals for).
- ipyleaflet `DrawControl` → `folium.plugins.Draw`, rendered with
  `streamlit_folium.st_folium`, reading the drawn line back from
  `last_active_drawing`.
- All core geometry/overlap/scoring functions in `analysis.py` are
  unchanged in behavior from the notebook (same tolerance logic, same
  0.55/0.25/0.10/0.10 conflict-score weighting, same HIGH/MEDIUM/LOW/MINIMAL
  severity thresholds).
- Excel export now returns in-memory bytes for `st.download_button` instead
  of writing to a fixed Windows path.
