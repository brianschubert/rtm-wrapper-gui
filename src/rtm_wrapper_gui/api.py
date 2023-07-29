import sys

from PySide6 import QtWidgets

from .window import MainWindow


def main(cli_args: list[str]) -> None:
    app = QtWidgets.QApplication(cli_args)

    window = MainWindow()
    window.resize(1200, 800)
    window.show()

    app.exec()


def run() -> None:
    main(sys.argv[1:])
