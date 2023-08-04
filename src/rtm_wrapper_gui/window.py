from typing import Any

from PySide6 import QtWidgets

from rtm_wrapper_gui import util
from rtm_wrapper_gui.plot import FigureWidget


class MainWindow(QtWidgets.QMainWindow):
    _central_widget: QtWidgets.QWidget

    figure_widget: FigureWidget

    plot_button: QtWidgets.QPushButton

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_window()
        self._init_central_widget()
        self._init_signals()

        self.figure_widget.show_splash(
            f"{util.make_version(util.DISTRIBUTION_NAME)}",
            horizontalalignment="center",
            color="grey",
            fontstyle="italic",
        )

    def _init_window(self) -> None:
        self.setWindowTitle("RTM Wrapper GUI")

    def _init_signals(self) -> None:
        self.plot_button.clicked.connect(self.figure_widget.draw)

    def _init_central_widget(self) -> None:
        top_layout = QtWidgets.QHBoxLayout()

        self.plot_button = QtWidgets.QPushButton()
        self.plot_button.setText("Plot")
        top_layout.addWidget(self.plot_button)

        self.figure_widget = FigureWidget()
        top_layout.addWidget(self.figure_widget)

        self._central_widget = QtWidgets.QWidget()
        self._central_widget.setLayout(top_layout)
        self.setCentralWidget(self._central_widget)
