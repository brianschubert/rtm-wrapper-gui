from __future__ import annotations

from PySide6 import QtCore

from rtm_wrapper_gui import util


class SimulationProducerMixin:
    new_results = QtCore.Signal(util.RtmResults)
