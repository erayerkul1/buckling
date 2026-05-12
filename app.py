import io
import tempfile
import pandas as pd
import streamlit as st
from panel_length_calculator import compute_panel_lengths

st.set_page_config(
    page_title="Panel Length Calculator",
    page_icon="📐",
    layout="centered",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .stApp { background: #0f1117; }

    /* Header */
    .header-box {
        background: linear-gradient(135deg, #1e2130 0%, #252840 100%);
        border: 1px solid #2e3250;
        border-radius: 16px;
        padding: 32px 36px 24px;
        margin-bottom: 28px;
    }
    .header-box h1 { color: #e8eaf6; font-size: 26px; font-weight: 700; margin: 0 0 6px; }
    .header-box p  { color: #8892b0; font-size: 14px; margin: 0; }

    /* Cards */
    .card {
        background: #1a1d2e;
        border: 1px solid #252840;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
    }
    .card-title {
        color: #a0aec0;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        margin-bottom: 14px;
    }

    /* Inputs */
    .stFileUploader > div { background: #1a1d2e !important; border: 1.5px dashed #2e3250 !important; border-radius: 10px !important; }
    .stTextArea textarea {
        background: #0f1117 !important;
        border: 1.5px solid #2e3250 !important;
        border-radius: 10px !important;
        color: #e8eaf6 !important;
        font-family: 'Inter', monospace !important;
        font-size: 15px !important;
    }
    .stTextArea textarea:focus { border-color: #5c6bc0 !important; box-shadow: 0 0 0 3px rgba(92,107,192,0.15) !important; }

    /* Button */
    .stButton > button {
        width: 100%;
        background: linear-gradient(135deg, #5c6bc0, #3f51b5) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 14px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #7986cb, #5c6bc0) !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(92,107,192,0.35) !important;
    }

    /* Table */
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    thead tr th {
        background: #1e2130 !important;
        color: #8892b0 !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 1px !important;
        text-transform: uppercase !important;
    }
    tbody tr td { color: #e8eaf6 !important; font-size: 14px !important; }
    tbody tr:hover td { background: #252840 !important; }

    /* Stat chips */
    .stat-row { display: flex; gap: 12px; margin-bottom: 20px; }
    .stat-chip {
        flex: 1;
        background: #1e2130;
        border: 1px solid #2e3250;
        border-radius: 10px;
        padding: 14px 16px;
        text-align: center;
    }
    .stat-chip .val { color: #7986cb; font-size: 22px; font-weight: 700; }
    .stat-chip .lbl { color: #8892b0; font-size: 11px; font-weight: 500; margin-top: 2px; }

    /* Error / warning */
    .err-row { background: #2d1b1b; border: 1px solid #5c2020; border-radius: 8px; padding: 10px 14px; margin: 6px 0; color: #fc8181; font-size: 13px; }

    /* Download button */
    .stDownloadButton > button {
        width: 100%;
        background: #1e2130 !important;
        color: #7986cb !important;
        border: 1.5px solid #3f51b5 !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        padding: 12px !important;
    }
    .stDownloadButton > button:hover {
        background: #252840 !important;
        color: #a0b0ff !important;
    }

    /* Hide streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding-top: 2rem; max-width: 780px; }
</style>
""", unsafe_allow_html=True)

# ── Header ──────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-box">
  <h1>📐 Panel Length Calculator</h1>
  <p>Upload a Nastran BDF file, enter property IDs and get X / Y panel lengths instantly.</p>
</div>
""", unsafe_allow_html=True)

# ── Upload ───────────────────────────────────────────────────────────────────
st.markdown('<div class="card"><div class="card-title">① BDF File</div>', unsafe_allow_html=True)
uploaded = st.file_uploader("", type=["bdf", "dat", "nas", "pch"], label_visibility="collapsed")
st.markdown('</div>', unsafe_allow_html=True)

# ── Property IDs ─────────────────────────────────────────────────────────────
st.markdown('<div class="card"><div class="card-title">② Property IDs</div>', unsafe_allow_html=True)
pid_input = st.text_area(
    "",
    placeholder="e.g.  1, 2, 3   or one per line:\n1\n2\n3",
    height=120,
    label_visibility="collapsed",
)
st.markdown('</div>', unsafe_allow_html=True)

# ── Run ───────────────────────────────────────────────────────────────────────
run = st.button("Calculate Panel Lengths")

if run:
    if not uploaded:
        st.error("Please upload a BDF file first.")
        st.stop()

    raw = pid_input.replace(",", "\n")
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

    rows = []
    errors = []

    progress = st.progress(0, text="Processing…")
    for i, pid in enumerate(pids):
        try:
            res = compute_panel_lengths(tmp_path, pid)
            rows.append({
                "Property ID": res["property_id"],
                "Plane":       res["plane"],
                "X Length (mm)": res["x_length"],
                "Y Length (mm)": res["y_length"],
                "X Direction": res["x_direction"],
            })
        except Exception as e:
            errors.append(f"PID {pid}: {e}")
        progress.progress((i + 1) / len(pids), text=f"Processing PID {pid}…")

    progress.empty()

    if errors:
        for err in errors:
            st.markdown(f'<div class="err-row">⚠ {err}</div>', unsafe_allow_html=True)

    if rows:
        df = pd.DataFrame(rows)

        # Stat chips
        ok  = len(rows)
        bad = len(errors)
        st.markdown(f"""
        <div class="stat-row">
          <div class="stat-chip"><div class="val">{ok}</div><div class="lbl">Successful</div></div>
          <div class="stat-chip"><div class="val">{bad}</div><div class="lbl">Failed</div></div>
          <div class="stat-chip"><div class="val">{df["X Length (mm)"].mean():.1f}</div><div class="lbl">Avg X (mm)</div></div>
          <div class="stat-chip"><div class="val">{df["Y Length (mm)"].mean():.1f}</div><div class="lbl">Avg Y (mm)</div></div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="card"><div class="card-title">③ Results</div>', unsafe_allow_html=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # CSV export (only property_id, x, y as requested)
        csv_df = df[["Property ID", "X Length (mm)", "Y Length (mm)"]].rename(columns={
            "Property ID":   "property_id",
            "X Length (mm)": "x",
            "Y Length (mm)": "y",
        })
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇  Download CSV  (property_id, x, y)",
            data=csv_bytes,
            file_name="panel_lengths.csv",
            mime="text/csv",
        )
