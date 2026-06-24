import sys, os, cv2, time, threading, csv, winsound
import numpy as np
from collections import deque

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QSizePolicy, QFileDialog,
)
from PyQt6.QtGui  import QImage, QPixmap, QFont, QIcon, QColor
from PyQt6.QtCore import pyqtSignal, Qt, pyqtSlot, QTimer, QPointF

from video_worker import VideoWorker
from audio_worker import AudioWorker
from visuals      import MplCanvas
from widgets import (
    C_BG, C_DEEP, C_ACCENT, C_ACCENT2, C_GREEN, C_AMBER, C_RED,
    C_TEXT, C_SUB, C_MUTED,
    F_DISPLAY, F_BODY, F_MONO,
    GlassCard, MetricPill, ArcGauge, HeatBar,
    StressTimelineWidget, CalibrationOverlay, Header,
    glow, section_label, _glass_frame, make_chart_block, _fresh_ax,
)
from pages import MetricsPage, SessionPage, ReportsPage

#  GLOBAL STYLESHEET
GLOBAL_QSS = f"""
* {{
    font-family: 'Exo 2', 'Carlito', 'Segoe UI', sans-serif;
}}
QMainWindow {{
    background-color: {C_BG};
    color: {C_TEXT};
}}
QWidget {{
    color: {C_TEXT};
}}
QLabel {{
    background: transparent;
    color: {C_TEXT};
}}
QScrollBar:vertical {{
    background: rgba(4,12,26,0.9);
    width: 4px;
    border-radius: 2px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,212,255,0.22);
    border-radius: 2px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}
"""

#  MAIN WINDOW

class StressApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BehaviourAI — Multimodal Analysis System")
        self.showMaximized()
        self.setStyleSheet(GLOBAL_QSS)

        try:
            self.setWindowIcon(QIcon("image 114.png"))
        except Exception:
            pass

        # ── Runtime state ──────────────────────────────────────────────────
        self.calibration_finished        = False
        self.emotion_history             = deque(maxlen=100)
        self.stress_history              = deque(maxlen=100)
        self.last_face_data              = {}
        self.last_audio_data             = {}
        self.distraction_heat            = 0.0
        self.smoothed_attn               = 100.0
        self.smoothed_stress             = 0.0
        self.neg_frame_count             = 0
        self.gaze_frame_count            = 0
        self.gaze_away_start_time        = None
        self.gaze_alert_triggered        = False
        self.eye_closure_start_time      = None
        self.eye_closure_alert_triggered = False
        self.is_recording                = False
        self.record_file                 = None
        self.csv_writer                  = None
        self.start_time                  = None
        self.session_finished            = False
        self.elapsed_seconds             = 0
        self.last_alert_time             = 0
        self.ALERT_COOLDOWN              = 3.0
        self._alert_count                = 0
        self._recording_count            = 0
        self._calib_badge_visible        = False
        self._calib_badge_timer          = QTimer()
        self._calib_badge_timer.setSingleShot(True)
        self._calib_badge_timer.timeout.connect(self._hide_calib_badge)
        self._attn_accumulator: list     = []
        self._last_wave_color            = C_ACCENT
        self._last_waveform              = None
        self._stress_color               = C_GREEN

        # ── New state from checklist ───────────────────────────────────────
        self.total_session_seconds = 0
        self.high_stress_seconds   = 0
        self.blink_rate_accumulator: list = []
        self.peak_stress           = 0.0
        self.peak_stress_timestamp = 0
        self.current_high_streak   = 0
        self.longest_high_streak   = 0
        self.saved_csv_filename    = ""

        # burden timer — clock-based, 1 tick per second
        self.burden_timer = QTimer()
        self.burden_timer.timeout.connect(self.track_burden_tick)

        self._init_ui()

        self.video_thread = VideoWorker()
        self.video_thread.image_signal.connect(self.update_image)
        self.video_thread.data_signal.connect(self.update_stats)

        self.audio_thread = AudioWorker()
        self.audio_thread.audio_data_signal.connect(self.update_audio_stats)

        self.session_timer = QTimer()
        self.session_timer.timeout.connect(self.update_timer)

        self.video_thread.start()
        self.audio_thread.start()

   
    #  UI BUILD
   
    def _init_ui(self):
        root   = QWidget()
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        self.header = Header()
        self.header.nav_changed.connect(self._on_nav_change)
        root_v.addWidget(self.header)

        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(0,212,255,0.10);")
        root_v.addWidget(sep)

        self.main_stack = QStackedWidget()

        # Page 0 — Live (UNCHANGED)
        live_page = QWidget()
        body_h = QHBoxLayout(live_page)
        body_h.setContentsMargins(12, 12, 12, 12)
        body_h.setSpacing(10)
        self.left_panel   = self._build_left()
        self.center_panel = self._build_center()
        self.right_panel  = self._build_right()
        body_h.addWidget(self.left_panel,   stretch=1)
        body_h.addWidget(self.center_panel, stretch=2)
        body_h.addWidget(self.right_panel,  stretch=1)
        self.main_stack.addWidget(live_page)

        self.metrics_page = MetricsPage()
        self.session_page = SessionPage()
        self.reports_page = ReportsPage()
        self.main_stack.addWidget(self.metrics_page)
        self.main_stack.addWidget(self.session_page)
        self.main_stack.addWidget(self.reports_page)

        root_v.addWidget(self.main_stack, stretch=1)
        self.setCentralWidget(root)

        self._set_side_panels_visible(False)

    def _on_nav_change(self, idx: int):
        self.main_stack.setCurrentIndex(idx)

    def _set_side_panels_visible(self, visible: bool):
        self.left_panel.setVisible(visible)
        self.right_panel.setVisible(visible)

    # ── left panel
    def _build_left(self) -> QWidget:
        card = GlassCard(accent_top=True)
        v = QVBoxLayout(card)
        v.setContentsMargins(15, 15, 15, 15)
        v.setSpacing(10)
        v.addWidget(section_label("SIGNAL ANALYSIS"))

        self.audio_canvas   = MplCanvas(self)
        self.emotion_canvas = MplCanvas(self)
        self.stress_canvas  = MplCanvas(self)

        ab = make_chart_block("LIVE AUDIO WAVEFORM",     self.audio_canvas,   "badge-audio")
        eb = make_chart_block("FACE EMOTION CONFIDENCE", self.emotion_canvas, "badge-conf")
        sb = make_chart_block("STRESS LEVEL OVER TIME",  self.stress_canvas,  "badge-stress")
        v.addWidget(ab); v.addWidget(eb); v.addWidget(sb)

        self._audio_badge_lbl  = ab.findChild(QLabel, "badge-audio")
        self._conf_badge_lbl   = eb.findChild(QLabel, "badge-conf")
        self._stress_badge_lbl = sb.findChild(QLabel, "badge-stress")

        v.addStretch()
        return card

    # center panel
    def _build_center(self) -> QWidget:
        card = GlassCard(accent_top=True)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        ch = QWidget(); ch.setFixedHeight(40)
        chl = QHBoxLayout(ch); chl.setContentsMargins(18, 0, 18, 0)
        feed_lbl = QLabel("LIVE SENSOR FEED")
        feed_lbl.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 8px; font-weight: 700; letter-spacing: 3px;
        """)
        chl.addWidget(feed_lbl); chl.addStretch()
        ch.setStyleSheet(
            "background: transparent; border-bottom: 1px solid rgba(0,212,255,0.09);"
        )
        v.addWidget(ch)

        self.center_stack = QStackedWidget()

        self.calib_overlay = CalibrationOverlay()
        self.calib_overlay.calibrate_clicked.connect(self.start_calibration)
        self.center_stack.addWidget(self.calib_overlay)

        video_page = QWidget()
        vv = QVBoxLayout(video_page)
        vv.setContentsMargins(0, 0, 0, 0)
        vv.setSpacing(0)
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_label.setStyleSheet(f"background: {C_DEEP};")
        vv.addWidget(self.video_label, stretch=1)
        self.center_stack.addWidget(video_page)
        v.addWidget(self.center_stack, stretch=1)

        self.timeline_container = QWidget()
        self.timeline_container.setFixedHeight(88)
        tl = QVBoxLayout(self.timeline_container)
        tl.setContentsMargins(15, 6, 15, 6)
        tl.setSpacing(4)
        tl_lbl2 = QLabel("STRESS EVENT LOG")
        tl_lbl2.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 8px; letter-spacing: 2px;
        """)
        # compact live page timeline
        self.stress_timeline_live = StressTimelineWidget()
        tl.addWidget(tl_lbl2)
        tl.addWidget(self.stress_timeline_live)
        self.timeline_container.hide()
        v.addWidget(self.timeline_container)

        return card

    # right panel
    def _build_right(self) -> QWidget:
        card = GlassCard(accent_top=True)
        v = QVBoxLayout(card)
        v.setContentsMargins(15, 15, 15, 15)
        v.setSpacing(8)
        v.addWidget(section_label("BIOMETRICS"))

        pills_data = [
            ("FACE EMOTION",  "val-face-emo"),
            ("AUDIO EMOTION", "val-audio-emo"),
            ("EYE GAZE",      "val-gaze"),
            ("HEAD STATUS",   "val-head"),
            ("BLINK RATE",    "val-blink"),
        ]
        self._metric_pills = {}
        self._pill_objects = {}
        for cap, oid in pills_data:
            pill = MetricPill(cap, oid)
            self._metric_pills[oid] = pill.val_lbl
            self._pill_objects[oid] = pill
            v.addWidget(pill)

        gauges_wrap = _glass_frame(radius=10)
        gv = QVBoxLayout(gauges_wrap)
        gv.setContentsMargins(6, 6, 6, 6)
        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(8)
        self.attn_gauge   = ArcGauge("ATTENTION", C_ACCENT)
        self.stress_gauge = ArcGauge("STRESS",    C_RED)
        gauge_row.addWidget(self.attn_gauge)
        gauge_row.addWidget(self.stress_gauge)
        gv.addLayout(gauge_row)
        v.addWidget(gauges_wrap)

        heat_wrap = _glass_frame(radius=9)
        hv = QVBoxLayout(heat_wrap)
        hv.setContentsMargins(14, 12, 14, 12)
        hv.setSpacing(8)
        heat_hdr = QHBoxLayout()
        heat_cap = QLabel("DISTRACTION HEAT")
        heat_cap.setStyleSheet(f"""
            color: {C_MUTED}; font-family: {F_MONO};
            font-size: 8px; letter-spacing: 2px; font-weight: 600;
        """)
        self.heat_val_lbl = QLabel("0%")
        self.heat_val_lbl.setStyleSheet(f"""
            color: {C_ACCENT}; font-family: {F_DISPLAY};
            font-size: 13px; font-weight: 700;
        """)
        heat_hdr.addWidget(heat_cap); heat_hdr.addStretch()
        heat_hdr.addWidget(self.heat_val_lbl)
        self.heat_bar = HeatBar()
        hv.addLayout(heat_hdr); hv.addWidget(self.heat_bar)
        v.addWidget(heat_wrap)

        v.addWidget(section_label("BEHAVIOURAL EVENT LOG"))
        self.event_log = QListWidget()
        self.event_log.setStyleSheet(f"""
            QListWidget {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 rgba(6,16,38,0.96), stop:1 rgba(3,9,22,0.96));
                border: 1px solid rgba(0,212,255,0.15);
                border-radius: 9px;
                color: {C_TEXT};
                font-family: {F_MONO};
                font-size: 10px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 5px 6px;
                border-bottom: 1px solid rgba(0,60,100,0.35);
                border-radius: 3px;
            }}
            QListWidget::item:selected {{ background: rgba(0,90,160,0.32); }}
            QListWidget::item:hover    {{ background: rgba(0,60,110,0.18); }}
        """)
        self.event_log.addItem("Awaiting calibration…")
        self.event_log.setFixedHeight(155)
        v.addWidget(self.event_log)
        v.addStretch()

        from PyQt6.QtWidgets import QPushButton
        self.btn_record = QPushButton("● START RECORDING")
        self.btn_record.setFixedHeight(52)
        self.btn_record.setCheckable(True)
        self.btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_record_style(False)
        self.btn_record.clicked.connect(self.toggle_recording)
        v.addWidget(self.btn_record)
        return card

    def _set_record_style(self, recording: bool):
        if recording:
            self.btn_record.setStyleSheet(f"""
                QPushButton {{
                    background: {C_RED};
                    border: 1px solid {C_RED};
                    color: #ffffff;
                    font-family: {F_DISPLAY};
                    font-weight: 700;
                    letter-spacing: 3px;
                    border-radius: 9px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: #cc2020; border-color: #ff6666; }}
            """)
        else:
            self.btn_record.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 rgba(0,90,160,0.90), stop:1 rgba(0,48,100,0.90));
                    border: 1px solid {C_ACCENT};
                    color: #ffffff;
                    font-family: {F_DISPLAY};
                    font-weight: 700;
                    letter-spacing: 3px;
                    border-radius: 9px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 rgba(0,130,200,0.95), stop:1 rgba(0,70,140,0.95));
                    border-color: {C_ACCENT2};
                }}
            """)

    
    #  CALIBRATION
    
    def start_calibration(self):
        self.video_thread.calib_phase = 1
        self.audio_thread.calib_phase = 1
        self.calib_overlay.calib_btn.setEnabled(False)
        self.calib_overlay.set_phase(
            "CALIBRATING…",
            "Remain still and silent for 6 seconds",
            "PHASE 1: STAY STILL & SILENT",
            C_ACCENT,
        )
        self.calib_overlay.start_arc(6000)

    def _hide_calib_badge(self):
        self._calib_badge_visible = False

    
    #  BURDEN TICK — proper clock-based timeline feed (track_burden_tick)
    # ─────────────────────────────────────────────────────────────────────
    def track_burden_tick(self):
        """Fires every 1 second during recording. Feeds timeline + accumulators."""
        if not self.is_recording or self.session_finished:
            return

        self.total_session_seconds += 1

        stress = self.smoothed_stress

        # Peak stress tracking
        if stress > self.peak_stress:
            self.peak_stress           = stress
            self.peak_stress_timestamp = self.total_session_seconds

        # High stress streak tracking
        if stress >= 85:
            self.high_stress_seconds   += 1
            self.current_high_streak   += 1
            if self.current_high_streak > self.longest_high_streak:
                self.longest_high_streak = self.current_high_streak
        else:
            self.current_high_streak = 0

        # Blink rate accumulation
        blink = self.last_face_data.get("blink_rate", 0)
        if isinstance(blink, (int, float)) and blink > 0:
            self.blink_rate_accumulator.append(blink)

        # Feed BOTH timelines (live compact + session page full)
        self.stress_timeline_live.add_event(stress, self.total_session_seconds)
        self.session_page.stress_timeline.add_event(stress, self.total_session_seconds)

    #slots

    @pyqtSlot(np.ndarray)
    def update_image(self, cv_img):
        if not self.calibration_finished:
            return
        if self._calib_badge_visible:
            font = cv2.FONT_HERSHEY_SIMPLEX; fs, th = 0.35, 1
            tm, ts = "CALIBRATION: ", "COMPLETE"
            (w1, h1), _ = cv2.getTextSize(tm, font, fs, th)
            (w2,  _), _ = cv2.getTextSize(ts, font, fs, th)
            x, y, r = 18, 18, 7
            fw, fh = w1 + w2 + 24, h1 + 10
            ov = cv_img.copy(); col = (0, 0, 0)
            cv2.rectangle(ov, (x + r, y), (x + fw - r, y + fh), col, -1)
            cv2.rectangle(ov, (x, y + r), (x + fw, y + fh - r), col, -1)
            for cx2, cy2 in [(x+r,y+r),(x+fw-r,y+r),(x+r,y+fh-r),(x+fw-r,y+fh-r)]:
                cv2.circle(ov, (cx2, cy2), r, col, -1, cv2.LINE_AA)
            cv2.addWeighted(ov, 0.7, cv_img, 0.3, 0, cv_img)
            cv2.circle(cv_img, (x + 9, y + fh // 2), 3, (16, 185, 129), -1, cv2.LINE_AA)
            cv2.putText(cv_img, tm, (x+18, y+h1+5), font, fs, (130,220,200), th, cv2.LINE_AA)
            cv2.putText(cv_img, ts, (x+18+w1, y+h1+5), font, fs, (220,240,255), th, cv2.LINE_AA)

        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.video_label.setPixmap(
            QPixmap.fromImage(qt_img).scaled(
                self.video_label.width(), self.video_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @pyqtSlot(dict)
    def update_stats(self, data):
        if not self.calibration_finished:
            return

        fps = self.video_thread.fps
        self.header.fps_lbl.setText(f"FPS {int(fps):02d}" if fps > 0 else "FPS —")
        self.last_face_data = data

        # Pills
        face_emo = str(data.get("emotion", "--")).upper()
        self._metric_pills["val-face-emo"].setText(face_emo)

        gaze_val = data.get("gaze_position", "--")
        self._metric_pills["val-gaze"].setText(gaze_val)

        head_val = data.get("head_status", "--")
        if len(str(head_val)) > 22:
            head_val = str(head_val)[:20] + "…"
        self._metric_pills["val-head"].setText(head_val)

        blink = data.get("blink_rate", "--")
        self._metric_pills["val-blink"].setText(
            f"{blink}/min" if blink != "--" else "--/min"
        )

        # Dot colours
        emo_neg = face_emo in ("ANGRY", "FEAR", "SAD", "DISGUST")
        emo_pos = face_emo in ("HAPPY", "NEUTRAL")
        self._pill_objects["val-face-emo"].set_status(
            "alert" if emo_neg else ("ok" if emo_pos else "muted")
        )
        self._pill_objects["val-gaze"].set_status(
            "ok" if gaze_val == "CENTER" else ("warn" if gaze_val != "--" else "muted")
        )
        head_ok = ("HEAD NEUTRAL" in str(head_val) or "HEAD TILTED" in str(head_val))
        self._pill_objects["val-head"].set_status(
            "ok" if head_ok else ("warn" if head_val != "--" else "muted")
        )
        try:
            br = float(blink) if blink != "--" else 0
            self._pill_objects["val-blink"].set_status(
                "ok" if 8 <= br <= 25 else ("warn" if br < 8 else "alert")
            )
        except Exception:
            self._pill_objects["val-blink"].set_status("muted")

        # Gaze alert
        gaze = data.get("gaze_position", "CENTER")
        if gaze not in ("CENTER", "UNKNOWN"):
            if self.gaze_away_start_time is None:
                self.gaze_away_start_time = time.time()
            if (time.time() - self.gaze_away_start_time >= 6.0
                    and not self.gaze_alert_triggered):
                self.add_behavioral_event("ALERT: Prolonged Gaze Avoidance (>6s)")
                self.gaze_alert_triggered = True
        else:
            self.gaze_away_start_time = None
            self.gaze_alert_triggered = False

        heat = self.calculate_distraction_heat(data)
        self.heat_bar.setValue(heat)
        hc = C_RED if heat >= 70 else (C_AMBER if heat >= 30 else C_ACCENT)
        self.heat_val_lbl.setText(f"{int(heat)}%")
        self.heat_val_lbl.setStyleSheet(f"""
            color: {hc}; font-family: {F_DISPLAY};
            font-size: 13px; font-weight: 700;
        """)
        # Fire alert when distraction heat is very high during recording
        if (heat >= 85 and self.is_recording and not self.session_finished
                and time.time() - getattr(self, "_last_heat_alert", 0) > 8.0):
            self.add_behavioral_event("ALERT: High Distraction Heat (prolonged inattention)")
            self._last_heat_alert = time.time()

        attn = self.calculate_attention(data)
        self.attn_gauge.setValue(attn)
        self._attn_accumulator.append(attn)
        stress = self.calculate_stress(data, self.last_audio_data)
        self.update_stress_ui(stress)
        self.log_data(stress)

        conf = data.get("confidence", 0)
        self.emotion_history.append(conf)
        if self._conf_badge_lbl:
            self._conf_badge_lbl.setText(f"{int(conf)}%")
        ax = _fresh_ax(self.emotion_canvas)
        d  = list(self.emotion_history); x = np.arange(len(d))
        ax.fill_between(x, d, color=C_GREEN, alpha=0.14)
        ax.plot(x, d, color=C_GREEN, linewidth=1.1, alpha=0.95)
        ax.set_ylim(0, 100)
        self.emotion_canvas.draw_idle()

        # Eye closure alert
        if data.get("eye_status") == "CLOSED":
            if self.eye_closure_start_time is None:
                self.eye_closure_start_time = time.time()
            if (time.time() - self.eye_closure_start_time >= 3.0
                    and not self.eye_closure_alert_triggered):
                self.add_behavioral_event("ALERT: Eye Closure (>3s)")
                self.eye_closure_alert_triggered = True
        else:
            self.eye_closure_start_time      = None
            self.eye_closure_alert_triggered = False

        self.session_page.update_session(
            self.elapsed_seconds, self._alert_count,
            self.is_recording, stress, attn,
        )

        audio_emo = self.last_audio_data.get("emotion", "neu") or "neu"
        self.session_page.update_live_emotions(
            str(data.get("emotion", "neutral")),
            str(audio_emo),
        )

    @pyqtSlot(dict)
    def update_audio_stats(self, data):
        status = data.get("status")
        if status in ("PHASE_2_START", "CALIB_COMPLETE"):
            if status == "PHASE_2_START":
                self.calib_overlay.set_phase(
                    "HOW ARE YOU FEELING TODAY?",
                    "Speak naturally for 6 seconds",
                    "PHASE 2: SPEAK NATURALLY",
                    C_ACCENT,
                )
                self.calib_overlay.start_arc(6000)
                return
            if status == "CALIB_COMPLETE":
                self.calibration_finished = True
                self.center_stack.setCurrentIndex(1)
                self.timeline_container.show()
                self._set_side_panels_visible(True)
                self._calib_badge_visible = True
                self._calib_badge_timer.start(5000)
                self.add_behavioral_event("System Calibration Successful")
                return
        
        if not self.calibration_finished:
            return
        
        self.last_audio_data = data
        emo       = data.get("emotion", "--")
        emo3      = str(emo)[:3].lower()
        audio_str = str(emo).upper()
        self._metric_pills["val-audio-emo"].setText(audio_str)

        if emo3 in ("ang", "sad"):
            self._pill_objects["val-audio-emo"].set_status("alert")
            if not hasattr(self, "_last_audio_alert") or \
                    time.time() - self._last_audio_alert > 5:
                self.add_behavioral_event(f"ALERT: Vocal {emo3.upper()} detected")
                self._last_audio_alert = time.time()
        elif emo3 in ("hap", "neu"):
            self._pill_objects["val-audio-emo"].set_status("ok")
        else:
            self._pill_objects["val-audio-emo"].set_status("muted")

        waveform = data.get("waveform")
        if waveform is not None and len(waveform) > 0:
            cmap = {"ang": C_RED, "hap": C_GREEN, "sad": C_ACCENT,
                    "neu": C_ACCENT, "sur": C_AMBER}
            wave_color = cmap.get(emo3, C_ACCENT)
            self._last_wave_color = wave_color
            self._last_waveform   = waveform
            if self._audio_badge_lbl:
                self._audio_badge_lbl.setText(audio_str[:3])
            ax = _fresh_ax(self.audio_canvas)
            w  = waveform[::10]; x = np.arange(len(w))
            ax.fill_between(x, w, color=wave_color, alpha=0.14)
            ax.plot(x, w, color=wave_color, linewidth=0.95, alpha=0.95)
            ax.set_ylim(-1, 1)
            self.audio_canvas.draw_idle()

        # Live emotion pills update
        face_emo = self.last_face_data.get("emotion", "neutral") or "neutral"
        self.session_page.update_live_emotions(str(face_emo), str(emo))

    #calculations

    def calculate_stress(self, face_data, audio_data):
        if face_data.get("emotion") == "NO FACE DETECTED" or not face_data:
            return self.smoothed_stress
        face_map  = {"angry": 0.9, "fear": 1.0, "sad": 0.6,
                     "disgust": 0.5, "neutral": 0, "happy": -0.2}
        audio_map = {"ang": 0.8, "sad": 0.5, "neu": 0}
        f_emo  = face_data.get("emotion", "neutral")
        f_conf = face_data.get("confidence", 0) / 100.0
        a_emo  = audio_data.get("emotion", "neu")
        is_neg = f_emo in ("angry", "fear", "sad") or a_emo in ("ang", "sad")
        if is_neg: self.neg_frame_count += 1
        else:      self.neg_frame_count  = 0
        mult = 1.5 if self.neg_frame_count >= 5 else 1.0
        bp = 0
        if face_data.get("gaze_position") != "CENTER": self.gaze_frame_count += 1
        else:                                           self.gaze_frame_count  = 0
        if self.gaze_frame_count >= 5: bp += 0.1
        head = face_data.get("head_status", "HEAD NEUTRAL")
        if any(w in head for w in ("HEAD LEFT", "HEAD RIGHT", "HEAD UP", "HEAD DOWN")):
            bp += 0.25
        raw = ((face_map.get(f_emo, 0) * f_conf) + audio_map.get(a_emo, 0)) * mult + bp
        cur = min(100, max(0, raw * 100))
        self.smoothed_stress = 0.05 * cur + 0.95 * self.smoothed_stress
        return self.smoothed_stress

    def calculate_attention(self, data):
        if data.get("emotion") == "NO FACE DETECTED":
            self.smoothed_attn = 0.0; return 0.0
        score = 100.0
        if data.get("gaze_position", "CENTER") != "CENTER": score -= 30
        if ("HEAD NEUTRAL" not in data.get("head_status", "HEAD NEUTRAL") and
            "HEAD TILTED"  not in data.get("head_status", "HEAD NEUTRAL")):
            score -= 20
        score -= self.distraction_heat * 0.5
        self.smoothed_attn = 0.1 * score + 0.9 * self.smoothed_attn
        return max(0, min(100, self.smoothed_attn))

    def calculate_distraction_heat(self, data):
        if data.get("emotion") == "NO FACE DETECTED":
            self.distraction_heat = 0.0; return 0.0
        is_away   = data.get("gaze_position") != "CENTER"
        is_turned = ("HEAD NEUTRAL" not in data.get("head_status", "HEAD NEUTRAL") and
                     "HEAD TILTED"  not in data.get("head_status", "HEAD NEUTRAL"))
        if is_away or is_turned: self.distraction_heat += 2.0
        else:                    self.distraction_heat -= 0.5
        self.distraction_heat = max(0, min(100, self.distraction_heat))
        return self.distraction_heat

    def update_stress_ui(self, stress_val: float):
        self.stress_gauge.setValue(stress_val)
        if   stress_val < 50: color = C_GREEN;  self._stress_color = C_GREEN
        elif stress_val < 85: color = C_AMBER;  self._stress_color = C_AMBER
        else:                 color = C_RED;    self._stress_color = C_RED; self.trigger_stress_alert()
        self.stress_gauge.color = QColor(color)
        self.stress_gauge.update()

        self.stress_history.append(stress_val)
        if self._stress_badge_lbl:
            self._stress_badge_lbl.setText(f"{int(stress_val)}%")
            self._stress_badge_lbl.setStyleSheet(f"""
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(0,60,110,0.85), stop:1 rgba(0,30,65,0.85));
                border: 1px solid rgba(0,212,255,0.22);
                border-radius: 9px;
                color: {color};
                font-family: {F_MONO};
                font-size: 9px;
                font-weight: 700;
                padding: 2px 10px;
                letter-spacing: 1.5px;
            """)

        ax = _fresh_ax(self.stress_canvas)
        d  = list(self.stress_history); x = np.arange(len(d))
        ax.fill_between(x, d, color=color, alpha=0.16)
        ax.plot(x, d, color=color, linewidth=1.0, alpha=0.9)
        ax.set_ylim(0, 100)
        ax.axhline(85, color=C_RED, linewidth=0.5, alpha=0.35, linestyle="--")
        self.stress_canvas.draw_idle()

    def trigger_stress_alert(self):
        current_time = time.time()
        if current_time - self.last_alert_time > self.ALERT_COOLDOWN:
            def medical_pattern():
                for _ in range(3):
                    winsound.Beep(900, 150)
                    time.sleep(0.1)
            threading.Thread(target=medical_pattern, daemon=True).start()
            self.last_alert_time = current_time

    #recording

    def toggle_recording(self):
        if self.btn_record.isChecked():
            # Reset all accumulators
            self.session_finished       = False
            self.elapsed_seconds        = 0
            self.total_session_seconds  = 0
            self.high_stress_seconds    = 0
            self.blink_rate_accumulator = []
            self.peak_stress            = 0.0
            self.peak_stress_timestamp  = 0
            self.current_high_streak    = 0
            self.longest_high_streak    = 0
            self._alert_count           = 0
            self._attn_accumulator      = []
            self.stress_timeline_live.clear_events()
            self.session_page.stress_timeline.clear_events()

            self._recording_count += 1
            self.session_page.set_recordings(self._recording_count)

            # Write to a temp file during recording; user picks final path at session end
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".csv",
                prefix=f"behaviourAI_{time.strftime('%Y%m%d_%H%M%S')}_",
            )
            self.saved_csv_filename = tmp.name
            tmp.close()
            self.record_file  = open(self.saved_csv_filename, mode="w", newline="")
            self.csv_writer   = csv.writer(self.record_file)
            self.csv_writer.writerow([
                "Timestamp", "Face_Emotion", "Audio_Emotion", "Stress_Level",
                "Gaze", "Head_Status", "Blink_Rate", "Distraction_Heat", "Attention_Level",
            ])

            self.is_recording = True
            self.start_time   = time.time()

            self.session_timer.start(1000)
            self.burden_timer.start(1000)

            self.btn_record.setText("■ STOP RECORDING")
            self._set_record_style(True)
            self.header.timer_lbl.setText("00:00")
            self.header.timer_lbl.show()

        else:
            self.session_timer.stop()
            self.burden_timer.stop()
            self.is_recording = False
            if self.record_file:
                self.record_file.close()
            self.btn_record.setText("● START RECORDING")
            self._set_record_style(False)
            self.header.timer_lbl.hide()

    def log_data(self, stress_val):
        if self.is_recording and self.csv_writer:
            elapsed = round(time.time() - self.start_time, 2)
            self.csv_writer.writerow([
                elapsed,
                self.last_face_data.get("emotion",  "N/A"),
                self.last_audio_data.get("emotion", "N/A"),
                round(stress_val, 2),
                self.last_face_data.get("gaze_position", "N/A"),
                self.last_face_data.get("head_status",   "N/A"),
                self.last_face_data.get("blink_rate",    0),
                round(self.distraction_heat, 2),
                round(self.smoothed_attn,    2),
            ])

    #timer
    def update_timer(self):
        self.elapsed_seconds += 1
        m, s = divmod(self.elapsed_seconds, 60)
        self.header.timer_lbl.setText(f"{m:02d}:{s:02d}")
        if self.elapsed_seconds >= 120:
            self.session_timer.stop()
            self.burden_timer.stop()
            if self.btn_record.isChecked():
                self.btn_record.setChecked(False)
                self.toggle_recording()
            self.finalize_clinical_assessment()

    #final assessment

    def finalize_clinical_assessment(self):
        self.session_finished = True
        if not self.session_page.stress_timeline.events:
            return

        events   = self.session_page.stress_timeline.events
        high     = sum(1 for e in events if e["status"] == "high")
        pct      = (high / len(events)) * 100
        attn_avg = np.mean(self._attn_accumulator) if self._attn_accumulator else 0
        avg_blink = (np.mean(self.blink_rate_accumulator)
                     if self.blink_rate_accumulator else 0)

        # Build assessment text
        if pct > 60:
            txt   = f"FINAL ASSESSMENT: TRAUMA CARE INTERVENTION RECOMMENDED  ({int(pct)}% HIGH STRESS)"
            color = C_RED
            self.add_behavioral_event("CRITICAL: Trauma intervention required.")
        elif pct >= 30:
            txt   = f"FINAL ASSESSMENT: MONITOR CLOSELY — CONSIDER SUPPORT  ({int(pct)}% HIGH STRESS)"
            color = C_AMBER
            self.add_behavioral_event("WARNING: Elevated stress; support suggested.")
        else:
            txt   = f"FINAL ASSESSMENT: SESSION STABLE — MAINTAIN AWARENESS  ({int(pct)}% HIGH STRESS)"
            color = C_GREEN
            self.add_behavioral_event("INFO: Session stable; minimal trauma indicators.")

        # Build treatment text 
        if pct > 60:
            treatment = (
                "RECOMMENDED INTERVENTIONS:\n"
                "  • Immediate grounding: Box breathing (4-4-4-4 pattern) or 5-4-3-2-1 sensory technique\n"
                "  • Refer to a trauma-informed therapist as soon as possible\n"
                "  • Schedule a follow-up monitoring session within 48 hours\n"
                "  • Avoid high-stress environments until professional review"
            )
        elif pct >= 30:
            treatment = (
                "RECOMMENDED INTERVENTIONS:\n"
                "  • Introduce mindfulness or CBT-based self-help exercises daily\n"
                "  • Monitor closely over the next 2–3 sessions for escalation\n"
                "  • Flag elevated patterns for supervisor or clinician review\n"
                "  • Encourage regular sleep, exercise, and social support"
            )
        else:
            treatment = (
                "RECOMMENDATIONS:\n"
                "  • Positive reinforcement — current coping strategies are effective\n"
                "  • Continue existing routine; no immediate intervention required\n"
                "  • Schedule a routine follow-up session in 1–2 weeks\n"
                "  • Maintain awareness; contact a professional if symptoms change"
            )

        # Metrics page — full post-session stats
        session_date = time.strftime("%Y-%m-%d  %H:%M:%S")
        self.metrics_page.update_summary(
            events         = events,
            stress_history = self.stress_history,
            attn_avg       = attn_avg,
            peak_stress    = self.peak_stress,
            peak_ts        = self.peak_stress_timestamp,
            longest_streak = self.longest_high_streak,
            high_stress_secs = self.high_stress_seconds,
            avg_blink      = avg_blink,
            session_date   = session_date,
        )

        # Session page — assessment + replay panel (no duplicate recommendations)
        self.session_page.set_assessment(
            headline       = txt,
            color          = color,
            high_pct       = pct,
            alert_count    = self._alert_count,
            attn_avg       = attn_avg,
        )

        # Reports page 
        m, s = divmod(self.elapsed_seconds, 60)

        self.reports_page.set_session_meta(
            date         = session_date,
            duration     = f"{m:02d}:{s:02d}",
            total_events = len(events),
            csv_path     = self.saved_csv_filename,
        )
        self.reports_page.set_assessment(txt, color, treatment)

    #event log

    def add_behavioral_event(self, message: str):
        ts    = time.strftime("%H:%M:%S")
        entry = f"[{ts}]  {message}"
        item  = QListWidgetItem(entry)

        if   "ALERT"    in message or "CRITICAL" in message:
            item.setForeground(QColor(C_RED));   self._alert_count += 1
        elif "WARNING"  in message:
            item.setForeground(QColor(C_AMBER)); self._alert_count += 1
        elif "INFO"     in message or "Calibration" in message or "System" in message:
            item.setForeground(QColor(C_GREEN))
        else:
            item.setForeground(QColor(C_SUB))

        if (self.event_log.count() == 1 and
                self.event_log.item(0).text() == "Awaiting calibration…"):
            self.event_log.clear()

        self.event_log.addItem(item)
        self.event_log.scrollToBottom()
        self.reports_page.add_event(item)

    def _beep_alert(self):
        """Fire a 3-beep alert if outside cooldown. Non-blocking."""
        if time.time() - self.last_alert_time > self.ALERT_COOLDOWN:
            self.last_alert_time = time.time()
            def _beep():
                for _ in range(3):
                    winsound.Beep(920, 140); time.sleep(0.09)
            threading.Thread(target=_beep, daemon=True).start()

    #cleanup
    
    def closeEvent(self, event):
        self.video_thread.stop()
        self.audio_thread.stop()
        event.accept()