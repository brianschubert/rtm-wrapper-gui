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
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

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

        # Set axes to empty array of shape (0,).
        self.axes = np.empty((0,), dtype=object)

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


class RtmResultsPlots(QtWidgets.QScrollArea):

    # Note: making this widget a QScrollArea allows the widgets in the plot controls
    # widget (combo boxes, list widgets) to be shurnk smaller than their normal minimum
    # horizontal size. TODO: track down why this is, and find a less hacky approach.

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
        # layout.setSpacing(0)
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

        self.layout().setContentsMargins(0, 0, 0, 0)

    def _init_signals(self) -> None:
        self.controls.plot_button.clicked.connect(self._on_plot_clicked)
        self.controls.reset_button.clicked.connect(self.reset_figure)
        self.active_results.value_changed[object].connect(self._on_results_changed)

    def reset_figure(self) -> None:
        # TODO reconcile figure clearing logic
        self.figure_widget.wipe_axes()
        self.figure_widget.canvas.figure.clear()
        self.figure_widget._refresh_canvas()

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
        self.reset_figure()
        try:
            plotter.plot(
                self.figure_widget.canvas.figure, self.active_results.value.dataset
            )
        except Exception as ex:
            logger.error("exception raised during plotting", exc_info=ex)
            QtWidgets.QMessageBox.critical(
                self, "Error plotting", f"Exception raised during plotting: {ex}"
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

        self.plotter_controls = QtWidgets.QStackedWidget(self)
        self.plotter_controls.hide()  # start hidden
        # self.plotter_controls.setSizePolicy(
        #     QtWidgets.QSizePolicy(
        #         QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        #         QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        #     )
        # )
        # self.plotter_controls.setMinimumWidth(50)
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
        self.layout().setContentsMargins(10, 0, 10, 10)

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


class MultiSelectPlotterConfigWidget(DatasetPlotterConfigWidget):
    """
    Plotter config consisting of several list selections.
    """

    list_selectors: dict[str, SelectionListWidget]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.list_selectors = {}

    def setup_for_dataset(self, dataset: xr.Dataset) -> None:
        super().setup_for_dataset(dataset)

        self.clear_selectors()

        for name, choices in self.selection_choices(dataset).items():
            list_widget = SelectionListWidget(f"{name}:")
            self.list_selectors[name] = list_widget
            for choice in choices:
                if isinstance(choice, tuple):
                    choice_display, choice_value = choice
                else:
                    choice_display = choice_value = choice

                item = QtWidgets.QListWidgetItem()
                item.setText(choice_display)
                item.setData(Qt.ItemDataRole.UserRole, choice_value)
                list_widget.list.addItem(item)
            self.layout().addWidget(list_widget)

    def clear_selectors(self) -> None:
        # Remove all current selection widgets.
        for widget in self.list_selectors.values():
            self.layout().removeWidget(widget)
            widget.deleteLater()
        self.list_selectors.clear()

    def selection_choices(
        self, dataset: xr.Dataset
    ) -> dict[str, list[str | tuple[str, str]]]:
        return {}

    def current_selections(self) -> dict[str, Any]:
        selections = {}

        for key, widget in self.list_selectors.items():
            try:
                value = widget.list.currentItem().data(Qt.ItemDataRole.UserRole)
            except AttributeError:
                raise RuntimeError(f"missing selection for {key}")

            selections[key] = value

        return selections


@PlotControls.plotters.register
class SingleSweepVariablePlotter(MultiSelectPlotterConfigWidget):
    @property
    def display_name(self) -> str:
        return "Single Sweep"

    def selection_choices(
        self, dataset: xr.Dataset
    ) -> dict[str, list[tuple[str, str]]]:
        return {  # type: ignore
            "variable": [
                (variable.attrs.get("title", variable.name), variable.name)
                for variable in dataset.data_vars.values()
            ],
        }

    def make_plotter(self) -> plotters.DatasetPlotter:
        return plotters.SingleSweepVariablePlotter(**self.current_selections())

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return len(dataset.indexes.dims) == 1


@PlotControls.plotters.register
class SingleSweepVariablePlotter(DatasetPlotterConfigWidget):
    @property
    def display_name(self) -> str:
        return "Single Sweep - all"

    def make_plotter(self) -> plotters.DatasetPlotter:
        return plotters.SingleSweepAllVariablesPlotter()

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return len(dataset.indexes.dims) == 1


@PlotControls.plotters.register
class LegendSweepVariablePlotter(MultiSelectPlotterConfigWidget):
    @property
    def display_name(self) -> str:
        return "Legend Sweep"

    def selection_choices(self, dataset: xr.Dataset) -> dict[str, list[str]]:
        return {  # type: ignore
            "variable": [
                (variable.attrs.get("title", variable.name), variable.name)
                for variable in dataset.data_vars.values()
            ],
            "xaxis_dim": [
                (_dim_name(dataset, dim), dim) for dim in dataset.indexes.dims
            ],
            "legend_dim": [
                (_dim_name(dataset, dim), dim) for dim in dataset.indexes.dims
            ],
        }

    def make_plotter(self) -> plotters.DatasetPlotter:
        return plotters.LegendSweepVariablePlotter(**self.current_selections())

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return len(dataset.indexes.dims) == 2


@PlotControls.plotters.register
class GridSweepVariablePlotter(MultiSelectPlotterConfigWidget):
    @property
    def display_name(self) -> str:
        return "2D Grid Comparison"

    def selection_choices(self, dataset: xr.Dataset) -> dict[str, list[str]]:
        return {  # type: ignore
            "variable": [
                (variable.attrs.get("title", variable.name), variable.name)
                for variable in dataset.data_vars.values()
            ],
            "xaxis_dim": [
                (_dim_name(dataset, dim), dim) for dim in dataset.indexes.dims
            ],
            "grid_y_dim": [
                (_dim_name(dataset, dim), dim) for dim in dataset.indexes.dims
            ],
            "grid_x_dim": [
                (_dim_name(dataset, dim), dim) for dim in dataset.indexes.dims
            ],
        }

    def make_plotter(self) -> plotters.DatasetPlotter:
        return plotters.GridSweepVariablePlotter(**self.current_selections())

    def can_plot_dataset(self, dataset: xr.Dataset) -> bool:
        return len(dataset.indexes.dims) == 3


class SelectionListWidget(QtWidgets.QWidget):
    label: QtWidgets.QLabel

    list: QtWidgets.QListWidget

    def __init__(self, label: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout())

        font = QtGui.QFont()
        font.setBold(True)

        self.label = QtWidgets.QLabel()
        self.label.setText(label)
        self.label.setFont(font)
        self.layout().addWidget(self.label)

        # self.setSizePolicy(
        #     QtWidgets.QSizePolicy(
        #         QtWidgets.QSizePolicy.Policy.Minimum,
        #         QtWidgets.QSizePolicy.Policy.Minimum,
        #     )
        # )

        self.list = QtWidgets.QListWidget()
        self.list.setFixedHeight(100)
        self.layout().addWidget(self.list)

        # self.list.setSizePolicy(
        #     QtWidgets.QSizePolicy(
        #         QtWidgets.QSizePolicy.Policy.Minimum,
        #         QtWidgets.QSizePolicy.Policy.Minimum,
        #     )
        # )
        self.list.setSizeAdjustPolicy(
            QtWidgets.QListWidget.SizeAdjustPolicy.AdjustToContents
        )
        # self.list.setMinimumWidth(50)
        # self.setMinimumWidth(50)


def _dim_name(data: xr.Dataset, dim: str) -> str:
    try:
        coord = data.coords[dim]
        return coord.attrs["title"]
    except KeyError:
        return dim
