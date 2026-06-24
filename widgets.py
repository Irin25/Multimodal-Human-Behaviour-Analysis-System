import math
from PyQt6.QtWidgets import (
    QWidget, QLabel, QFrame, QPushButton,
    QVBoxLayout, QHBoxLayout, QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QLinearGradient, QRadialGradient,
    QPainterPath, QFont, QFontDatabase,
)
from PyQt6.QtCore import (
    pyqtSignal, Qt, QTimer, QPointF, QRectF, QPoint,
)

from visuals import MplCanvas

# ─────────────────────────────────────────────────────────────────────────────
#  PALETTE
# ─────────────────────────────────────────────────────────────────────────────
C_BG      = "#040810"
C_DEEP    = "#060c18"
C_ACCENT  = "#00D4FF"
C_ACCENT2 = "#66E5FF"
C_GREEN   = "#10B981"
C_AMBER   = "#F59E0B"
C_RED     = "#EF4444"
C_TEXT    = "#C8E6F8"
C_SUB     = "#4A7A9B"
C_MUTED   = "#1E3A52"

# Glass card fill — very low alpha for true glass effect
_GLASS_A  = (8,  18, 42,  30)
_GLASS_B  = (5,  12, 28,  40)
_RIM_HI   = (0, 212, 255,  90)
_RIM_DIM  = (0, 100, 160, 120)

# ─────────────────────────────────────────────────────────────────────────────
#  FONT FAMILIES — resolved at import time from what's actually loaded
# ─────────────────────────────────────────────────────────────────────────────
def _pick(candidates: list[str], fallback: str) -> str:
    available = QFontDatabase.families()
    for c in candidates:
        if c in available:
            return f"'{c}'"
    return fallback

# Called once after _load_fonts() in appmain.py runs
def _resolve_fonts():
    global F_DISPLAY, F_BODY, F_MONO
    F_DISPLAY = _pick(["Orbitron", "Rajdhani", "Audiowide"], "'Segoe UI', sans-serif")
    F_BODY    = _pick(["Exo 2", "Exo2", "Carlito", "Calibri", "Segoe UI"], "sans-serif")
    F_MONO    = _pick(["Share Tech Mono", "ShareTechMono", "Liberation Mono",
                        "Cascadia Code", "Consolas", "Courier New"], "monospace")

# Defaults (overwritten by _resolve_fonts once app + fonts are loaded)
F_DISPLAY = "'Orbitron', 'Segoe UI', sans-serif"
F_BODY    = "'Exo 2', 'Segoe UI', sans-serif"
F_MONO    = "'Share Tech Mono', 'Liberation Mono', 'Consolas', monospace"


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def glow(widget, radius=28, hex_color=C_ACCENT, alpha=45, ox=0, oy=3):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(radius)
    c = QColor(hex_color)
    c.setAlpha(alpha)
    fx.setColor(c)
    fx.setOffset(ox, oy)
    widget.setGraphicsEffect(fx)


