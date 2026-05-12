"""
Panel Length Calculator
=======================
Spyder'da F5 ile çalıştır → arayüz açılır.

- BDF dosyası seç
- Property ID'leri virgülle gir  (örn: 1, 2, 3)
- CSV kayıt yolunu seç
- Calculate → sonuçlar tabloda + CSV'ye yazılır
"""

import sys
import os
import csv
import numpy as np
from itertools import combinations
from scipy.spatial import ConvexHull
from pyNastran.bdf.bdf import BDF

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QAbstractItemView, QMessageBox,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QColor

# ═══════════════════════════════════════════════════════════════════════════════
#  HESAPLAMA MOTORU
# ═══════════════════════════════════════════════════════════════════════════════

SHELL_TYPES = {"CQUAD4": 4, "CQUAD8": 4, "CTRIA3": 3, "CTRIA6": 3}
BAR_TYPES   = {"CBAR", "CBEAM", "CROD", "CTUBE"}
PLANE_AXES  = {"XZ": [0, 2], "ZY": [2, 1], "XY": [0, 1]}


def load_bdf(bdf_path: str) -> BDF:
    model = BDF(debug=False)
    model.read_bdf(bdf_path, xref=False)
    return model


def build_bar_prop_nodes(model: BDF) -> dict[int, set]:
    """Bar property → node ID seti. Model başına bir kez hesaplanır."""
    prop_nodes: dict[int, set] = {}
    for elem in model.elements.values():
        if elem.type in BAR_TYPES:
            prop_nodes.setdefault(elem.pid, set()).update(elem.node_ids)
    return prop_nodes


def get_nodes_for_property(model: BDF, pid: int) -> tuple[dict, dict]:
    """
    Tek geçişte hem köşe hem tüm node koordinatlarını döndürür.
    Returns: (corner_coords, all_coords)
    """
    corner_nids: set = set()
    all_nids:    set = set()
    for elem in model.elements.values():
        if elem.pid == pid and elem.type in SHELL_TYPES:
            nids = elem.node_ids
            corner_nids.update(nids[:SHELL_TYPES[elem.type]])
            all_nids.update(nids)
    if not corner_nids:
        raise ValueError(f"Property ID {pid} için shell eleman bulunamadı.")
    get_pos = lambda n: np.array(model.nodes[n].get_position(), dtype=float)
    all_c    = {n: get_pos(n) for n in all_nids}
    corner_c = {n: all_c[n]  for n in corner_nids}
    return corner_c, all_c


def detect_plane(coords: dict) -> str:
    pts = np.array(list(coords.values()))
    return {0: "ZY", 1: "XZ", 2: "XY"}[int(np.argmin(pts.var(axis=0)))]


def find_corners(coords: dict, plane: str) -> list:
    axes  = PLANE_AXES[plane]
    nids  = list(coords.keys())
    pts2d = np.array([coords[n][axes] for n in nids])
    nid_idx = {n: i for i, n in enumerate(nids)}  # O(1) lookup

    if len(nids) < 4:
        raise ValueError("4'ten az köşe node bulundu.")
    if len(nids) == 4:
        return nids

    hull_nids = [nids[i] for i in ConvexHull(pts2d).vertices]
    if len(hull_nids) == 4:
        return hull_nids

    # En geniş dörtgeni bul (maksimum alan)
    best_area, best_quad = -1, None
    for quad in combinations(hull_nids, 4):
        qp = pts2d[[nid_idx[n] for n in quad]]
        c  = qp.mean(axis=0)
        o  = np.argsort(np.arctan2(qp[:,1]-c[1], qp[:,0]-c[0]))
        op = qp[o]
        area = 0.5 * abs(
            op[0,0]*(op[1,1]-op[3,1]) + op[1,0]*(op[2,1]-op[0,1]) +
            op[2,0]*(op[3,1]-op[1,1]) + op[3,0]*(op[0,1]-op[2,1])
        )
        if area > best_area:
            best_area = area
            best_quad = [quad[i] for i in o]
    return best_quad


