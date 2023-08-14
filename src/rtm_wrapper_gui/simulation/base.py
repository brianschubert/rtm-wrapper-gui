from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from rtm_wrapper_gui import util


class SimulationProducer(QtWidgets.QWidget):
    new_results = QtCore.Signal(util.RtmResults)
