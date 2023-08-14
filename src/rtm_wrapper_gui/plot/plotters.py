"""
Dataset plotters.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

import xarray as xr

import rtm_wrapper.plot as rtm_plot

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class DatasetPlotter(abc.ABC):
    """
    Base class for all dataset plotters.

    Dataset plotters attempt to produce some type of plot for a given dataset.
    """

    def __init__(self, **kwargs: Any) -> None:
        if kwargs:
            raise ValueError(f"received unknown kwargs: {list(kwargs.keys())}")

    @abc.abstractmethod
    def plot(self, figure: Figure, dataset: xr.Dataset) -> None:
        ...


class VariableDatasetPlotter(DatasetPlotter):
    """
    Dataset plotter that plots data from a single variable.
    """

    _variable: str | None

    def __init__(self, **kwargs: Any) -> None:
        self._variable = kwargs.pop("variable")
        super().__init__(**kwargs)

    def plot(self, figure: Figure, dataset: xr.Dataset) -> None:
        if self._variable is None:
            raise RuntimeError("variable not configured")

        variable = dataset.data_vars[self._variable]
        self.plot_variable(figure, variable)

    @abc.abstractmethod
    def plot_variable(self, figure: Figure, variable: xr.DataArray):
        ...


class SingleSweepVariablePlotter(VariableDatasetPlotter):
    def plot_variable(self, figure: Figure, data: xr.DataArray) -> None:
        ax = figure.subplots(1, 1)
        rtm_plot.plot_sweep_single(data, ax=ax)


class LegendSweepVariablePlotter(VariableDatasetPlotter):
    _xaxis_dim: str | None

    _legend_dim: str | None

    def __init__(self, **kwargs: Any) -> None:
        self._xaxis_dim = kwargs.pop("xaxis_dim")
        self._legend_dim = kwargs.pop("legend_dim")
        super().__init__(**kwargs)

    def plot_variable(self, figure: Figure, data: xr.DataArray) -> None:
        ax = figure.subplots(1, 1)
        rtm_plot.plot_sweep_legend(
            data, ax=ax, xaxis_dim=self._xaxis_dim, legend_dim=self._legend_dim
        )


class GridSweepVariablePlotter(VariableDatasetPlotter):
    _xaxis_dim: str | None

    _grid_y_dim: str | None
    _grid_x_dim: str | None

    def __init__(self, **kwargs: Any) -> None:
        self._xaxis_dim = kwargs.pop("xaxis_dim")
        self._grid_y_dim = kwargs.pop("grid_y_dim")
        self._grid_x_dim = kwargs.pop("grid_x_dim")
        super().__init__(**kwargs)

    def plot_variable(self, figure: Figure, data: xr.DataArray) -> None:
        rtm_plot.plot_sweep_grid(
            data,
            fig=figure,
            xaxis_dim=self._xaxis_dim,
            grid_y_dim=self._grid_y_dim,
            grid_x_dim=self._grid_x_dim,
        )