def order_ccw(corner_nids: list, coords: dict, plane: str) -> list:
    axes = PLANE_AXES[plane]
    pts  = np.array([coords[n][axes] for n in corner_nids])
    c    = pts.mean(axis=0)
    ang  = np.arctan2(pts[:,1]-c[1], pts[:,0]-c[0])
    return [corner_nids[i] for i in np.argsort(ang)]


def nodes_on_segment(all_nids: list, all_pts: np.ndarray,
                     pa: np.ndarray, pb: np.ndarray) -> set:
    """Numpy vektör işlemleriyle kenar üzerindeki node'ları bulur."""
    edge_vec = pb - pa
    edge_lsq = float(np.dot(edge_vec, edge_vec))
    edge_len = np.sqrt(edge_lsq)
    tol_perp = max(0.01 * edge_len, 1e-3)
    tol_t    = 1e-4

    v    = all_pts - pa                          # (N, 3)
    t    = (v @ edge_vec) / edge_lsq            # (N,)
    mask = (t >= -tol_t) & (t <= 1.0 + tol_t)
    proj = pa + t[:, None] * edge_vec           # (N, 3)
    perp = np.linalg.norm(all_pts - proj, axis=1)
    mask &= (perp < tol_perp)
    return {all_nids[i] for i in np.where(mask)[0]}


def find_bar_prop(bar_prop_nodes: dict, edge_nodes: set) -> tuple:
    """Önceden hesaplanmış haritadan en iyi bar property'yi seçer."""
    best_pid, best_n = None, 0
    for pid, bar_nids in bar_prop_nodes.items():
        shared = len(edge_nodes & bar_nids)
        if shared > best_n:
            best_n, best_pid = shared, pid
    return best_pid, best_n


def get_bar_dims(model: BDF, bar_pid) -> tuple:
    if bar_pid is None or bar_pid not in model.properties:
        return None, None
    prop  = model.properties[bar_pid]
    ptype = prop.type
    if ptype in ("PBARL", "PBEAML"):
        dims = getattr(prop, "dim", [])
        return (round(float(dims[0]), 6) if len(dims) > 0 else None,
                round(float(dims[1]), 6) if len(dims) > 1 else None)
    if ptype == "PBAR":
        return round(float(prop.A), 6), round(float(prop.i1), 6)
    if ptype == "PBEAM":
        a  = getattr(prop, "A",  [None])
        i1 = getattr(prop, "i1", [None])
        return (round(float(a[0]),  6) if a[0]  is not None else None,
                round(float(i1[0]), 6) if i1[0] is not None else None)
    if ptype == "PROD":
        return round(float(prop.A), 6), None
    return None, None


