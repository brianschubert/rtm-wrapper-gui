"""
Plotting GUI elements.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Optional

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

from rtm_wrapper_gui import util

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
        self.setLayout(layout)

        layout.setContentsMargins(0, 0, 0, 10)

        self.canvas = FigureCanvasQTAgg(Figure())
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

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

    def _set_subplots(self, **kwargs: Any) -> None:
        # Remove all existing axes.
        for ax in self.axes.flat:
            self.canvas.figure.delaxes(ax)

        # Create the requested axes.
        axes: Axes | np.ndarray = self.canvas.figure.subplots(**kwargs)

        if isinstance(axes, np.ndarray):
            self.axes = axes
        else:
            # Only single axis was returned. Store it as a singleton array with shape
            # (). This ensures that ``self.axes`` always has a consistent type.
            self.axes = np.array(axes, dtype=object)

        # Reset the toolbar's navigation stack.
        self.toolbar.update()

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

        self._get_axes().text(0.5, 0.5, message, **kwargs)


class RtmResultsPlots(QtWidgets.QWidget):
    figure_widget: FigureWidget

    controls: PlotControls

    active_results: util.WatchedBox[util.RtmResults | None]

    def __init__(
        self,
        results_box: util.WatchedBox[util.RtmResults],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.active_results = results_box

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.figure_widget = FigureWidget(self)
        layout.addWidget(self.figure_widget)

        self.controls = PlotControls(self)
        layout.addWidget(self.controls)


class PlotterRegistry:
    """
    Registry of dataset plotters that the plot controls can offer to the user.
    """

    _plotters: list[type[...]]

    def __init__(self) -> None:
        self._plotters = []

    def register(self, cls: type[...]) -> None:
        self._plotters.append(cls)


class PlotControls(QtWidgets.QWidget):
    plotters: ClassVar[PlotterRegistry] = PlotterRegistry()

    plotter_selector: QtWidgets.QComboBox
    plotter_controls: QtWidgets.QStackedWidget

    plot_button: QtWidgets.QPushButton
    reset_button: QtWidgets.QPushButton

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)

        left_controls = QtWidgets.QVBoxLayout()
        layout.addLayout(left_controls)

        self.plotter_controls = QtWidgets.QStackedWidget()
        layout.addWidget(self.plotter_controls)

        self.plotter_selector = QtWidgets.QComboBox()
        left_controls.addWidget(self.plotter_selector)

        for num in range(5):
            name = f"Option {num}"
            widget = QtWidgets.QGroupBox()
            widget.setTitle(f"Content {num} Configuration")

            self.plotter_selector.addItem(name)
            self.plotter_controls.addWidget(widget)

        self.reset_button = QtWidgets.QPushButton()
        self.reset_button.setIcon(
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogResetButton
            )
        )
        self.reset_button.setText("Reset")
        left_controls.addWidget(self.reset_button)

        self.plot_button = QtWidgets.QPushButton()
        self.plot_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.plot_button.setText("Plot")
        left_controls.addWidget(self.plot_button)

        # self.setSizePolicy(
        #     QtWidgets.QSizePolicy(
        #         QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        #     )
        # )

        self._init_signals()

    def _init_signals(self) -> None:
        self.plot_button.clicked.connect(self._on_plot_clicked)
        self.plotter_selector.activated[int].connect(
            self.plotter_controls.setCurrentIndex
        )

    @QtCore.Slot()
    def _on_plot_clicked(self) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("plot button clicked")
