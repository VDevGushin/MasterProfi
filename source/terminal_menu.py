from __future__ import annotations

import select
import sys
import termios
import tty
import os
from typing import Sequence


def choose_option(options: Sequence[str]) -> int | None:
    """Show a small arrow-key terminal menu; return a zero-based choice or None."""
    if not options or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    selected = 0
    line_count = len(options) + 1

    def render(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{line_count}A")
        for index, label in enumerate(options):
            marker = "❯" if index == selected else " "
            text = f" {marker} {index + 1}. {label} "
            if index == selected:
                text = f"\x1b[7m{text}\x1b[0m"
            sys.stdout.write(f"\x1b[2K\r{text}\n")
        sys.stdout.write("\x1b[2K\r↑/↓ — выбрать, Enter — подтвердить, Esc — отменить\n")
        sys.stdout.flush()

    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        sys.stdout.write("\x1b[?25l")
        render(first=True)
        while True:
            key = os.read(descriptor, 1).decode("utf-8", errors="ignore")
            if key in {"\r", "\n"}:
                return selected
            if key in {"j", "J"}:
                selected = min(selected + 1, len(options) - 1)
                render()
                continue
            if key in {"k", "K"}:
                selected = max(selected - 1, 0)
                render()
                continue
            if key.isdigit() and 1 <= int(key) <= len(options):
                selected = int(key) - 1
                render()
                continue
            if key == "\x1b":
                ready, _, _ = select.select([descriptor], [], [], 0.1)
                if not ready:
                    return None
                sequence = os.read(descriptor, 2).decode("utf-8", errors="ignore")
                if sequence == "[A":
                    selected = max(selected - 1, 0)
                    render()
                elif sequence == "[B":
                    selected = min(selected + 1, len(options) - 1)
                    render()
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        sys.stdout.write("\x1b[?25h\n")
        sys.stdout.flush()
