import os, time
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFrame, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QSizePolicy,
)
from PyQt6.QtGui import (
    QColor, QFont,
)
from PyQt6.QtCore import Qt, QRectF

from widgets import (
    C_BG, C_DEEP, C_ACCENT, C_ACCENT2, C_GREEN, C_AMBER, C_RED,
    C_TEXT, C_SUB, C_MUTED,
    F_DISPLAY, F_BODY, F_MONO,
    GlassCard, StressTimelineWidget,
    glow, section_label, _glass_frame, make_chart_block, _fresh_ax,
)
from visuals import MplCanvas


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _page_scroll_wrap(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    sa.setStyleSheet("""
        QScrollArea { background: transparent; border: none; }
        QScrollBar:vertical {
            background: rgba(4,12,26,0.6); width: 4px; border-radius: 2px;
        }
        QScrollBar::handle:vertical {
            background: rgba(0,212,255,0.22); border-radius: 2px; min-height: 24px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """)
    return sa


def _stat_card(label: str, value: str, color: str = C_ACCENT2):
    f = _glass_frame(radius=10)
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 8, 14, 8)
    v.setSpacing(3)
    cap = QLabel(label)
    cap.setStyleSheet(f"""
        color: {C_MUTED};
        font-family: {F_MONO};
        font-size: 7px;
        letter-spacing: 2.5px;
        font-weight: 700;
        background: transparent;
    """)
    val = QLabel(value)
    val.setObjectName("stat_val")
    val.setWordWrap(False)
    val.setStyleSheet(f"""
        color: {color};
        font-family: {F_DISPLAY};
        font-size: 14px;
        font-weight: 700;
        background: transparent;
    """)
    v.addWidget(cap)
    v.addWidget(val)
    return f, val


