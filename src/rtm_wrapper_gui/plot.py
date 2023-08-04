from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from matplotlib.axes import Axes


class FigureWidget(QtWidgets.QWidget):
    canvas: FigureCanvasQTAgg

    axes: np.ndarray

    draw = QtCore.Signal()

    def __init__(
        self, parent: Optional[QtWidgets.QWidget] = None, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(parent, *args, **kwargs)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = FigureCanvasQTAgg(Figure())
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.setLayout(layout)

        # Temporarily initialize axes to single array of shape () containing a None value.
        self.axes = np.empty((0,), dtype=object)

        self._init_signals()

    def _init_signals(self) -> None:
        self.draw.connect(self.draw_random)

    def _get_axes(self) -> Axes:
        try:
            return self.axes.item()  # type: ignore
        except ValueError as ex:
            raise RuntimeError(
                f"attempted to retrieve singleton axes, but current figure"
                f" has multiple axes with shape {self.axes.shape}"
            ) from ex

    # def resizeEvent(self, *args: Any) -> None:
    #     super().resizeEvent(*args)
    #     self._refresh_canvas()

    def _refresh_canvas(self) -> None:
        self.canvas.draw_idle()

    @QtCore.Slot()
    def draw_random(self) -> None:
        self._set_subplots(nrows=2, ncols=2)
        for ax in self.axes.flat:
            # ax.clear()
            ax.plot(
                np.random.random_integers(0, 10, 10),
                np.random.random_integers(0, 10, 10),
                "x",
            )
        self._refresh_canvas()

    def show_splash(self, message: str, **kwargs: Any) -> None:
        self._set_subplots(nrows=1, ncols=1)

        self._get_axes().axis("off")
        # ax.set_xticks([])
        # ax.set_yticks([])

        self._get_axes().text(0.5, 0.5, message, **kwargs)
