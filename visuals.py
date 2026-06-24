from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib

matplotlib.rcParams.update({
    "figure.facecolor":  (0, 0, 0, 0),
    "axes.facecolor":    (0, 0, 0, 0),
    "savefig.facecolor": (0, 0, 0, 0),
    "figure.edgecolor":  (0, 0, 0, 0),
    "axes.edgecolor":    (0, 0, 0, 0),
})


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=2.6, dpi=100, title=""):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.fig.patch.set_facecolor((0, 0, 0, 0))
        self.fig.patch.set_alpha(0.0)

        self.axes = self.fig.add_subplot(111)
        self.axes.set_facecolor((0, 0, 0, 0))

        # Remove ALL spines
        for spine in self.axes.spines.values():
            spine.set_visible(False)

        
        self.axes.tick_params(
            left=False, right=False, bottom=False, top=False,
            labelleft=False, labelright=False,
            labelbottom=False, labeltop=False,
        )

        self.axes.yaxis.grid(
            True,
            linestyle="-",
            color="#091929",
            linewidth=0.4,
            alpha=0.9,
        )
        self.axes.set_axisbelow(True)

        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        super().__init__(self.fig)

        self.setStyleSheet("background: transparent;")
        self.setAttribute(
            __import__("PyQt6.QtCore", fromlist=["Qt"])
            .Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.setContentsMargins(0, 0, 0, 0)

    def fresh_axes(self):
        """Wipe and reset axes, return ready for plotting."""
        ax = self.axes
        ax.cla()
        ax.set_facecolor((0, 0, 0, 0))
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.tick_params(
            left=False, right=False, bottom=False, top=False,
            labelleft=False, labelright=False,
            labelbottom=False, labeltop=False,
        )
        ax.yaxis.grid(True, color="#091929", linewidth=0.4, alpha=0.9)
        ax.set_axisbelow(True)
        return ax