"""Worker watchdog: controller pipe closure kills the entire inherited group.

Invoked by absolute filename in isolated Python mode, never from the worker tree.
"""

import os
import select
import signal
import subprocess
import sys


def main():
    child = subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL)
    while child.poll() is None:
        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if readable and not os.read(sys.stdin.fileno(), 1):
            os.killpg(os.getpgrp(), signal.SIGKILL)
    return child.returncode


if __name__ == "__main__":
    sys.exit(main())
