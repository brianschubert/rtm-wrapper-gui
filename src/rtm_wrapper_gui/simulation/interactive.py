from __future__ import annotations

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt

from rtm_wrapper_gui.simulation.base import SimulationProducer


class InteractiveSimulationProducer(SimulationProducer):
    splash_textedit: QtWidgets.QTextEdit()

    def __init__(self, parent: QtGui.QTextDocument | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.splash_textedit = QtWidgets.QTextEdit()
        layout.addWidget(self.splash_textedit)

        self.splash_textedit.setText("Coming soon!")
        self.splash_textedit.setAlignment(Qt.AlignmentFlag.AlignCenter)
