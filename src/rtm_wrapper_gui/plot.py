from __future__ import annotations

import abc
import logging
import random
import string
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, Optional

import numpy as np
import xarray as xr
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

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
        layout.setContentsMargins(0, 0, 0, 10)

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
        # ax.set_xticks([])
        # ax.set_yticks([])

        self._get_axes().text(0.5, 0.5, message, **kwargs)


class RtmResultsPlots(QtWidgets.QWidget):
    figure_widget: FigureWidget

    controls: PlotControls

    plot_button: QtWidgets.QToolButton

    sim_results: util.RtmResults | None

    change_results = QtCore.Signal(util.RtmResults)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.figure_widget = FigureWidget(self)
        layout.addWidget(self.figure_widget)

        self.controls = PlotControls(self)
        layout.addWidget(self.controls)

        self.plot_button = QtWidgets.QToolButton()
        self.plot_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.plot_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.plot_button.setText("Plot")
        layout.addWidget(self.plot_button)

        self._init_signals()

        self.sim_results = None

    def _init_signals(self) -> None:
        self.change_results[util.RtmResults].connect(self._on_change_results)
        self.plot_button.clicked.connect(self._on_plot_clicked)

    @QtCore.Slot(util.RtmResults)
    def _on_change_results(self, results: util.RtmResults) -> None:
        self.sim_results = results

    @QtCore.Slot()
    def _on_plot_clicked(self) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("plot button clicked")
        # if self.sim_results is None:
        #     error = self._make_error_box("No results loaded")
        #     error.exec()
        #     return
        #
        # self.figure_widget.draw.emit()

        self.controls.dimensions_selector.set_requested_dims(
            random.sample(string.ascii_letters, 3)
        )

        # # or raise
        # actived_plotter = self.controls.get_active_plotter()
        #
        # specified_dim_settings = self.controls.get_requested_dims()
        #
        # actived_plotter.plot(self.figure, dataset, dim_spec)

    def _make_error_box(self, message: str) -> QtWidgets.QMessageBox:
        box = QtWidgets.QMessageBox()
        box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
        box.setText("Unable to plot")
        box.setInformativeText(message)
        box.setWindowTitle("Plot Error")
        # Match parent window's icon.
        box.setWindowIcon(self.window().windowIcon())
        # Use system error icon
        # box.setWindowIcon(QtGui.QIcon.fromTheme("error"))
        return box


class DatasetPlotter(abc.ABC):
    dimensions: tuple[str, ...]

    @abc.abstractmethod
    def plot(self, figure: FigureWidget, dataset, dim_spec) -> None:
        pass


class FixedDimDatasetPlotter(DatasetPlotter):
    """
    Dataset plotter that relies ona fixed layout for the dataset dimensions
    """

    def plot(self, figure: FigureWidget, dataset, dim_spec) -> None:
        trimmed_dataset = self._reshape_to_spec(dataset, dim_spec)
        self._plot(figure, dataset)

    @abc.abstractmethod
    def _plot(self, figure: FigureWidget, dataset: util.RtmResults) -> None:
        ...


class PlotterRegistry:
    """
    Registry of dataset plotters that the plot controls can offer to the user.
    """

    _plotters: list[type[DatasetPlotter]]

    def __init__(self) -> None:
        self._plotters = []

    def register(self, cls: type[DatasetPlotter]) -> None:
        self._plotters.append(cls)


class PlotControls(QtWidgets.QWidget):
    plotters: ClassVar[PlotterRegistry] = PlotterRegistry()

    plotter_selector: QtWidgets.QComboBox

    dimensions_selector: DimensionSelector

    reset_controls = QtCore.Slot()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
            )
        )

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.plotter_selector = QtWidgets.QComboBox(self)
        layout.addWidget(self.plotter_selector)

        self.dimensions_selector = DimensionSelector(self)
        layout.addWidget(self.dimensions_selector)


class DimensionSelector(QtWidgets.QGroupBox):
    requested_dimensions: list[str]

    available_dimensions: dict[str, xr.DataArray]

    reset = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Dimensions", parent)

        self.reset.connect(self._on_reset)

        self.setLayout(QtWidgets.QHBoxLayout())

    def set_requested_dims(self, dims: Iterable[str]) -> None:
        self.requested_dimensions = list(dims)
        self.reset.emit()

    def _on_reset(self) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("resetting dimension selector")

        # https://stackoverflow.com/q/4528347/11082165
        while self.layout().count():
            widget = self.layout().takeAt(0).widget()
            logger.debug("removing %r", widget)
            widget.deleteLater()

        for dim in self.requested_dimensions:
            self._add_dim_combo(dim)

    def _add_dim_combo(self, dim_name: str) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("adding combo %r", dim_name)

        widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout()
        widget.setLayout(layout)

        label = QtWidgets.QLabel(f"{dim_name}: ")
        layout.addWidget(label)

        combo = QtWidgets.QComboBox()
        layout.addWidget(combo)

        self.layout().addWidget(widget)


@PlotControls.plotters.register
class SingleSweepPlotter(DatasetPlotter):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
