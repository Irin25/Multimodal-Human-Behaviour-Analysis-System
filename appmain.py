import os
os.add_dll_directory(r'C:\MHBAS\venv\lib\site-packages\torch\lib')
import torch

import sys, os, time, math
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import (
    QPixmap, QFont, QPainter, QColor, QLinearGradient,
    QRadialGradient, QPainterPath, QPen, QFontDatabase,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF

from widgets import C_ACCENT, C_ACCENT2, C_SUB, C_MUTED, F_DISPLAY, F_BODY

from app import StressApp

#fonts

def _load_fonts() -> None:
    
    available = QFontDatabase.families()
    if "Orbitron" in available and "Exo 2" in available:
        print("[fonts] System fonts found — Orbitron & Exo 2 ready.")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir   = os.path.join(script_dir, "fonts")
    loaded = 0

    if os.path.isdir(font_dir):
        for fname in os.listdir(font_dir):
            if fname.lower().endswith((".ttf", ".otf")):
                path   = os.path.join(font_dir, fname)
                result = QFontDatabase.addApplicationFont(path)
                if result != -1:
                    loaded += 1
        if loaded:
            print(f"[fonts] Loaded {loaded} font(s) from local fonts/ folder.")
            return

    print("[fonts] WARNING: Orbitron/Exo 2 not found. Run install_fonts.py to install.")


#splash screen
def make_splash() -> QSplashScreen:
    W, H = 600, 360
    pix  = QPixmap(W, H)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, W, H), 22, 22)
    grad = QLinearGradient(0, 0, W * 0.5, H)
    grad.setColorAt(0, QColor(8, 18, 46, 250))
    grad.setColorAt(1, QColor(4,  8, 22, 255))
    p.fillPath(path, grad)

    for width, alpha in [(5, 6), (3, 18), (1, 62)]:
        p.setPen(QPen(QColor(0, 212, 255, alpha), width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(width/2, width/2, W - width, H - width), 22, 22)

    sh = QLinearGradient(0, 0, W, 0)
    for pos, a in [(0, 0), (0.35, 55), (0.5, 88), (0.65, 55), (1, 0)]:
        sh.setColorAt(pos, QColor(0, 212, 255, a))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(sh)
    p.drawRoundedRect(QRectF(0, 0, W, 2), 22, 22)

    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image 106.png")
    cx, cy_logo = W // 2, 90
    if os.path.exists(logo_path):
        logo_pix    = QPixmap(logo_path)
        logo_scaled = logo_pix.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
        lx = cx - logo_scaled.width() // 2
        p.setOpacity(0.85)
        p.drawPixmap(lx, cy_logo - 40, logo_scaled)
        p.setOpacity(1.0)
    else:
        rg = QRadialGradient(QPointF(cx, cy_logo), 90)
        rg.setColorAt(0, QColor(0, 212, 255, 28)); rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(rg); p.drawEllipse(QPointF(cx, cy_logo), 90, 90)
        for r2, alpha, lw in [(52, 12, 1.5), (36, 38, 1.5), (21, 78, 2)]:
            p.setPen(QPen(QColor(0, 212, 255, alpha), lw))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy_logo), r2, r2)
        rg2 = QRadialGradient(QPointF(cx, cy_logo), 9)
        rg2.setColorAt(0, QColor(175, 240, 255, 250))
        rg2.setColorAt(1, QColor(0, 212, 255, 170))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(rg2)
        p.drawEllipse(QPointF(cx, cy_logo), 8, 8)

    p.setPen(QColor(C_ACCENT2))
    p.setFont(QFont("Orbitron", 28, QFont.Weight.Bold))
    p.drawText(QRectF(0, 158, W, 60), Qt.AlignmentFlag.AlignCenter, "BehaviourAI")

    p.setPen(QColor(C_SUB))
    p.setFont(QFont("Exo 2", 10))
    p.drawText(QRectF(0, 218, W, 30), Qt.AlignmentFlag.AlignCenter,
               "Multimodal Analysis System  —  v1.0")

    bar_y = H - 40
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(8, 22, 50, 200))
    p.drawRoundedRect(QRectF(40, bar_y, W - 80, 4), 2, 2)
    pg = QLinearGradient(40, 0, W - 40, 0)
    pg.setColorAt(0, QColor(0, 212, 255, 200))
    pg.setColorAt(1, QColor(0, 212, 255, 60))
    p.setBrush(pg)
    p.drawRoundedRect(QRectF(40, bar_y, (W - 80) * 0.75, 4), 2, 2)

    p.setPen(QColor(C_MUTED))
    p.setFont(QFont("Exo 2", 8))
    p.drawText(QRectF(0, bar_y + 10, W, 24),
               Qt.AlignmentFlag.AlignCenter, "Initialising biometric sensors…")
    p.end()
    return QSplashScreen(pix, Qt.WindowType.FramelessWindowHint)


#entry point
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("BehaviourAI")

    _load_fonts()

    available = QFontDatabase.families()
    if "Exo 2" in available:
        app.setFont(QFont("Exo 2", 10))
    elif "Carlito" in available:
        app.setFont(QFont("Carlito", 10))
    elif "Calibri" in available:
        app.setFont(QFont("Calibri", 10))
    else:
        app.setFont(QFont("Segoe UI", 10))

    
    splash = make_splash()
    splash.show()
    app.processEvents()  # force splash to paint before anything else runs

    SPLASH_START = time.time()
    MIN_SPLASH   = 3.0

    window = StressApp()
    app.processEvents()  

    def _finish():
        remaining = MIN_SPLASH - (time.time() - SPLASH_START)
        if remaining > 0:
            QTimer.singleShot(
                int(remaining * 1000),
                lambda: (window.show(), splash.finish(window)),
            )
        else:
            window.show()
            splash.finish(window)

    QTimer.singleShot(0, _finish)
    sys.exit(app.exec())