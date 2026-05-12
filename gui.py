"""
Panel Length Calculator — Desktop GUI
Run directly in Spyder (F5) or terminal: python gui.py
"""

import sys
import csv
import io
import threading

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QSizePolicy, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

from panel_length_calculator import compute_panel_lengths

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#0f1117"
CARD     = "#1a1d2e"
BORDER   = "#2e3250"
ACCENT   = "#5c6bc0"
ACCENT2  = "#7986cb"
TEXT     = "#e8eaf6"
SUBTEXT  = "#8892b0"
GREEN    = "#66bb6a"
RED      = "#fc8181"
AMBER    = "#ffa726"

STYLE = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel#sub {{
    color: {SUBTEXT};
    font-size: 11px;
}}
QLabel#title {{
    color: {TEXT};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#section {{
    color: {SUBTEXT};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}}

/* File row */
QLineEdit {{
    background: {CARD};
    border: 1.5px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
    font-size: 13px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QTextEdit {{
    background: {CARD};
    border: 1.5px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    color: {TEXT};
    font-size: 13px;
}}
QTextEdit:focus {{
    border-color: {ACCENT};
}}

/* Buttons */
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {ACCENT}, stop:1 #3f51b5);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 {ACCENT2}, stop:1 {ACCENT});
}}
QPushButton#primary:disabled {{
    background: #2a2d3e;
    color: {SUBTEXT};
}}

QPushButton#secondary {{
    background: {CARD};
    color: {ACCENT2};
    border: 1.5px solid {ACCENT};
    border-radius: 8px;
    padding: 10px 22px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#secondary:hover {{
    background: #252840;
    color: white;
}}
QPushButton#secondary:disabled {{
    color: {SUBTEXT};
    border-color: {BORDER};
}}

QPushButton#browse {{
    background: {CARD};
    color: {ACCENT2};
    border: 1.5px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#browse:hover {{
    border-color: {ACCENT};
    color: white;
}}

/* Table */
QTableWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    color: {TEXT};
    font-size: 12px;
    selection-background-color: #252840;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border: none;
}}
QTableWidget::item:selected {{
    background: #252840;
    color: {TEXT};
}}
QHeaderView::section {{
    background: #1e2130;
    color: {SUBTEXT};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}

/* Progress */
QProgressBar {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 6px;
}}

