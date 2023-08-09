from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from matplotlib.axes import Axes

from PySide6 import QtCore, QtWidgets


class FigureWidget(QtWidgets.QWidget):
    canvas: FigureCanvasQTAgg

    axes: Axes

    draw = QtCore.Signal()

    def __init__(
        self, parent: Optional[QtWidgets.QWidget] = None, *args, **kwargs
    ) -> None:
        super().__init__(parent, *args, **kwargs)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)

        self.canvas = FigureCanvasQTAgg(Figure(figsize=(5, 3)))
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.setLayout(layout)

        self.axes = self.canvas.figure.subplots()

        self._init_signals()

    def _init_signals(self) -> None:
        self.draw.connect(self.draw_random)

    def refresh_canvas(self) -> None:
        self.canvas.figure.tight_layout()
        self.canvas.draw_idle()
        # self.canvas.flush_events()

    @QtCore.Slot()
    def draw_random(self) -> None:
        self.axes.clear()
        self.axes.plot(
            np.random.random_integers(0, 10, 10),
            np.random.random_integers(0, 10, 10),
            "x",
        )
        self.refresh_canvas()