def section_label(text: str, color: str = None) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: {color or C_SUB};
        font-family: {F_MONO};
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 3.5px;
        padding: 0 0 6px 2px;
        background: transparent;
    """)
    return lbl


def _paint_glass(p: QPainter, w: int, h: int,
                 radius: float = 12.0, accent_top: bool = False):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)

    fill = QLinearGradient(0, 0, w * 0.35, h)
    fill.setColorAt(0.0, QColor(*_GLASS_A))
    fill.setColorAt(0.5, QColor(6, 14, 35, 25))
    fill.setColorAt(1.0, QColor(*_GLASS_B))
    p.fillPath(path, fill)

    p.setPen(QPen(QColor(*_RIM_DIM), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)

    hi = QLinearGradient(0, 0, w * 0.55, h * 0.45)
    hi.setColorAt(0.0, QColor(*_RIM_HI))
    hi.setColorAt(0.5, QColor(0, 180, 230, 14))
    hi.setColorAt(1.0, QColor(0, 60, 100,  3))
    pen_hi = QPen()
    pen_hi.setBrush(hi)
    pen_hi.setWidth(1)
    p.setPen(pen_hi)
    p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), radius - 0.5, radius - 0.5)

    shimmer = QLinearGradient(0, 0, w, 0)
    for pos, a in [(0, 0), (0.25, 80), (0.5, 140), (0.75, 80), (1, 0)]:
        shimmer.setColorAt(pos, QColor(0, 212, 255, a))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shimmer)
    p.drawRoundedRect(QRectF(2, 1, w - 4, 3), 1, 1)

    if accent_top:
        acc = QLinearGradient(0, 0, w, 0)
        for pos, a in [(0, 0), (0.25, 130), (0.5, 200), (0.75, 130), (1, 0)]:
            acc.setColorAt(pos, QColor(0, 212, 255, a))
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(14, 0, w - 28, 2), 1, 1)


def _glass_frame(parent=None, radius=10.0, accent_top=False) -> QFrame:
    f = QFrame(parent)
    f.setStyleSheet("background: transparent;")

    def _pe(event, _f=f, _r=radius, _at=accent_top):
        q = QPainter(_f)
        _paint_glass(q, _f.width(), _f.height(), _r, _at)
        QFrame.paintEvent(_f, event)

    f.paintEvent = _pe
    return f


def make_chart_block(title: str, canvas: MplCanvas,
                     badge_id: str = None) -> QFrame:
    wrap = QFrame()
    wrap.setObjectName("ChartBlock")
    wrap.setStyleSheet("background: transparent;")
    v = QVBoxLayout(wrap)
    v.setContentsMargins(12, 10, 12, 8)
    v.setSpacing(5)

    hdr = QHBoxLayout()
    lbl = QLabel(title)
    lbl.setStyleSheet(f"""
        color: {C_MUTED};
        font-family: {F_MONO};
        font-size: 8px;
        letter-spacing: 2.5px;
        font-weight: 600;
        background: transparent;
    """)
    hdr.addWidget(lbl)
    hdr.addStretch()

    if badge_id:
        badge = QLabel("--")
        badge.setObjectName(badge_id)
        badge.setStyleSheet(f"""
            background: rgba(0,70,120,0.70);
            border: 1px solid rgba(0,212,255,0.22);
            border-radius: 9px;
            color: {C_ACCENT2};
            font-family: {F_MONO};
            font-size: 9px;
            font-weight: 700;
            padding: 2px 10px;
            letter-spacing: 1.5px;
        """)
        hdr.addWidget(badge)

    v.addLayout(hdr)
    v.addWidget(canvas)

    def _pe(event, _w=wrap):
        q = QPainter(_w)
        _paint_glass(q, _w.width(), _w.height(), 9.0)
        QFrame.paintEvent(_w, event)

    wrap.paintEvent = _pe
    return wrap


def _fresh_ax(canvas: MplCanvas):
    ax = canvas.axes
    ax.cla()
    ax.set_facecolor((0, 0, 0, 0))
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(left=False, bottom=False,
                   labelleft=False, labelbottom=False)
    ax.yaxis.grid(True, color="#091929", linewidth=0.4, alpha=0.9)
    ax.set_axisbelow(True)
    return ax


# ─────────────────────────────────────────────────────────────────────────────
#  GLASS CARD
# ─────────────────────────────────────────────────────────────────────────────
class GlassCard(QFrame):
    def __init__(self, parent=None, accent_top=False):
        super().__init__(parent)
        self._accent_top = accent_top
        self.setObjectName("GlassCard")
        self.setStyleSheet(
            "QFrame#GlassCard { background: transparent; border-radius: 14px; }"
        )
        glow(self, radius=50, hex_color=C_ACCENT, alpha=18, oy=8)

    def paintEvent(self, event):
        p = QPainter(self)
        _paint_glass(p, self.width(), self.height(), 14.0, self._accent_top)
        super().paintEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  METRIC PILL
# ─────────────────────────────────────────────────────────────────────────────
class MetricPill(QFrame):
    _STATUS_COLORS = {
        "ok":    C_GREEN,
        "warn":  C_AMBER,
        "alert": C_RED,
        "muted": C_MUTED,
        "live":  C_ACCENT,
    }

    def __init__(self, label_text: str, value_id: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._apply_dot(C_ACCENT)

        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)

        cap = QLabel(label_text)
        cap.setStyleSheet(f"""
            color: {C_MUTED};
            font-family: {F_MONO};
            font-size: 8px;
            letter-spacing: 2px;
            font-weight: 600;
            background: transparent;
        """)

        self.val_lbl = QLabel("--")
        self.val_lbl.setObjectName(value_id)
        self.val_lbl.setStyleSheet(f"""
            color: {C_TEXT};
            font-family: {F_BODY};
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: transparent;
        """)

        col.addStretch()
        col.addWidget(cap)
        col.addWidget(self.val_lbl)
        col.addStretch()
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(col)
        row.addStretch()

    def _apply_dot(self, color: str):
        self._dot.setStyleSheet(f"""
            background: {color};
            border-radius: 4px;
            border: 1px solid rgba(255,255,255,0.25);
        """)
        glow(self._dot, radius=10, hex_color=color, alpha=160, oy=0)

    def set_status(self, status: str):
        self._apply_dot(self._STATUS_COLORS.get(status, C_ACCENT))

    def paintEvent(self, event):
        p = QPainter(self)
        _paint_glass(p, self.width(), self.height(), 8.0)
        super().paintEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  ARC GAUGE
# ─────────────────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.label  = label
        self.color  = QColor(color)
        self._value = 0.0
        self.setMinimumSize(120, 96)

    def setValue(self, v: float):
        self._value = max(0.0, min(100.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W // 2, H - 10
        r = min(W, H * 2) // 2 - 8

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, W, H), 10, 10)
        fill = QLinearGradient(0, 0, W, H)
        fill.setColorAt(0, QColor(10, 22, 48, 100))
        fill.setColorAt(1, QColor(5, 12, 28, 110))
        p.fillPath(path, fill)
        p.setPen(QPen(QColor(*_RIM_DIM), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 10, 10)

        p.setPen(QPen(QColor(8, 20, 45, 200), 9,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 0 * 16, 180 * 16)

        if self._value > 0:
            deg  = max(6.0, self._value / 100.0 * 180.0)
            span = int(deg) * 16

            gc = QColor(self.color); gc.setAlpha(38)
            p.setPen(QPen(gc, 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 0 * 16, span)

            gc.setAlpha(70)
            p.setPen(QPen(gc, 13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 0 * 16, span)

            p.setPen(QPen(self.color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 0 * 16, span)

            bright = QColor(self.color).lighter(155); bright.setAlpha(200)
            p.setPen(QPen(bright, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r + 2), int(cy - r + 2),
                      r * 2 - 4, r * 2 - 4, 0 * 16, span)

        p.setPen(QColor(200, 235, 255, 230))
        p.setFont(QFont("Orbitron", 13, QFont.Weight.Bold))
        p.drawText(QRectF(cx - 36, cy - 32, 72, 32),
                   Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}%")

        p.setPen(QColor(C_SUB))
        p.setFont(QFont("Share Tech Mono", 7))
        p.drawText(QRectF(0, H - 15, W, 15),
                   Qt.AlignmentFlag.AlignCenter, self.label)


# ─────────────────────────────────────────────────────────────────────────────
#  HEAT BAR
# ─────────────────────────────────────────────────────────────────────────────
class HeatBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(10)

    def setValue(self, v: float):
        self._value = max(0, min(100, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setBrush(QColor(8, 22, 48, 180))
        p.setPen(QPen(QColor(0, 60, 100, 120), 1))
        p.drawRoundedRect(0, 0, W, H, 5, 5)
        if self._value <= 0:
            return
        fw = max(10, int(W * self._value / 100))
        c  = (QColor(C_RED)   if self._value >= 70 else
              QColor(C_AMBER) if self._value >= 30 else QColor(C_ACCENT))
        gc = QColor(c); gc.setAlpha(40)
        p.setBrush(gc); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, fw + 5, H, 5, 5)
        grad = QLinearGradient(0, 0, fw, 0)
        grad.setColorAt(0.0, c.darker(140))
        grad.setColorAt(0.6, c)
        grad.setColorAt(1.0, c.lighter(140))
        p.setBrush(grad)
        p.drawRoundedRect(0, 1, fw, H - 2, 4, 4)
        hi = QLinearGradient(0, 1, 0, H // 2)
        hi.setColorAt(0, QColor(255, 255, 255, 55))
        hi.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(hi)
        p.drawRoundedRect(1, 1, fw - 2, (H - 2) // 2, 3, 3)


# ─────────────────────────────────────────────────────────────────────────────
#  STRESS TIMELINE  — type field removed, status only
# ─────────────────────────────────────────────────────────────────────────────
class StressTimelineWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.events           = []
        self.session_duration = 120
        self.current_time     = 0
        self.setMinimumHeight(58)

    def add_event(self, stress_val: float, timestamp: float):
        """Add a stress event. type field removed — status only."""
        self.current_time = timestamp
        lvl = "high" if stress_val >= 85 else ("med" if stress_val >= 50 else "low")
        self.events.append({"time": timestamp, "val": stress_val, "status": lvl})
        self.update()

    def clear_events(self):
        self.events = []
        self.current_time = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        mg, bh = 40, 8
        pw = W - mg * 2
        yc = H // 2

        p.setPen(QPen(QColor(255, 255, 255, 6), 1))
        for i in range(7):
            p.drawLine(mg + i * pw // 6, yc - 20, mg + i * pw // 6, yc + 20)

        p.setBrush(QColor(6, 16, 38, 160))
        p.setPen(QPen(QColor(*_RIM_DIM), 1))
        p.drawRoundedRect(mg, yc - bh // 2, pw, bh, 4, 4)

        for e in self.events:
            if e["status"] != "high":
                continue
            x = mg + int(e["time"] / self.session_duration * pw)
            p.setPen(QPen(QColor(C_RED), 1.5))
            p.drawLine(x, yc - 14, x, yc + 14)
            rg = QRadialGradient(QPointF(x, yc), 13)
            rg.setColorAt(0, QColor(239, 68, 68, 70))
            rg.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(rg)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, yc), 13, 13)

        sx = mg + self.current_time / self.session_duration * pw
        if sx <= mg + pw:
            p.setPen(QPen(QColor(200, 230, 255, 110), 1))
            p.drawLine(int(sx), 6, int(sx), H - 6)
            p.setBrush(QColor(180, 225, 255))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(sx, yc), 3, 3)

        p.setPen(QColor(C_MUTED))
        p.setFont(QFont("Share Tech Mono", 6))
        p.drawText(QPoint(mg, H - 2), "00:00")
        m, s = divmod(self.session_duration, 60)
        p.drawText(QPoint(W - mg - 30, H - 2), f"{m:02d}:{s:02d}")


# ─────────────────────────────────────────────────────────────────────────────
#  CALIBRATION OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
class CalibrationOverlay(QWidget):
    calibrate_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arc_progress = 0.0
        self._arc_timer    = QTimer(self)
        self._arc_timer.timeout.connect(self._tick_arc)
        self._arc_step     = 0.0
        self._pulse        = 0.0
        self._pulse_dir    = 1
        self._pulse_timer  = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(40)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(26)

        self.ring_area = QWidget()
        self.ring_area.setFixedSize(140, 140)
        self.ring_area.paintEvent = self._paint_ring
        layout.addWidget(self.ring_area, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_lbl = QLabel("SYSTEM READY")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet(f"""
            color: {C_ACCENT2};
            font-family: {F_DISPLAY};
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 6px;
            background: transparent;
        """)

        self.sub_lbl = QLabel("Initialise biometric sensors before analysis begins")
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_lbl.setStyleSheet(f"""
            color: {C_SUB};
            font-family: {F_BODY};
            font-size: 11px;
            letter-spacing: 1px;
            background: transparent;
        """)

        self.calib_btn = QPushButton("START CALIBRATION")
        self.calib_btn.setFixedSize(310, 54)
        self.calib_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn_style(C_ACCENT)
        self.calib_btn.clicked.connect(self.calibrate_clicked)

        layout.addWidget(self.title_lbl)
        layout.addWidget(self.sub_lbl)
        layout.addWidget(self.calib_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _tick_pulse(self):
        self._pulse += 0.035 * self._pulse_dir
        if   self._pulse >= 1.0: self._pulse_dir = -1
        elif self._pulse <= 0.0: self._pulse_dir =  1
        self.ring_area.update()

    def _apply_btn_style(self, border_color: str):
        self.calib_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(0,80,130,0.75), stop:1 rgba(0,40,80,0.75));
                border: 1px solid {border_color};
                color: {C_ACCENT2};
                font-family: {F_DISPLAY};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 4px;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(0,130,180,0.80), stop:1 rgba(0,70,120,0.80));
                border-color: {C_ACCENT2};
            }}
            QPushButton:disabled {{
                border-color: {C_MUTED};
                color: {C_MUTED};
                background: rgba(4,12,26,0.5);
            }}
        """)

    def _paint_ring(self, _):
        p = QPainter(self.ring_area)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = 70; r = 54

        pa = int(18 + self._pulse * 42)
        rg = QRadialGradient(QPointF(cx, cy), r + 18)
        rg.setColorAt(0, QColor(0, 212, 255, pa))
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(rg)
        p.drawEllipse(QPointF(cx, cy), r + 18, r + 18)

        p.setPen(QPen(QColor(0, 50, 80, 120), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        for i in range(36):
            angle = math.radians(i * 10)
            x1 = cx + (r - 3) * math.cos(angle); y1 = cy - (r - 3) * math.sin(angle)
            x2 = cx + (r + 5) * math.cos(angle); y2 = cy - (r + 5) * math.sin(angle)
            ta = int(25 + self._arc_progress * 155)
            p.setPen(QPen(QColor(0, 212, 255, ta), 1))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        if self._arc_progress > 0:
            span = int(self._arc_progress * 360 * 16)
            gc = QColor(C_ACCENT); gc.setAlpha(50)
            p.setPen(QPen(gc, 18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 90 * 16, -span)
            p.setPen(QPen(QColor(C_ACCENT), 3,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, 90 * 16, -span)
            bright = QColor(C_ACCENT2); bright.setAlpha(210)
            p.setPen(QPen(bright, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(int(cx - r + 1), int(cy - r + 1),
                      r * 2 - 2, r * 2 - 2, 90 * 16, -span)

        rg2 = QRadialGradient(QPointF(cx, cy), 10)
        rg2.setColorAt(0,   QColor(160, 235, 255, 245))
        rg2.setColorAt(0.5, QColor(0, 212, 255, 180))
        rg2.setColorAt(1,   QColor(0, 80, 160, 90))
        p.setBrush(rg2); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 9, 9)

    def start_arc(self, duration_ms: int):
        self._arc_progress = 0.0
        ticks = duration_ms // 50
        self._arc_step = 1.0 / ticks if ticks else 1.0
        self._arc_timer.start(50)

    def _tick_arc(self):
        self._arc_progress = min(1.0, self._arc_progress + self._arc_step)
        self.ring_area.update()
        if self._arc_progress >= 1.0:
            self._arc_timer.stop()

    def set_phase(self, title: str, sub: str, btn_text: str, btn_color=None):
        self.title_lbl.setText(title)
        self.sub_lbl.setText(sub)
        self.calib_btn.setText(btn_text)
        if btn_color:
            self._apply_btn_style(btn_color)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(4, 8, 20, 225))
        rg = QRadialGradient(QPointF(W / 2, H / 2), max(W, H) * 0.55)
        rg.setColorAt(0, QColor(0, 50, 110, 30))
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(rg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(0, 0, W, H)


# ─────────────────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────────────────
class Header(QWidget):
    nav_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(62)
        self._nav_btns   = []
        self._active_tab = 0

        h = QHBoxLayout(self)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(0)

        # ── Logo: load image 106.png and tint cyan via Qt compositing ──────
        import os as _os
        from PyQt6.QtGui import QPixmap as _QPixmap

        def _make_logo_pixmap(size: int = 34):
            import glob as _glob
            _base = _os.path.dirname(_os.path.abspath(__file__))
            # Try exact names first, then glob for any png with "106" in name
            _candidates = [
                _os.path.join(_base, "image 106.png"),
                _os.path.join(_base, "image106.png"),
                _os.path.join(_base, "logo_cyan.png"),
                _os.path.join(_base, "image_106.png"),
                _os.path.join(_base, "image_106-removebg-preview.png"),
            ]
            # Also glob catch-all
            _candidates += _glob.glob(_os.path.join(_base, "*106*"))
            _candidates += _glob.glob(_os.path.join(_base, "*logo*"))

            for _p in _candidates:
                if _os.path.exists(_p):
                    print(f"[logo] Loading from: {_p}")
                    _src = _QPixmap(_p).scaled(
                        size, size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    _cyan = _QPixmap(_src.size())
                    _cyan.fill(QColor(0, 212, 255))
                    _pp = QPainter(_cyan)
                    _pp.setCompositionMode(
                        QPainter.CompositionMode.CompositionMode_DestinationIn
                    )
                    _pp.drawPixmap(0, 0, _src)
                    _pp.end()
                    return _cyan
            print(f"[logo] NOT FOUND in: {_base}")
            print(f"[logo] Files there: {_os.listdir(_base)[:20]}")
            return None

        logo = QLabel()
        logo.setFixedSize(42, 42)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _logo_pix = _make_logo_pixmap(34)
        if _logo_pix:
            logo.setPixmap(_logo_pix)
            logo.setStyleSheet("""
                background: rgba(0,20,50,0.70);
                border: 1px solid rgba(0,212,255,0.45);
                border-radius: 21px;
                padding: 4px;
            """)
        else:
            logo.setText("⬡")
            logo.setStyleSheet(f"""
                color: {C_ACCENT};
                font-size: 16px;
                border: 1px solid rgba(0,212,255,0.38);
                border-radius: 21px;
                background: qradialgradient(cx:0.4,cy:0.35,radius:0.7,
                    stop:0 rgba(0,60,100,0.92),stop:1 rgba(4,10,24,0.95));
            """)
        glow(logo, radius=22, hex_color=C_ACCENT, alpha=80, oy=0)

        title_block = QWidget()
        title_block.setFixedWidth(260)
        title_block.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        title_block.setStyleSheet("background: transparent;")
        tb = QVBoxLayout(title_block)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(2)

        t1 = QLabel("MHBAS")
        t1.setStyleSheet(f"""
            background: transparent;
            color: {C_TEXT};
            font-family: {F_DISPLAY};
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 5px;
        """)
        t2 = QLabel("MULTIMODAL HUMAN BEHAVIOUR ANALYSIS SYSTEM")
        t2.setStyleSheet(f"""
            background: transparent;
            color: {C_MUTED};
            font-family: {F_MONO};
            font-size: 7px;
            letter-spacing: 1px;
        """)
        tb.addWidget(t1)
        tb.addWidget(t2)

        left = QWidget()
        left.setFixedWidth(310)
        left.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        left.setStyleSheet("background: transparent;")
        lh = QHBoxLayout(left)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(10)
        lh.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lh.addWidget(logo)
        lh.addWidget(title_block)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        for i, label in enumerate(["Live", "Metrics", "Session", "Reports"]):
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._on_nav(idx))
            self._nav_btns.append(btn)
            nav.addWidget(btn)
        self._style_nav(0)

        chip_ss = f"""
            background: rgba(8,20,48,0.80);
            border: 1px solid rgba(0,212,255,0.14);
            border-radius: 14px;
            padding: 4px 14px;
            font-family: {F_MONO};
            font-size: 10px;
            letter-spacing: 1px;
        """
        self.fps_lbl = QLabel("FPS —")
        self.fps_lbl.setStyleSheet(chip_ss + f"color: {C_GREEN};")

        self.live_lbl = QLabel("● LIVE")
        self.live_lbl.setStyleSheet(chip_ss + f"color: {C_RED};")

        self.timer_lbl = QLabel()
        self.timer_lbl.setStyleSheet(chip_ss + f"""
            color: {C_ACCENT2};
            font-family: {F_DISPLAY};
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 2px;
        """)
        self.timer_lbl.hide()

        self._live_on = True
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._blink_live)
        self._live_timer.start(900)

        right = QWidget()
        right.setFixedWidth(280)
        right.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        right.setStyleSheet("background: transparent;")
        rh = QHBoxLayout(right)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(8)
        rh.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        rh.addWidget(self.fps_lbl)
        rh.addWidget(self.live_lbl)
        rh.addWidget(self.timer_lbl)

        h.addWidget(left)
        h.addStretch(1)
        h.addLayout(nav)
        h.addStretch(1)
        h.addWidget(right)

    def _blink_live(self):
        self._live_on = not self._live_on
        color = C_RED if self._live_on else C_MUTED
        self.live_lbl.setStyleSheet(f"""
            background: rgba(8,20,48,0.80);
            border: 1px solid rgba(0,212,255,0.14);
            border-radius: 14px;
            padding: 4px 14px;
            font-family: {F_MONO};
            font-size: 10px;
            letter-spacing: 1px;
            color: {color};
        """)

    def _on_nav(self, idx: int):
        self._active_tab = idx
        self._style_nav(idx)
        self.nav_changed.emit(idx)

    def _style_nav(self, active: int):
        for i, btn in enumerate(self._nav_btns):
            if i == active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                            stop:0 rgba(0,100,180,0.65),
                            stop:1 rgba(0,55,110,0.55));
                        border: 1px solid {C_ACCENT};
                        color: {C_ACCENT2};
                        border-radius: 16px;
                        padding: 0 22px;
                        font-family: {F_DISPLAY};
                        font-size: 10px;
                        font-weight: 700;
                        letter-spacing: 1px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                        color: {C_MUTED};
                        border-radius: 16px;
                        padding: 0 22px;
                        font-family: {F_BODY};
                        font-size: 11px;
                    }}
                    QPushButton:hover {{
                        background: rgba(0,80,140,0.22);
                        color: {C_TEXT};
                    }}
                """)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        fill = QLinearGradient(0, 0, 0, H)
        fill.setColorAt(0, QColor(8, 18, 46, 238))
        fill.setColorAt(1, QColor(4, 10, 28, 248))
        p.fillRect(0, 0, W, H, fill)
        shimmer = QLinearGradient(0, 0, W, 0)
        for pos, a in [(0, 0), (0.3, 38), (0.5, 60), (0.7, 38), (1, 0)]:
            shimmer.setColorAt(pos, QColor(0, 212, 255, a))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(shimmer)
        p.drawRect(0, 0, W, 2)
        bl = QLinearGradient(0, 0, W, 0)
        for pos, a in [(0, 0), (0.2, 100), (0.5, 165), (0.8, 100), (1, 0)]:
            bl.setColorAt(pos, QColor(0, 80, 140, a))
        p.setBrush(bl)
        p.drawRect(0, H - 1, W, 1)
        super().paintEvent(event)