def _action_btn(text: str, color: str = C_ACCENT) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(44)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 rgba(0,90,160,0.80), stop:1 rgba(0,48,100,0.80));
            border: 1px solid {color};
            color: #ffffff;
            font-family: {F_DISPLAY};
            font-weight: 700;
            letter-spacing: 2px;
            border-radius: 9px;
            font-size: 10px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 rgba(0,130,200,0.90), stop:1 rgba(0,70,140,0.90));
            border-color: {C_ACCENT2};
        }}
        QPushButton:disabled {{
            background: rgba(20,40,70,0.35);
            border: 1px solid rgba(0,212,255,0.10);
            color: {C_MUTED};
        }}
    """)
    return btn


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE 1 — METRICS
# ─────────────────────────────────────────────────────────────────────────────
class MetricsPage(QWidget):
    """
    Post-session analytics page.
    Public API:
        update_summary(events, stress_history, attn_avg, peak_stress,
                       peak_ts, longest_streak, high_stress_secs,
                       avg_blink, session_date)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        inner.setStyleSheet("background: transparent;")
        
        root = QVBoxLayout(inner)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        hdg = QLabel("SESSION METRICS")
        hdg.setStyleSheet(f"""
            color: {C_ACCENT2}; font-family: {F_DISPLAY};
            font-size: 18px; font-weight: 700; letter-spacing: 5px;
            background: transparent;
        """)
        root.addWidget(hdg)

        sub = QLabel("Post-session biometric analytics — populated after recording ends.")
        sub.setStyleSheet(
            f"color: {C_SUB}; font-family: {F_MONO}; font-size: 9px; "
            f"letter-spacing: 1px; background: transparent;"
        )
        root.addWidget(sub)

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(10)
        tile_defs = [
            ("SESSION DATE",     "—",     C_ACCENT2),
            ("PEAK STRESS",      "—%",    C_RED),
            ("HIGH STRESS TIME", "—s",    C_AMBER),
            ("LONGEST STREAK",   "—s",    C_AMBER),
            ("AVG ATTENTION",    "—%",    C_GREEN),
            ("AVG BLINK RATE",   "—/min", C_ACCENT),
        ]
        self._stat_labels = {}
        for label, default, color in tile_defs:
            f, lbl = _stat_card(label, default, color)
            f.setFixedHeight(80)
            self._stat_labels[label] = lbl
            tiles_row.addWidget(f, stretch=1)
        root.addLayout(tiles_row)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.stress_canvas  = MplCanvas(self, width=6, height=2.8, dpi=90)
        self.emotion_canvas = MplCanvas(self, width=5, height=2.8, dpi=90)
        stress_block  = make_chart_block("STRESS LEVEL TIMELINE",     self.stress_canvas)
        emotion_block = make_chart_block("STRESS STATUS DISTRIBUTION", self.emotion_canvas)
        charts_row.addWidget(stress_block,  stretch=3)
        charts_row.addWidget(emotion_block, stretch=2)
        root.addLayout(charts_row)

        self._awaiting_lbl = QLabel(
            "⟳  No session data yet — start a recording session on the Live page."
        )
        self._awaiting_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._awaiting_lbl.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 11px; padding: 40px 0; background: transparent;
        """)
        root.addWidget(self._awaiting_lbl)
        root.addStretch()

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(_page_scroll_wrap(inner))

    def update_summary(self, *, events, stress_history, attn_avg, peak_stress,
                       peak_ts, longest_streak, high_stress_secs, avg_blink, session_date):
        self._awaiting_lbl.hide()
        self._stat_labels["SESSION DATE"].setText(session_date.split()[0])
        self._stat_labels["PEAK STRESS"].setText(f"{int(peak_stress)}%")
        self._stat_labels["HIGH STRESS TIME"].setText(f"{high_stress_secs}s")
        self._stat_labels["LONGEST STREAK"].setText(f"{longest_streak}s")
        self._stat_labels["AVG ATTENTION"].setText(f"{int(attn_avg)}%")
        self._stat_labels["AVG BLINK RATE"].setText(f"{avg_blink:.1f}/m")

        if stress_history:
            ax = _fresh_ax(self.stress_canvas)
            vals = list(stress_history)
            xs   = list(range(len(vals)))
            ax.fill_between(xs, vals, color=C_ACCENT, alpha=0.18, linewidth=0)
            ax.plot(xs, vals, color=C_ACCENT, linewidth=1.4, alpha=0.9)
            ax.axhline(85, color=C_RED, linewidth=0.8, linestyle="--", alpha=0.55)
            ax.set_ylim(0, 105)
            self.stress_canvas.fig.tight_layout(pad=0)
            self.stress_canvas.draw()

        if events:
            ax2 = _fresh_ax(self.emotion_canvas)
            statuses = [e["status"] for e in events]
            counts   = {
                "high":   statuses.count("high"),
                "medium": statuses.count("medium"),
                "low":    statuses.count("low"),
            }
            colors = [C_RED, C_AMBER, C_GREEN]
            labels = [f"High\n{counts['high']}", f"Med\n{counts['medium']}", f"Low\n{counts['low']}"]
            vals2  = [counts["high"], counts["medium"], counts["low"]]
            if sum(vals2) > 0:
                wedges, _ = ax2.pie(
                    vals2, colors=colors, startangle=90,
                    wedgeprops=dict(width=0.55, edgecolor="#040810", linewidth=1.5),
                )
                ax2.legend(wedges, labels, loc="center left", bbox_to_anchor=(0.85, 0.5),
                           frameon=False, labelcolor=C_SUB,
                           prop={"family": "monospace", "size": 7})
            else:
                # session ended with zero events — show a placeholder instead of blank axes
                ax2.text(0.5, 0.5, "No data", ha="center", va="center",
                         transform=ax2.transAxes, color=C_MUTED,
                         fontfamily="monospace", fontsize=9)
            self.emotion_canvas.fig.tight_layout(pad=0)
            self.emotion_canvas.draw()


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE 2 — SESSION
# ─────────────────────────────────────────────────────────────────────────────
class SessionPage(QWidget):
    """
    Full session view: live-feed stress timeline + post-session clinical
    assessment block + fused dominant emotion badge.

    Public API (all called from app.py):
        self.stress_timeline              — StressTimelineWidget fed by app.py
        set_recordings(count)
        update_session(elapsed, alerts, is_recording, stress, attn)
        update_fused_emotion(face, audio)
        set_assessment(headline, color, high_pct, alert_count, attn_avg)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        # ── Heading row ──────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdg = QLabel("SESSION OVERVIEW")
        hdg.setStyleSheet(f"""
            color: {C_ACCENT2}; font-family: {F_DISPLAY};
            font-size: 18px; font-weight: 700; letter-spacing: 5px;
            background: transparent;
        """)
        hdr_row.addWidget(hdg)
        hdr_row.addStretch()

        self._rec_count_lbl = QLabel("REC #0")
        self._rec_count_lbl.setStyleSheet(f"""
            background: rgba(0,70,120,0.55);
            border: 1px solid rgba(0,212,255,0.22);
            border-radius: 10px;
            color: {C_ACCENT2}; font-family: {F_MONO};
            font-size: 9px; font-weight: 700;
            padding: 3px 12px; letter-spacing: 1.5px;
        """)
        hdr_row.addWidget(self._rec_count_lbl)
        root.addLayout(hdr_row)

        # ── Live status pills ─────────────────────────────────────────────────
        live_row = QHBoxLayout()
        live_row.setSpacing(10)

        pill_defs = [
            ("ELAPSED",       "00:00",   C_ACCENT2, "_live_elapsed"),
            ("STRESS",        "—%",      C_RED,     "_live_stress"),
            ("ATTENTION",     "—%",      C_GREEN,   "_live_attn"),
            ("ALERTS",        "0",       C_AMBER,   "_live_alerts"),
            ("FACE EMOTION",  "—",       C_SUB,     "_live_face_emo"),
            ("AUDIO EMOTION", "—",       C_SUB,     "_live_audio_emo"),
        ]
        for label, default, color, attr in pill_defs:
            f, lbl = _stat_card(label, default, color)
            f.setFixedHeight(58)
            setattr(self, attr, lbl)
            live_row.addWidget(f, stretch=1)
        root.addLayout(live_row)

        # ── Full stress timeline ──────────────────────────────────────────────
        tl_card = GlassCard(accent_top=True)
        tl_v = QVBoxLayout(tl_card)
        tl_v.setContentsMargins(16, 14, 16, 14)
        tl_v.setSpacing(8)
        tl_v.addWidget(section_label("FULL SESSION STRESS TIMELINE"))
        self.stress_timeline = StressTimelineWidget()
        self.stress_timeline.setMinimumHeight(90)
        tl_v.addWidget(self.stress_timeline)
        root.addWidget(tl_card)

        # ── Assessment block ──────────────────────────────────────────────────
        self._assess_card = GlassCard()
        av = QVBoxLayout(self._assess_card)
        av.setContentsMargins(20, 18, 20, 18)
        av.setSpacing(12)
        av.addWidget(section_label("CLINICAL ASSESSMENT"))

        self._headline_lbl = QLabel("Awaiting session completion…")
        self._headline_lbl.setWordWrap(True)
        self._headline_lbl.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 11px; font-weight: 700;
            letter-spacing: 2px; padding: 6px 0;
            background: transparent;
        """)
        av.addWidget(self._headline_lbl)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        sd = [
            ("HIGH STRESS %", "—", C_RED),
            ("TOTAL ALERTS",  "—", C_AMBER),
            ("AVG ATTENTION", "—", C_GREEN),
        ]
        self._assess_stats = {}
        for lbl, default, color in sd:
            f, ref = _stat_card(lbl, default, color)
            f.setFixedHeight(72)
            self._assess_stats[lbl] = ref
            stats_row.addWidget(f, stretch=1)
        av.addLayout(stats_row)
        root.addWidget(self._assess_card)

        # ── Session Summary Panel ───────────────────────────────────────────────
        self._replay_card = GlassCard()
        self._replay_card.hide()
        rv = QVBoxLayout(self._replay_card)
        rv.setContentsMargins(20, 16, 20, 16)
        rv.setSpacing(10)

        replay_hdr = QHBoxLayout()
        replay_hdr.addWidget(section_label("SESSION SUMMARY"))
        replay_hdr.addStretch()

        self._next_session_pill = QLabel("NEXT SESSION  —")
        self._next_session_pill.setStyleSheet(f"""
            background: rgba(0,70,120,0.55);
            border: 1px solid rgba(0,212,255,0.22);
            border-radius: 10px;
            color: {C_ACCENT2}; font-family: {F_MONO};
            font-size: 9px; font-weight: 700;
            padding: 3px 12px; letter-spacing: 1.5px;
        """)
        replay_hdr.addWidget(self._next_session_pill)
        rv.addLayout(replay_hdr)

        self._reports_nudge = QLabel(
            "Full clinical report, event log export and CSV download  →  Reports tab"
        )
        self._reports_nudge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reports_nudge.setStyleSheet(f"""
            color: {C_ACCENT}; font-family: {F_MONO};
            font-size: 9px; letter-spacing: 1px;
            padding: 6px 0 0 0; background: transparent;
            border-top: 1px solid rgba(0,212,255,0.10);
        """)
        rv.addWidget(self._reports_nudge)

        root.addWidget(self._replay_card)
        root.addStretch()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_recordings(self, count: int):
        self._rec_count_lbl.setText(f"REC #{count}")

    def update_session(self, elapsed: int, alert_count: int,
                       is_recording: bool, stress: float, attn: float):
        m, s = divmod(elapsed, 60)
        self._live_elapsed.setText(f"{m:02d}:{s:02d}")
        self._live_stress.setText(f"{int(stress)}%")
        self._live_attn.setText(f"{int(attn)}%")
        self._live_alerts.setText(str(alert_count))

        if stress >= 85:
            self._live_stress.setStyleSheet(
                f"color: {C_RED}; font-family: {F_DISPLAY}; font-size: 14px; font-weight: 700; background: transparent;")
        elif stress >= 55:
            self._live_stress.setStyleSheet(
                f"color: {C_AMBER}; font-family: {F_DISPLAY}; font-size: 14px; font-weight: 700; background: transparent;")
        else:
            self._live_stress.setStyleSheet(
                f"color: {C_GREEN}; font-family: {F_DISPLAY}; font-size: 14px; font-weight: 700; background: transparent;")

    def update_live_emotions(self, face_emo: str, audio_emo: str):
        """Update raw emotion pills on the live status row."""
        def _short(s: str, maxlen: int = 10) -> str:
            s = s.upper().strip()
            if len(s) <= maxlen:
                return s
            first = s.split()[0]
            return first[:maxlen]

        self._live_face_emo.setText(_short(face_emo))
        self._live_audio_emo.setText(_short(audio_emo))

    def set_assessment(self, *, headline: str, color: str,
                       high_pct: float, alert_count: int, attn_avg: float):
        self._headline_lbl.setText(headline)
        self._headline_lbl.setStyleSheet(f"""
            color: {color}; font-family: {F_MONO};
            font-size: 11px; font-weight: 700;
            letter-spacing: 2px; padding: 6px 0;
            background: transparent;
        """)
        self._assess_stats["HIGH STRESS %"].setText(f"{int(high_pct)}%")
        self._assess_stats["TOTAL ALERTS"].setText(str(alert_count))
        self._assess_stats["AVG ATTENTION"].setText(f"{int(attn_avg)}%")

        # Populate replay panel
        if high_pct > 60:
            next_txt, pill_color = "NEXT SESSION  IN 24 h", C_RED
        elif high_pct >= 30:
            next_txt, pill_color = "NEXT SESSION  IN 48 h", C_AMBER
        else:
            next_txt, pill_color = "NEXT SESSION  IN 1 WK", C_GREEN

        self._next_session_pill.setText(next_txt)
        self._next_session_pill.setStyleSheet(f"""
            background: rgba(0,70,120,0.55);
            border: 1px solid {pill_color}55;
            border-radius: 10px;
            color: {pill_color}; font-family: {F_MONO};
            font-size: 9px; font-weight: 700;
            padding: 3px 12px; letter-spacing: 1.5px;
        """)

        self._replay_card.show()


# ─────────────────────────────────────────────────────────────────────────────
#  PAGE 3 — REPORTS
# ─────────────────────────────────────────────────────────────────────────────
class ReportsPage(QWidget):
    """
    Export & report page.

    Public API:
        set_session_meta(date, duration, total_events, csv_path)
        set_assessment(text, color, treatment)
        add_event(QListWidgetItem)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._csv_path   = ""
        self._assess_txt = ""
        self._treat_txt  = ""

        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        inner.setStyleSheet("background: transparent;")
        
        root = QVBoxLayout(inner)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        hdg = QLabel("SESSION REPORTS")
        hdg.setStyleSheet(f"""
            color: {C_ACCENT2}; font-family: {F_DISPLAY};
            font-size: 18px; font-weight: 700; letter-spacing: 5px;
            background: transparent;
        """)
        root.addWidget(hdg)

        sub = QLabel("Session data, event log export, and assessment report.")
        sub.setStyleSheet(
            f"color: {C_SUB}; font-family: {F_MONO}; font-size: 9px; "
            f"letter-spacing: 1px; background: transparent;"
        )
        root.addWidget(sub)

        # Meta tiles
        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        meta_defs = [
            ("DATE",          "—", C_ACCENT2),
            ("DURATION",      "—", C_ACCENT),
            ("TOTAL EVENTS",  "—", C_AMBER),
            ("CSV DATA FILE", "—", C_GREEN),
        ]
        self._meta_labels = {}
        for label, default, color in meta_defs:
            f, lbl = _stat_card(label, default, color)
            f.setFixedHeight(80)
            self._meta_labels[label] = lbl
            meta_row.addWidget(f, stretch=1)
        root.addLayout(meta_row)

        # Assessment summary
        assess_card = GlassCard()
        av = QVBoxLayout(assess_card)
        av.setContentsMargins(20, 16, 20, 16)
        av.setSpacing(8)
        av.addWidget(section_label("ASSESSMENT SUMMARY"))

        self._assess_lbl = QLabel("Session not yet complete.")
        self._assess_lbl.setWordWrap(True)
        self._assess_lbl.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 10px; letter-spacing: 1.5px; padding: 4px 0;
            background: transparent;
        """)
        av.addWidget(self._assess_lbl)

        self._treat_lbl = QLabel("")
        self._treat_lbl.setWordWrap(True)
        self._treat_lbl.setStyleSheet(f"""
            color: {C_SUB}; font-family: {F_MONO};
            font-size: 10px; line-height: 155%; background: transparent;
        """)
        av.addWidget(self._treat_lbl)
        root.addWidget(assess_card)

        # Event log mirror
        log_card = GlassCard()
        lv = QVBoxLayout(log_card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        lv.addWidget(section_label("BEHAVIOURAL EVENT LOG"))

        self.event_log = QListWidget()
        self.event_log.setStyleSheet(f"""
            QListWidget {{
                background: rgba(6,16,38,0.55);
                border: 1px solid rgba(0,212,255,0.15);
                border-radius: 9px; color: {C_TEXT};
                font-family: {F_MONO}; font-size: 10px; padding: 5px;
            }}
            QListWidget::item {{
                padding: 5px 6px;
                border-bottom: 1px solid rgba(0,60,100,0.25);
                border-radius: 3px;
                background: transparent;
            }}
            QListWidget::item:selected {{ background: rgba(0,90,160,0.32); }}
            QListWidget::item:hover    {{ background: rgba(0,60,110,0.18); }}
        """)
        self.event_log.setMinimumHeight(180)
        self.event_log.addItem("No events yet — complete a recording session.")
        lv.addWidget(self.event_log)
        root.addWidget(log_card)

        # Export buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_save_report = _action_btn("💾  SAVE REPORT AS TXT", C_ACCENT)
        self._btn_save_report.setEnabled(False)
        self._btn_save_report.clicked.connect(self._save_report_txt)

        self._btn_save_csv = _action_btn("📁  SAVE CSV AS…", C_AMBER)
        self._btn_save_csv.setEnabled(False)
        self._btn_save_csv.clicked.connect(self._save_csv_as)

        self._btn_open_csv = _action_btn("📂  OPEN CSV", C_GREEN)
        self._btn_open_csv.setEnabled(False)
        self._btn_open_csv.clicked.connect(self._open_csv)

        btn_row.addWidget(self._btn_save_report)
        btn_row.addWidget(self._btn_save_csv)
        btn_row.addWidget(self._btn_open_csv)
        root.addLayout(btn_row)
        root.addStretch()

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(_page_scroll_wrap(inner))

    # Public API

    def set_session_meta(self, *, date: str, duration: str,
                         total_events: int, csv_path: str):
        self._csv_path = csv_path
        self._meta_labels["DATE"].setText(date.split()[0])
        self._meta_labels["DURATION"].setText(duration)
        self._meta_labels["TOTAL EVENTS"].setText(str(total_events))
        fname = os.path.basename(csv_path) if csv_path else "—"
        self._meta_labels["CSV DATA FILE"].setText(
            fname[:22] + "…" if len(fname) > 24 else fname
        )
        self._btn_save_report.setEnabled(True)
        if csv_path and os.path.exists(csv_path):
            self._btn_save_csv.setEnabled(True)
            self._btn_open_csv.setEnabled(True)

    def set_assessment(self, text: str, color: str, treatment: str):
        self._assess_txt = text
        self._treat_txt  = treatment
        self._assess_lbl.setText(text)
        self._assess_lbl.setStyleSheet(f"""
            color: {color}; font-family: {F_MONO};
            font-size: 10px; letter-spacing: 1.5px; padding: 4px 0;
            background: transparent;
        """)
        self._treat_lbl.setText(treatment)

    def add_event(self, item: QListWidgetItem):
        if (self.event_log.count() == 1 and
                self.event_log.item(0).text().startswith("No events yet")):
            self.event_log.clear()
        clone = QListWidgetItem(item.text())
        clone.setForeground(item.foreground())
        self.event_log.addItem(clone)
        self.event_log.scrollToBottom()

    # Private actions

    def _save_report_txt(self):
        default_name = f"BehaviourAI_Report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report", default_name, "Text Files (*.txt)"
        )
        if not path:
            return
        lines = [
            "=" * 70,
            "  BehaviourAI — SESSION REPORT",
            f"  Generated: {time.strftime('%Y-%m-%d  %H:%M:%S')}",
            "=" * 70, "",
            "ASSESSMENT", "-" * 50,
            self._assess_txt, "",
            self._treat_txt, "",
            "BEHAVIOURAL EVENT LOG", "-" * 50,
        ]
        for i in range(self.event_log.count()):
            lines.append(self.event_log.item(i).text())
        lines += ["", "=" * 70]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError as exc:
            print(f"[ReportsPage] Could not save report: {exc}")

    def _save_csv_as(self):
        if not self._csv_path or not os.path.exists(self._csv_path):
            return
        default_name = f"BehaviourAI_Session_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV As", default_name, "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            import shutil
            shutil.copy2(self._csv_path, path)
        except OSError as exc:
            print(f"[ReportsPage] Could not copy CSV: {exc}")

    def _open_csv(self):
        # open the session's own CSV directly — no picker needed
        path = self._csv_path
        if not path or not os.path.exists(path):
            return
        import subprocess, sys
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])