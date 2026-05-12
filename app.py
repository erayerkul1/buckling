import tempfile
import pandas as pd
import streamlit as st
from panel_length_calculator import compute_panel_lengths

st.set_page_config(
    page_title="Panel Length Calculator",
    page_icon="📐",
    layout="wide",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: #0f1117; }

    .header-box {
        background: linear-gradient(135deg, #1e2130 0%, #252840 100%);
        border: 1px solid #2e3250;
        border-radius: 16px;
        padding: 28px 32px 20px;
        margin-bottom: 24px;
    }
    .header-box h1 { color: #e8eaf6; font-size: 24px; font-weight: 700; margin: 0 0 4px; }
    .header-box p  { color: #8892b0; font-size: 13px; margin: 0; }

    .card {
        background: #1a1d2e;
        border: 1px solid #252840;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
    }
    .card-title {
        color: #a0aec0; font-size: 10px; font-weight: 600;
        letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 12px;
    }

    .stFileUploader > div {
        background: #1a1d2e !important;
        border: 1.5px dashed #2e3250 !important;
        border-radius: 10px !important;
    }
    .stTextArea textarea {
        background: #0f1117 !important;
        border: 1.5px solid #2e3250 !important;
        border-radius: 10px !important;
        color: #e8eaf6 !important;
        font-family: 'Inter', monospace !important;
        font-size: 14px !important;
    }
    .stTextArea textarea:focus {
        border-color: #5c6bc0 !important;
        box-shadow: 0 0 0 3px rgba(92,107,192,0.15) !important;
    }

    .stButton > button {
        width: 100%;
        background: linear-gradient(135deg, #5c6bc0, #3f51b5) !important;
        color: white !important; border: none !important;
        border-radius: 10px !important; padding: 13px !important;
        font-size: 14px !important; font-weight: 600 !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #7986cb, #5c6bc0) !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(92,107,192,0.35) !important;
    }

    .stDataFrame { border-radius: 10px; overflow: hidden; }

    .stat-row { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .stat-chip {
        flex: 1; min-width: 100px;
        background: #1e2130; border: 1px solid #2e3250;
        border-radius: 10px; padding: 12px 14px; text-align: center;
    }
    .stat-chip .val { color: #7986cb; font-size: 20px; font-weight: 700; }
    .stat-chip .lbl { color: #8892b0; font-size: 10px; font-weight: 500; margin-top: 2px; }

    .err-row {
        background: #2d1b1b; border: 1px solid #5c2020;
        border-radius: 8px; padding: 8px 12px; margin: 4px 0;
        color: #fc8181; font-size: 12px;
    }

    .stDownloadButton > button {
        width: 100%;
        background: #1e2130 !important; color: #7986cb !important;
        border: 1.5px solid #3f51b5 !important; border-radius: 10px !important;
        font-weight: 600 !important; font-size: 13px !important; padding: 11px !important;
    }
    .stDownloadButton > button:hover {
        background: #252840 !important; color: #a0b0ff !important;
    }

    .bar-tag {
        display: inline-block;
        padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;
        margin-right: 4px;
    }
    .bar-x { background: #1a2744; color: #7986cb; border: 1px solid #3f51b5; }
    .bar-y { background: #1a2d1a; color: #66bb6a; border: 1px solid #2e7d32; }

    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding-top: 1.5rem; max-width: 1400px; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-box">
  <h1>📐 Panel Length Calculator</h1>
  <p>Upload a Nastran BDF · Enter property IDs · Get X/Y lengths + edge bar properties as CSV</p>
</div>
""", unsafe_allow_html=True)

# ── Layout: left inputs / right results ──────────────────────────────────────
left, right = st.columns([1, 2], gap="large")

with left:
    st.markdown('<div class="card"><div class="card-title">① BDF File</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("", type=["bdf", "dat", "nas", "pch"], label_visibility="collapsed")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="card-title">② Property IDs</div>', unsafe_allow_html=True)
    pid_input = st.text_area(
        "",
        placeholder="1, 2, 3\nor one per line:\n1\n2\n3",
        height=140,
        label_visibility="collapsed",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    run = st.button("Calculate Panel Lengths")

# ── Compute ───────────────────────────────────────────────────────────────────
if run:
    with right:
        if not uploaded:
            st.error("Please upload a BDF file first.")
            st.stop()

        raw   = pid_input.replace(",", "\n")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if not lines:
            st.error("Please enter at least one property ID.")
            st.stop()

        try:
            pids = [int(x) for x in lines]
        except ValueError:
            st.error("Property IDs must be integers.")
            st.stop()

        with tempfile.NamedTemporaryFile(suffix=".bdf", delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        rows   = []
        errors = []
        bar_labels = ["x1", "x2", "y1", "y2"]

        progress = st.progress(0, text="Processing…")
        for i, pid in enumerate(pids):
            try:
                res = compute_panel_lengths(tmp_path, pid)
                row = {
                    "property_id":   res["property_id"],
                    "plane":         res["plane"],
                    "x_length":      res["x_length"],
                    "y_length":      res["y_length"],
                    "x_direction":   res["x_direction"],
                }
                for lbl in bar_labels:
                    b = res["bars"][lbl]
                    row[f"bar_prop_{lbl}"]  = b["pid"]
                    row[f"bar_dim1_{lbl}"]  = b["dim1"]
                    row[f"bar_dim2_{lbl}"]  = b["dim2"]
                rows.append(row)
            except Exception as e:
                errors.append(f"PID {pid}: {e}")
            progress.progress((i + 1) / len(pids), text=f"Processing PID {pid}…")

        progress.empty()

        for err in errors:
            st.markdown(f'<div class="err-row">⚠ {err}</div>', unsafe_allow_html=True)

        if not rows:
            st.stop()

        df = pd.DataFrame(rows)

        # Stat chips
        ok  = len(rows)
        bad = len(errors)
        st.markdown(f"""
        <div class="stat-row">
          <div class="stat-chip"><div class="val">{ok}</div><div class="lbl">OK</div></div>
          <div class="stat-chip"><div class="val">{bad}</div><div class="lbl">Failed</div></div>
          <div class="stat-chip"><div class="val">{df["x_length"].mean():.1f}</div><div class="lbl">Avg X (mm)</div></div>
          <div class="stat-chip"><div class="val">{df["y_length"].mean():.1f}</div><div class="lbl">Avg Y (mm)</div></div>
        </div>
        """, unsafe_allow_html=True)

        # ── Panel dimensions table ────────────────────────────────────────────
        st.markdown('<div class="card"><div class="card-title">③ Panel Dimensions</div>', unsafe_allow_html=True)
        dim_df = df[["property_id", "plane", "x_direction", "x_length", "y_length"]].rename(columns={
            "property_id": "Property ID",
            "plane":       "Plane",
            "x_direction": "X Direction",
            "x_length":    "X Length (mm)",
            "y_length":    "Y Length (mm)",
        })
        st.dataframe(dim_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ── Bar properties table ──────────────────────────────────────────────
        st.markdown('<div class="card"><div class="card-title">④ Edge Bar Properties</div>', unsafe_allow_html=True)

        bar_cols = ["property_id"]
        for lbl in bar_labels:
            bar_cols += [f"bar_prop_{lbl}", f"bar_dim1_{lbl}", f"bar_dim2_{lbl}"]

        bar_df = df[bar_cols].rename(columns={
            "property_id": "Property ID",
            **{f"bar_prop_{l}":  f"Bar PID ({l.upper()})"  for l in bar_labels},
            **{f"bar_dim1_{l}":  f"Dim1 ({l.upper()})"     for l in bar_labels},
            **{f"bar_dim2_{l}":  f"Dim2 ({l.upper()})"     for l in bar_labels},
        })
        st.dataframe(bar_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ── CSV export ────────────────────────────────────────────────────────
        csv_cols = {
            "property_id": "property_id",
            "x_length":    "x",
            "y_length":    "y",
        }
        for lbl in bar_labels:
            csv_cols[f"bar_prop_{lbl}"]  = f"bar_prop_{lbl}"
            csv_cols[f"bar_dim1_{lbl}"]  = f"bar_dim1_{lbl}"
            csv_cols[f"bar_dim2_{lbl}"]  = f"bar_dim2_{lbl}"

        csv_df    = df[list(csv_cols.keys())].rename(columns=csv_cols)
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="⬇  Download CSV",
            data=csv_bytes,
            file_name="panel_lengths.csv",
            mime="text/csv",
        )
