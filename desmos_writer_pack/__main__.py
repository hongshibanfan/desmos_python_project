"""支持 python -m desmos_writer_pack 直接运行命令行。"""
from __future__ import annotations

import sys

from .desmos_writer import main

if __name__ == "__main__":
    sys.exit(main())
