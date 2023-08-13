"""
Plotting GUI elements.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Iterator, Optional

import numpy as np
import xarray as xr
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

from rtm_wrapper_gui import util

from . import plotters

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

    def wipe_axes(self) -> None:
        """Remove all existing axes."""
        for ax in self.axes.flat:
            self.canvas.figure.delaxes(ax)

    def _set_subplots(self, **kwargs: Any) -> None:
        self.wipe_axes()

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
        self.controls.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
        )
        layout.addWidget(self.controls)

        self._init_signals()

    def _init_signals(self) -> None:
        self.controls.plot_button.clicked.connect(self._on_plot_clicked)
        self.active_results.value_changed[object].connect(self._on_results_changed)

    @QtCore.Slot()
    def _on_plot_clicked(self) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("plot button clicked")

        if self.active_results.value is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Misconfigured plotter",
                f"Cannot create plot: no simulation results are loaded",
            )
            return

        plotter_index = self.controls.plotter_selector.currentIndex()
        plotter_config: DatasetPlotterConfigWidget = (  # type: ignore
            self.controls.plotter_controls.widget(plotter_index)
        )
        if plotter_config is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Misconfigured plotter",
                f"Cannot create plot: no plotter selected",
            )
            logger.warning("plot button clicked, but no plotter is active")
            return

        try:
            plotter = plotter_config.make_plotter()
        except Exception as ex:
            logger.warning("exception raised during plotter creation", exc_info=ex)
            QtWidgets.QMessageBox.warning(
                self,
                "Misconfigured plotter",
                f"Cannot create plot with current configuration: {ex}",
            )
            return

        logger.debug("plotting")
        self.figure_widget.wipe_axes()
        plotter.plot(
            self.figure_widget.canvas.figure, self.active_results.value.dataset
        )
        self.figure_widget._refresh_canvas()

    def _on_results_changed(self, new_results: util.RtmResults | None) -> None:
        logger = logging.getLogger(__name__)

        if new_results is None:
            logger.debug("results is None - disabling all plotters")
            self.controls.plotter_selector.setCurrentIndex(-1)
            for plotter_idx in range(0, self.controls.plotter_controls.count()):
                plotter_combo_item = self.controls.plotter_selector.model().item(
                    plotter_idx, 0
                )
                plotter_combo_item.setEnabled(False)
            return

        for plotter_idx in range(self.controls.plotter_controls.count()):
            plotter: DummyPlotterConfig = self.controls.plotter_controls.widget(plotter_idx)  # type: ignore
            plotter.setup_for_dataset(new_results.dataset)

            plotter_combo_item = self.controls.plotter_selector.model().item(
                plotter_idx, 0
            )
            enabled = plotter.can_plot_dataset(new_results.dataset)
            plotter_combo_item.setEnabled(enabled)
            logger.debug(
                f"plotter %d %s (%s) enabled: %s",
                plotter_idx,
                plotter.display_name,
                type(plotter).__name__,
                enabled,
            )

        current_index = self.controls.plotter_selector.currentIndex()
        active_plotter = self.controls.plotter_selector.model().item(current_index, 0)
        if active_plotter is not None and not active_plotter.isEnabled():
            logger.debug("active plotter was disabled - resetting to no active plotter")
            self.controls.plotter_selector.setCurrentIndex(-1)
            self.controls.plotter_controls.setCurrentIndex(-1)


class DatasetPlotterConfigWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QHBoxLayout())

    def make_plotter(self) -> plotters.DatasetPlotter:
        raise NotImplementedError

    @property
    def display_name(self) -> str:
        return self.__class__.__name__

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return False

    def setup_for_dataset(self, dataset: xr.Dataset) -> None:
        ...


class PlotterRegistry:
    """
    Registry of dataset plotters that the plot controls can offer to the user.
    """

    _plotters: list[type[DatasetPlotterConfigWidget]]

    def __init__(self) -> None:
        self._plotters = []

    def register(
        self, cls: type[DatasetPlotterConfigWidget]
    ) -> type[DatasetPlotterConfigWidget]:
        self._plotters.append(cls)
        return cls

    def __iter__(self) -> Iterator[type[DatasetPlotterConfigWidget]]:
        yield from self._plotters


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
        self.plotter_controls.hide()  # start hidden
        layout.addWidget(self.plotter_controls)

        self.plotter_selector = QtWidgets.QComboBox()
        self.plotter_selector.setPlaceholderText("<no selection>")
        left_controls.addWidget(self.plotter_selector)

        for plotter_cls in self.plotters:
            plotter_controls = plotter_cls(self)
            self.plotter_selector.addItem(plotter_controls.display_name)
            self.plotter_controls.addWidget(plotter_controls)

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
        self.plotter_selector.currentIndexChanged[int].connect(self._on_plotter_changed)

    def _on_plotter_changed(self, index: int) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("plotter controls index changed to %r", index)
        self.plotter_controls.setCurrentIndex(index)
        if index == -1:
            self.plotter_controls.hide()
        else:
            self.plotter_controls.show()


class FixedDimVariablePlotter(DatasetPlotterConfigWidget):
    required_dims: list[str]

    variable_selector: _LabelledListWidget

    dim_lists: list[_LabelledListWidget]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.variable_selector = _LabelledListWidget("Variable")
        self.layout().addWidget(self.variable_selector)
        self.dim_lists = []

    def setup_for_dataset(self, dataset: xr.Dataset) -> None:
        super().setup_for_dataset(dataset)

        self.variable_selector.list.clear()
        for var_name in dataset.data_vars.keys():
            self.variable_selector.list.addItem(var_name)

        for widget in self.dim_lists:
            self.layout().removeWidget(widget)
            # widget.deleteLater()

        for plot_dim in self.required_dims:
            list_widget = _LabelledListWidget(plot_dim)
            self.dim_lists.append(list_widget)
            for data_dim in dataset.indexes.dims.keys():
                list_widget.list.addItem(f"{data_dim}")
            self.layout().addWidget(list_widget)

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return len(dataset.indexes.dims) == len(self.required_dims)


@PlotControls.plotters.register
class SingleSweepVariablePlotter(FixedDimVariablePlotter):
    required_dims: tuple[str, ...] = ("x-axis",)

    @property
    def display_name(self) -> str:
        return "Single Sweep"

    def _get_config(self) -> dict[str, Any]:
        try:
            variable = self.variable_selector.list.currentItem().text()
        except AttributeError:
            raise RuntimeError("variable not selected")

        dims = []
        for req_dim, selector in zip(self.required_dims, self.dim_lists):
            try:
                dims.append(selector.list.currentItem().text())
            except AttributeError:
                raise RuntimeError(f"no dimension selected for {req_dim}")

        return {"variable": variable, "dims": dims}

    def make_plotter(self) -> plotters.DatasetPlotter:
        return plotters.SingleSweepVariablePlotter(**self._get_config())


class _LabelledListWidget(QtWidgets.QWidget):
    label: QtWidgets.QLabel

    list: QtWidgets.QListWidget

    def __init__(self, label: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.label = QtWidgets.QLabel()
        self.label.setText(label)
        self.layout().addWidget(self.label)

        self.list = QtWidgets.QListWidget()
        self.layout().addWidget(self.list)
