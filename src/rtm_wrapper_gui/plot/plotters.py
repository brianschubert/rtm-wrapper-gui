"""
Dataset plotters.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

import xarray as xr

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


class FixedDimVariablePlotter(VariableDatasetPlotter):
    """
    Variable plotter that relies on a fixed layout for the dataset dimensions.
    """

    _dim_shape: tuple[str, ...] | None

    def __init__(self, **kwargs: Any) -> None:
        self._dim_shape = kwargs.pop("dims")
        super().__init__(**kwargs)

    def plot_variable(self, figure: Figure, data: xr.DataArray) -> None:
        if self._dim_shape is None:
            raise RuntimeError("dim shape not configured")
        reshaped_data = data.transpose(*self._dim_shape, missing_dims="raise")
        self._plot_variable(figure, reshaped_data)

    @abc.abstractmethod
    def _plot_variable(self, figure: Figure, data: xr.DataArray) -> None:
        ...