def compute(model: BDF, bar_prop_nodes: dict, pid: int) -> dict:
    """
    model ve bar_prop_nodes dışarıdan verilir (bir kez yüklenir).
    Döndürür: property_id, plane, x_length, y_length, x_direction,
              bars, avg_dim1_x, avg_dim2_x, avg_dim1_y, avg_dim2_y
    """
    corner_c, all_c = get_nodes_for_property(model, pid)

    plane   = detect_plane(corner_c)
    corners = find_corners(corner_c, plane)
    bl, br, tr, tl = order_ccw(corners, corner_c, plane)

    # Numpy array'e çevir → vektörize segment kontrolü için
    all_nids_list = list(all_c.keys())
    all_pts       = np.array([all_c[n] for n in all_nids_list])

    bottom = float(np.linalg.norm(corner_c[bl] - corner_c[br]))
    right  = float(np.linalg.norm(corner_c[br] - corner_c[tr]))
    top    = float(np.linalg.norm(corner_c[tr] - corner_c[tl]))
    left   = float(np.linalg.norm(corner_c[tl] - corner_c[bl]))

    h_avg, v_avg = (bottom + top) / 2, (left + right) / 2

    if h_avg >= v_avg:
        x_len, y_len, x_dir = h_avg, v_avg, "horizontal"
        x_edges = [("x1", bl, br), ("x2", tl, tr)]
        y_edges = [("y1", tl, bl), ("y2", br, tr)]
    else:
        x_len, y_len, x_dir = v_avg, h_avg, "vertical"
        x_edges = [("x1", tl, bl), ("x2", br, tr)]
        y_edges = [("y1", bl, br), ("y2", tl, tr)]

    bars = {}
    for label, na, nb in x_edges + y_edges:
        seg        = nodes_on_segment(all_nids_list, all_pts, corner_c[na], corner_c[nb])
        bpid, shn  = find_bar_prop(bar_prop_nodes, seg)
        d1, d2     = get_bar_dims(model, bpid)
        bars[label] = {"pid": bpid, "dim1": d1, "dim2": d2, "shared_nodes": shn}

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 6) if v else None

    return {
        "property_id": pid,
        "plane":       plane,
        "x_length":    round(x_len, 4),
        "y_length":    round(y_len, 4),
        "x_direction": x_dir,
        "bars":        bars,
        "avg_dim1_x":  _avg([bars["x1"]["dim1"], bars["x2"]["dim1"]]),
        "avg_dim2_x":  _avg([bars["x1"]["dim2"], bars["x2"]["dim2"]]),
        "avg_dim1_y":  _avg([bars["y1"]["dim1"], bars["y2"]["dim1"]]),
        "avg_dim2_y":  _avg([bars["y1"]["dim2"], bars["y2"]["dim2"]]),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  ARAYÜZ
# ═══════════════════════════════════════════════════════════════════════════════

BG     = "#0f1117"
CARD   = "#1a1d2e"
BORDER = "#2e3250"
ACCENT = "#5c6bc0"
ACC2   = "#7986cb"
TEXT   = "#e8eaf6"
SUB    = "#8892b0"
GREEN  = "#66bb6a"
RED    = "#fc8181"
AMBER  = "#ffa726"

STYLE = f"""
QMainWindow, QWidget  {{ background:{BG}; color:{TEXT}; font-family:'Segoe UI','Arial'; font-size:13px; }}
QLabel                {{ background:transparent; color:{TEXT}; }}
QLabel#title          {{ font-size:21px; font-weight:700; }}
QLabel#sub            {{ color:{SUB}; font-size:11px; }}
QLabel#sec            {{ color:{SUB}; font-size:10px; font-weight:600; letter-spacing:1px; }}
QLineEdit             {{ background:{CARD}; border:1.5px solid {BORDER}; border-radius:8px; padding:7px 11px; color:{TEXT}; }}
QLineEdit:focus       {{ border-color:{ACCENT}; }}
QTextEdit             {{ background:{CARD}; border:1.5px solid {BORDER}; border-radius:8px; padding:7px; color:{TEXT}; }}
QTextEdit:focus       {{ border-color:{ACCENT}; }}
QPushButton#pri       {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {ACCENT},stop:1 #3f51b5);
                         color:white; border:none; border-radius:8px; padding:10px 20px; font-weight:600; }}
QPushButton#pri:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {ACC2},stop:1 {ACCENT}); }}
QPushButton#pri:disabled {{ background:#252840; color:{SUB}; }}
QPushButton#sec       {{ background:{CARD}; color:{ACC2}; border:1.5px solid {ACCENT}; border-radius:8px; padding:10px 20px; font-weight:600; }}
QPushButton#sec:hover {{ background:#252840; color:white; }}
QPushButton#sec:disabled {{ color:{SUB}; border-color:{BORDER}; }}
QPushButton#brw       {{ background:{CARD}; color:{ACC2}; border:1.5px solid {BORDER}; border-radius:8px; padding:7px 14px; font-size:12px; }}
QPushButton#brw:hover {{ border-color:{ACCENT}; color:white; }}
QTableWidget          {{ background:{CARD}; border:1px solid {BORDER}; border-radius:8px;
                         gridline-color:{BORDER}; color:{TEXT}; font-size:12px; selection-background-color:#252840; }}
QTableWidget::item    {{ padding:5px 8px; border:none; }}
QHeaderView::section  {{ background:#1e2130; color:{SUB}; border:none; border-right:1px solid {BORDER};
                         border-bottom:1px solid {BORDER}; padding:5px 8px; font-size:10px; font-weight:600; letter-spacing:0.8px; }}
QProgressBar          {{ background:{CARD}; border:1px solid {BORDER}; border-radius:5px; height:5px; color:transparent; }}
QProgressBar::chunk   {{ background:{ACCENT}; border-radius:5px; }}
QScrollBar:vertical   {{ background:{BG}; width:7px; border-radius:3px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:3px; min-height:20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
"""

BAR_LABELS = ["x1", "x2", "y1", "y2"]

# Her bar için prop→dim1→dim2 yan yana, sonuna avg'lar
CSV_KEYS = (
    ["property_id", "x_length", "y_length"]
    + [k for l in BAR_LABELS for k in (f"bar_prop_{l}", f"bar_dim1_{l}", f"bar_dim2_{l}")]
    + ["avg_dim1_x", "avg_dim2_x", "avg_dim1_y", "avg_dim2_y"]
)
CSV_HEADERS = (
    ["property_id", "x", "y"]
    + [k for l in BAR_LABELS for k in (f"bar_prop_{l}", f"bar_dim1_{l}", f"bar_dim2_{l}")]
    + ["avg_dim1_x", "avg_dim2_x", "avg_dim1_y", "avg_dim2_y"]
)

TABLE_KEYS = (
    ["property_id", "plane", "x_direction", "x_length", "y_length"]
    + [k for l in BAR_LABELS for k in (f"bar_prop_{l}", f"bar_dim1_{l}", f"bar_dim2_{l}")]
    + ["avg_dim1_x", "avg_dim2_x", "avg_dim1_y", "avg_dim2_y"]
)
TABLE_HDRS = (
    ["Prop ID", "Plane", "X Yönü", "X Length\n(mm)", "Y Length\n(mm)"]
    + [k for l in BAR_LABELS for k in (f"Bar PID\n{l.upper()}", f"Dim1\n{l.upper()}", f"Dim2\n{l.upper()}")]
    + ["Avg Dim1\nX", "Avg Dim2\nX", "Avg Dim1\nY", "Avg Dim2\nY"]
)


class Worker(QObject):
    progress = pyqtSignal(int, int)
    row_done = pyqtSignal(dict)
    err_done = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(self, bdf_path, pids):
        super().__init__()
        self.bdf_path = bdf_path
        self.pids     = pids

    def run(self):
        # BDF ve bar haritası bir kez yüklenir, tüm PID'ler için paylaşılır
        try:
            model          = load_bdf(self.bdf_path)
            bar_prop_nodes = build_bar_prop_nodes(model)
        except Exception as e:
            for pid in self.pids:
                self.err_done.emit(pid, f"BDF yüklenemedi: {e}")
            self.finished.emit()
            return

        for i, pid in enumerate(self.pids):
            try:
                self.row_done.emit(compute(model, bar_prop_nodes, pid))
            except Exception as e:
                self.err_done.emit(pid, str(e))
            self.progress.emit(i + 1, len(self.pids))
        self.finished.emit()


def _card():
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{CARD};border:1px solid {BORDER};border-radius:12px;}}")
    return f


