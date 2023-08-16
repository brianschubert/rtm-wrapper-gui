from __future__ import annotations

import itertools
from operator import itemgetter

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt

from rtm_wrapper.engines.sixs import PySixSEngine
from rtm_wrapper_gui.simulation.base import SimulationProducerMixin


class InteractiveSimulationProducer(SimulationProducerMixin, QtWidgets.QWidget):
    splash_textedit: QtWidgets.QTextEdit()

    base_group: QtWidgets.QGroupBox

    sweep_group: QtWidgets.QGroupBox

    def __init__(self, parent: QtGui.QTextDocument | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.splash_textedit = QtWidgets.QTextEdit()
        layout.addWidget(self.splash_textedit)
        self.splash_textedit.setFixedHeight(25)

        self.splash_textedit.setText("Coming soon!")
        self.splash_textedit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.base_group = QtWidgets.QGroupBox("Base:")
        self.base_group.setSizePolicy(
            QtWidgets.QSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Maximum,
            )
        )
        base_group_layout = QtWidgets.QGridLayout()
        self.base_group.setLayout(base_group_layout)
        layout.addWidget(self.base_group)

        self.sweep_group = QtWidgets.QGroupBox("Sweep:")
        layout.addWidget(self.sweep_group)

        params = itertools.groupby(
            sorted(PySixSEngine.params.param_implementations.keys(), key=itemgetter(0)),
            key=itemgetter(0),
        )

        for i, (param, classes) in enumerate(params):
            print(param, classes)
            label = QtWidgets.QLabel()
            label.setText(param.replace("_", " "))
            font = QtGui.QFont()
            font.setBold(True)
            label.setFont(font)
            combo = QtWidgets.QComboBox()
            combo.addItems([c.__name__ for _, c in classes])

            base_group_layout.addWidget(label, i, 0)
            base_group_layout.addWidget(combo, i, 1)
