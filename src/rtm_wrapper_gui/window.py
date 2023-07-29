from typing import Any

from PySide6 import QtWidgets


class MainWindow(QtWidgets.QMainWindow):
    _central_widget: QtWidgets.QWidget

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._init_window()
        self._init_central_widget()

    def _init_window(self) -> None:
        self.setWindowTitle("RTM Wrapper GUI")

    def _init_central_widget(self) -> None:
        top_layout = QtWidgets.QHBoxLayout()

        test_text = QtWidgets.QTextEdit()
        test_text.setText("Test")
        top_layout.addWidget(test_text)

        self._central_widget = QtWidgets.QWidget()
        self._central_widget.setLayout(top_layout)
        self.setCentralWidget(self._central_widget)