def _sec(text):
    l = QLabel(text.upper())
    l.setObjectName("sec")
    return l


def _divider():
    d = QFrame()
    d.setFixedHeight(1)
    d.setStyleSheet(f"background:{BORDER};border:none;")
    return d


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Panel Length Calculator")
        self.resize(1350, 760)
        self.setStyleSheet(STYLE)
        self._rows = []
        self._build()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── Başlık ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        t = QLabel("📐  Panel Length Calculator")
        t.setObjectName("title")
        s = QLabel("BDF seç · Property ID'leri gir · CSV kaydet")
        s.setObjectName("sub")
        hdr.addWidget(t)
        hdr.addStretch()
        hdr.addWidget(s, alignment=Qt.AlignBottom)
        lay.addLayout(hdr)
        lay.addWidget(_divider())

        # ── Giriş kartları (3 sütun) ──────────────────────────────────────────
        inp = QHBoxLayout()
        inp.setSpacing(14)
        inp.addWidget(self._bdf_card(),  3)
        inp.addWidget(self._pid_card(),  2)
        inp.addWidget(self._csv_card(),  3)
        lay.addLayout(inp)

        # ── Butonlar ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_calc = QPushButton("▶  Calculate")
        self.btn_calc.setObjectName("pri")
        self.btn_calc.setFixedHeight(42)
        self.btn_export = QPushButton("⬇  CSV Kaydet")
        self.btn_export.setObjectName("sec")
        self.btn_export.setFixedHeight(42)
        self.btn_export.setEnabled(False)
        self.btn_calc.clicked.connect(self._calc)
        self.btn_export.clicked.connect(self._export)
        btn_row.addWidget(self.btn_calc, 3)
        btn_row.addWidget(self.btn_export, 1)
        lay.addLayout(btn_row)

        # ── Progress + status ─────────────────────────────────────────────────
        self.prog = QProgressBar()
        self.prog.setFixedHeight(5)
        self.prog.setVisible(False)
        lay.addWidget(self.prog)

        self.status = QLabel("")
        self.status.setObjectName("sub")
        lay.addWidget(self.status)

        # ── Sonuç tablosu ─────────────────────────────────────────────────────
        lay.addWidget(self._table_card(), 1)

    # ── Kart builder'ları ─────────────────────────────────────────────────────

    def _bdf_card(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        v.addWidget(_sec("① BDF Dosyası"))
        row = QHBoxLayout()
        self.bdf_edit = QLineEdit()
        self.bdf_edit.setPlaceholderText(".bdf / .dat / .nas dosyası seçin…")
        self.bdf_edit.setReadOnly(True)
        b = QPushButton("Seç…")
        b.setObjectName("brw")
        b.setFixedHeight(36)
        b.clicked.connect(self._browse_bdf)
        row.addWidget(self.bdf_edit)
        row.addWidget(b)
        v.addLayout(row)
        return c

    def _pid_card(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        v.addWidget(_sec("② Property ID'ler"))
        self.pid_edit = QTextEdit()
        self.pid_edit.setPlaceholderText("Virgülle ayır:\n1, 2, 3")
        self.pid_edit.setFixedHeight(70)
        v.addWidget(self.pid_edit)
        return c

    def _csv_card(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        v.addWidget(_sec("③ CSV Kayıt Yolu"))
        row = QHBoxLayout()
        self.csv_edit = QLineEdit()
        self.csv_edit.setPlaceholderText("panel_lengths.csv kayıt yolu…")
        b = QPushButton("Seç…")
        b.setObjectName("brw")
        b.setFixedHeight(36)
        b.clicked.connect(self._browse_csv)
        row.addWidget(self.csv_edit)
        row.addWidget(b)
        v.addLayout(row)
        return c

    def _table_card(self):
        c = _card()
        v = QVBoxLayout(c)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)
        v.addWidget(_sec("④ Sonuçlar"))
        self.table = QTableWidget(0, len(TABLE_KEYS))
        self.table.setHorizontalHeaderLabels(TABLE_HDRS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)
        return c

    # ── Dosya seçiciler ───────────────────────────────────────────────────────

    def _browse_bdf(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "BDF Dosyası Seç", "",
            "BDF Files (*.bdf *.dat *.nas *.pch);;All Files (*)"
        )
        if p:
            self.bdf_edit.setText(p)
            if not self.csv_edit.text():
                default_csv = os.path.splitext(p)[0] + "_panel_lengths.csv"
                self.csv_edit.setText(default_csv)

    def _browse_csv(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "CSV Kayıt Yeri", self.csv_edit.text() or "panel_lengths.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if p:
            self.csv_edit.setText(p)

    # ── Hesaplama ─────────────────────────────────────────────────────────────

    def _parse_pids(self):
        raw = self.pid_edit.toPlainText().replace(",", " ")
        return [int(t) for t in raw.split() if t.strip()]

    def _calc(self):
        bdf = self.bdf_edit.text().strip()
        if not bdf:
            QMessageBox.warning(self, "Eksik", "BDF dosyası seçin.")
            return
        try:
            pids = self._parse_pids()
        except ValueError:
            QMessageBox.warning(self, "Hata", "Property ID'ler tam sayı olmalı.")
            return
        if not pids:
            QMessageBox.warning(self, "Eksik", "En az bir property ID girin.")
            return

        self._rows.clear()
        self.table.setRowCount(0)
        self.btn_calc.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.prog.setVisible(True)
        self.prog.setMaximum(len(pids))
        self.prog.setValue(0)
        self.status.setText("Hesaplanıyor…")

        self._thread = QThread()
        self._worker = Worker(bdf, pids)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda c, t: self.prog.setValue(c))
        self._worker.row_done.connect(self._add_row)
        self._worker.err_done.connect(self._add_err)
        self._worker.finished.connect(self._done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _flat(self, res: dict) -> dict:
        d = {k: res[k] for k in ("property_id", "plane", "x_direction", "x_length", "y_length")}
        for lbl in BAR_LABELS:
            b = res["bars"][lbl]
            d[f"bar_prop_{lbl}"] = b["pid"]
            d[f"bar_dim1_{lbl}"] = b["dim1"]
            d[f"bar_dim2_{lbl}"] = b["dim2"]
        d["avg_dim1_x"] = res["avg_dim1_x"]
        d["avg_dim2_x"] = res["avg_dim2_x"]
        d["avg_dim1_y"] = res["avg_dim1_y"]
        d["avg_dim2_y"] = res["avg_dim2_y"]
        return d

    def _add_row(self, res: dict):
        row = self._flat(res)
        self._rows.append(row)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, key in enumerate(TABLE_KEYS):
            val = row.get(key)
            item = QTableWidgetItem("" if val is None else str(val))
            item.setTextAlignment(Qt.AlignCenter)
            if key == "x_length":
                item.setForeground(QColor(ACC2))
            elif key == "y_length":
                item.setForeground(QColor(GREEN))
            elif key.startswith("bar_prop") and val is not None:
                item.setForeground(QColor(AMBER))
            self.table.setItem(r, c, item)

    def _add_err(self, pid: int, msg: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QTableWidgetItem(f"PID {pid} — {msg}")
        it.setForeground(QColor(RED))
        self.table.setItem(r, 0, it)

    def _done(self):
        self.btn_calc.setEnabled(True)
        self.btn_export.setEnabled(bool(self._rows))
        self.prog.setVisible(False)
        err = self.table.rowCount() - len(self._rows)
        parts = [f"{len(self._rows)} başarılı"]
        if err:
            parts.append(f"{err} hatalı")
        self.status.setText("  ·  ".join(parts))

        # CSV yolu seçiliyse otomatik kaydet
        csv_path = self.csv_edit.text().strip()
        if csv_path and self._rows:
            self._write_csv(csv_path)
            self.status.setText(self.status.text() + f"  ·  Kaydedildi → {csv_path}")

    # ── CSV dışa aktarım ──────────────────────────────────────────────────────

    def _export(self):
        path = self.csv_edit.text().strip()
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "CSV Kaydet", "panel_lengths.csv",
                "CSV Files (*.csv);;All Files (*)"
            )
            if not path:
                return
            self.csv_edit.setText(path)
        self._write_csv(path)
        self.status.setText(f"Kaydedildi → {path}")

    def _write_csv(self, path: str):
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(CSV_HEADERS)
                for row in self._rows:
                    w.writerow([row.get(k, "") for k in CSV_KEYS])
        except Exception as e:
            QMessageBox.critical(self, "CSV Hatası", str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  BAŞLAT  (Spyder: F5 · Terminal: python panel_length_calculator.py)
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    win = App()
    win.show()
    try:
        app.exec_()
    except SystemExit:
        pass
