"""环境自检：启动失败时先跑这个，看是哪一环的问题。

    python check_env.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))


def line(k, v):
    print(f"{k:<22}{v}")


def main() -> int:
    print("=" * 56)
    print("Desmos 输入程序 环境自检")
    print("=" * 56)

    line("Python", sys.executable)
    line("版本", sys.version.split()[0])
    line("工作目录", os.getcwd())
    line("脚本目录", str(HERE))

    try:
        import importlib.metadata as md
        line("playwright", md.version("playwright"))
    except Exception as e:
        line("playwright", f"✗ 未安装（{e}）")
        print("\n请先运行：python -m pip install playwright")
        return 2


    temp = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    writable = "?"
    try:
        Path(temp).mkdir(parents=True, exist_ok=True)
        fd, p = tempfile.mkstemp(dir=temp, prefix=".probe_")
        os.close(fd)
        os.remove(p)
        writable = "✓ 可写"
    except Exception as e:
        writable = f"✗ 不可写（{type(e).__name__}）→ 程序会自动换目录"
    line("临时目录", temp)
    line("  是否可写", writable)
    line("DESMOS_TEMP_DIR", os.environ.get("DESMOS_TEMP_DIR", "(未设置)"))


    print("-" * 56)
    try:
        import desmos_writer_pack as dw
        s = dw.open_desmos(
            url="https://www.desmos.com/3d?lang=zh-CN",
            headless=True,
            verbose=False,
        )
        try:
            line("浏览器启动", "✓ 成功")
            line("Desmos 加载", f"✓ 可编辑行 {s.row_count()} 个")
            line("Calc.getState", "✓ 可用" if s.state_latex() is not None else "✗ 不可用")
            r = s.write(1, "z=x^2+y^2")
            line("写入第1行", f"{'✓' if r.ok else '✗'} {r.message}")
            r2 = s.write(99, "z=nope")
            line("越界检查", f"{'✓ 正确拒绝' if not r2.ok else '✗ 竟然写进去了'}")
        finally:
            s.close()
    except Exception as e:
        line("浏览器启动", f"✗ {type(e).__name__}: {str(e)[:120]}")
        print("\n如果是临时目录问题，可以手动指定：")
        print('  PowerShell:  $env:DESMOS_TEMP_DIR="D:\\temp"')
        print("  cmd:         set DESMOS_TEMP_DIR=D:\\temp")
        return 3

    print("=" * 56)
    print("一切正常，可以运行 test.py 了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