/* Scrollbar */
QScrollBar:vertical {{
    background: {BG};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


# ── Worker thread ─────────────────────────────────────────────────────────────

class Worker(QObject):
    progress = pyqtSignal(int, int)   # current, total
    result   = pyqtSignal(dict)       # one result row
    error    = pyqtSignal(int, str)   # pid, message
    finished = pyqtSignal()

    def __init__(self, bdf_path, pids):
        super().__init__()
        self.bdf_path = bdf_path
        self.pids     = pids

    def run(self):
        for i, pid in enumerate(self.pids):
            try:
                res = compute_panel_lengths(self.bdf_path, pid)
                self.result.emit(res)
            except Exception as e:
                self.error.emit(pid, str(e))
            self.progress.emit(i + 1, len(self.pids))
        self.finished.emit()


# ── Card widget ───────────────────────────────────────────────────────────────

def card(parent=None):
    f = QFrame(parent)
    f.setStyleSheet(f"""
        QFrame {{
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: 12px;
        }}
    """)
    return f


def section_label(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    BAR_LABELS = ["x1", "x2", "y1", "y2"]

    COLUMNS = (
        ["property_id", "plane", "x_direction", "x_length", "y_length"]
        + [f"bar_prop_{l}" for l in BAR_LABELS]
        + [f"bar_dim1_{l}" for l in BAR_LABELS]
        + [f"bar_dim2_{l}" for l in BAR_LABELS]
    )

    COL_HEADERS = (
        ["Property ID", "Plane", "X Dir", "X Length\n(mm)", "Y Length\n(mm)"]
        + [f"Bar PID\n{l.upper()}" for l in BAR_LABELS]
        + [f"Dim1\n{l.upper()}"   for l in BAR_LABELS]
        + [f"Dim2\n{l.upper()}"   for l in BAR_LABELS]
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Panel Length Calculator")
        self.resize(1300, 740)
        self.setStyleSheet(STYLE)
        self._rows = []
        self._thread = None
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(24, 20, 24, 20)
        main.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("📐  Panel Length Calculator")
        title.setObjectName("title")
        sub = QLabel("Nastran BDF → X / Y panel lengths + edge bar properties → CSV")
        sub.setObjectName("sub")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(sub, alignment=Qt.AlignBottom)
        main.addLayout(hdr)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {BORDER}; border: none;")
        main.addWidget(div)

        # Top row: file + IDs side by side
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(self._build_file_card(), 3)
        top.addWidget(self._build_pid_card(),  2)
        main.addLayout(top)

        # Action row
        act = QHBoxLayout()
        act.setSpacing(10)
        self.btn_calc   = QPushButton("▶  Calculate")
        self.btn_calc.setObjectName("primary")
        self.btn_calc.setFixedHeight(42)
        self.btn_export = QPushButton("⬇  Export CSV")
        self.btn_export.setObjectName("secondary")
        self.btn_export.setFixedHeight(42)
        self.btn_export.setEnabled(False)
        self.btn_calc.clicked.connect(self._on_calculate)
        self.btn_export.clicked.connect(self._on_export)
        act.addWidget(self.btn_calc,   3)
        act.addWidget(self.btn_export, 1)
        main.addLayout(act)

        # Progress
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        main.addWidget(self.progress)

        # Status
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("sub")
        main.addWidget(self.status_lbl)

        # Results table
        main.addWidget(self._build_table(), 1)

    def _build_file_card(self):
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(section_label("① BDF File"))
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Select a .bdf / .dat / .nas file…")
        self.file_edit.setReadOnly(True)
        btn = QPushButton("Browse…")
        btn.setObjectName("browse")
        btn.setFixedHeight(36)
        btn.clicked.connect(self._browse)
        row.addWidget(self.file_edit)
        row.addWidget(btn)
        lay.addLayout(row)
        return c

    def _build_pid_card(self):
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(section_label("② Property IDs"))
        self.pid_edit = QTextEdit()
        self.pid_edit.setPlaceholderText("1, 2, 3\nor one per line:\n1\n2\n3")
        self.pid_edit.setFixedHeight(90)
        lay.addWidget(self.pid_edit)
        return c

    def _build_table(self):
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        lay.addWidget(section_label("③ Results"))

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COL_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(False)
        lay.addWidget(self.table)
        return c

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select BDF file", "",
            "BDF Files (*.bdf *.dat *.nas *.pch);;All Files (*)"
        )
        if path:
            self.file_edit.setText(path)

    def _parse_pids(self):
        raw = self.pid_edit.toPlainText().replace(",", "\n")
        tokens = [t.strip() for t in raw.splitlines() if t.strip()]
        return [int(t) for t in tokens]

    def _on_calculate(self):
        bdf = self.file_edit.text().strip()
        if not bdf:
            QMessageBox.warning(self, "Missing file", "Please select a BDF file first.")
            return
        try:
            pids = self._parse_pids()
        except ValueError:
            QMessageBox.warning(self, "Invalid input", "Property IDs must be integers.")
            return
        if not pids:
            QMessageBox.warning(self, "Missing IDs", "Please enter at least one property ID.")
            return

        self._rows.clear()
        self.table.setRowCount(0)
        self.btn_calc.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(pids))
        self.progress.setValue(0)
        self.status_lbl.setText("Processing…")

        self._thread = QThread()
        self._worker = Worker(bdf, pids)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, current, total):
        self.progress.setValue(current)

    def _on_result(self, res):
        row_data = {
            "property_id": res["property_id"],
            "plane":       res["plane"],
            "x_direction": res["x_direction"],
            "x_length":    res["x_length"],
            "y_length":    res["y_length"],
        }
        for lbl in self.BAR_LABELS:
            b = res["bars"][lbl]
            row_data[f"bar_prop_{lbl}"]  = b["pid"]
            row_data[f"bar_dim1_{lbl}"]  = b["dim1"]
            row_data[f"bar_dim2_{lbl}"]  = b["dim2"]
        self._rows.append(row_data)
        self._add_table_row(row_data)

    def _on_error(self, pid, msg):
        r = self.table.rowCount()
        self.table.insertRow(r)
        err_item = QTableWidgetItem(f"PID {pid} — {msg}")
        err_item.setForeground(QColor(RED))
        self.table.setItem(r, 0, err_item)

    def _on_finished(self):
        self.btn_calc.setEnabled(True)
        self.btn_export.setEnabled(bool(self._rows))
        self.progress.setVisible(False)
        ok  = len(self._rows)
        err = self.table.rowCount() - ok
        parts = [f"{ok} OK"]
        if err:
            parts.append(f"{err} failed")
        self.status_lbl.setText("  ·  ".join(parts))

    def _add_table_row(self, data: dict):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, key in enumerate(self.COLUMNS):
            val = data.get(key)
            txt = "" if val is None else str(val)
            item = QTableWidgetItem(txt)
            item.setTextAlignment(Qt.AlignCenter)

            # Colour coding
            if key == "x_length":
                item.setForeground(QColor(ACCENT2))
            elif key == "y_length":
                item.setForeground(QColor(GREEN))
            elif key.startswith("bar_prop") and val is not None:
                item.setForeground(QColor(AMBER))

            self.table.setItem(r, c, item)

    # ── Export ────────────────────────────────────────────────────────────────

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "panel_lengths.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        csv_cols = (
            ["property_id", "x", "y"]
            + [f"bar_prop_{l}" for l in self.BAR_LABELS]
            + [f"bar_dim1_{l}" for l in self.BAR_LABELS]
            + [f"bar_dim2_{l}" for l in self.BAR_LABELS]
        )
        src_keys = (
            ["property_id", "x_length", "y_length"]
            + [f"bar_prop_{l}" for l in self.BAR_LABELS]
            + [f"bar_dim1_{l}" for l in self.BAR_LABELS]
            + [f"bar_dim2_{l}" for l in self.BAR_LABELS]
        )

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(csv_cols)
                for row in self._rows:
                    writer.writerow([row.get(k, "") for k in src_keys])
            self.status_lbl.setText(f"Saved → {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    # Spyder'da sys.exit çağrısı IDE'yi kapatır, bu yüzden exec_ sonucu yoksayılır
    try:
        app.exec_()
    except SystemExit:
        pass


if __name__ == "__main__":
    run()
