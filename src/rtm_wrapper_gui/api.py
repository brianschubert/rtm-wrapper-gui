from __future__ import annotations

import argparse
import logging
import shlex
import signal
import sys
from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from rtm_wrapper_gui import util
from rtm_wrapper_gui.window import MainWindow

if TYPE_CHECKING:
    from types import FrameType


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
    parser.add_argument(
        "--version", action="store_true", help="Print version information and exit."
    )

    return parser


def main(cli_args: list[str]) -> None:
    """CLI entrypoint."""
    args = _make_parser().parse_args(cli_args)

    # Print version and exit if requested.
    if args.version:
        print(util.make_detailed_version(util.DISTRIBUTION_NAME))
        return

    util.setup_debug_root_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.debug("cli %r", args)

    qt_argv = sys.argv[:1] + args.qt_args
    logger.debug("starting QApplication with args=%r", qt_argv)
    app = QtWidgets.QApplication(qt_argv)
    _register_quit()

    logger.debug("creating main window")
    window = MainWindow()
    window.resize(1200, 800)
    logger.debug("showing main window")
    window.show()

    logger.debug("starting app")
    app.exec()
    logger.debug("exiting normally")


def run() -> None:
    """Launch CLI entrypoint with the current process's CLI args."""
    main(sys.argv[1:])


def _register_quit() -> None:
    """
    Registering signal handler to gracefully quit the global QApplication on SIGINT.

    References
    ==========

    * https://stackoverflow.com/questions/4938723/
    """

    def _handler(signum: int, frame: FrameType | None) -> None:
        logger = logging.getLogger(__name__)
        logger.debug(
            "quitting in response to signal %r. Was in %r",
            signal.Signals(signum).name,
            frame,
        )
        QtWidgets.QApplication.quit()

    signal.signal(signal.SIGINT, _handler)
