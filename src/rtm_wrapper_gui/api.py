import argparse
import ast
import logging
import shlex
import sys

from PySide6 import QtWidgets

from . import util
from .window import MainWindow


def _make_parser() -> argparse.ArgumentParser:
    """
    Create CLI argument parser.
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--log-level",
        type=util.log_level,
        default="WARNING",
        help="Log level.",
        metavar="{DEBUG,INFO,WARNING,ERROR,CRITICAL} | <integer>",
    )
    parser.add_argument(
        "--qt-args",
        type=shlex.split,
        default="",
        help="Command line to pass to the internal QApplication.",
    )

    return parser


def main(cli_args: list[str]) -> None:
    """CLI entrypoint."""
    args = _make_parser().parse_args(cli_args)

    util.setup_debug_root_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.debug("cli %r", args)

    qt_argv = sys.argv[:1] + args.qt_args
    logger.debug(f"starting QApplication with {qt_argv=}")
    app = QtWidgets.QApplication(qt_argv)

    window = MainWindow()
    window.resize(1200, 800)
    window.show()

    app.exec()


def run() -> None:
    """Launch CLI entrypoint with the current process's CLI args."""
    main(sys.argv[1:])
