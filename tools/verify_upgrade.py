"""真实验证：自动滚动（键盘模式） + API 模式。

    python verify_upgrade.py               # 测包内版
    python verify_upgrade.py desmos_writer # 测外层单文件版
"""
from __future__ import annotations

import importlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

MODULE = sys.argv[1] if len(sys.argv) > 1 else "desmos_writer_pack"
dw = importlib.import_module(MODULE)
print("验证模块:", dw.__file__)

URL = "https://www.desmos.com/calculator?lang=zh-CN"
N = 12


def values(s):
    return [x for x in (s.state_latex() or []) if x and x.strip()]


def main() -> int:
    s = dw.open_desmos(url=URL, headless=False, verbose=False)
    rc = 0
    try:
        print("=" * 62)
        print(f"1. 键盘模式：连续写 {N} 行（面板会溢出，考验自动滚动）")
        print("=" * 62)
        ok_count = 0
        for row in range(1, N + 1):
            r = dw.write_expression(s, row, f"y={row}")
            if r.ok:
                ok_count += 1
            else:
                print(f"   第{row}行失败: {r.message}")
        print(f"   成功 {ok_count}/{N}")
        vals = values(s)
        print(f"   实际条数 {len(vals)}")
        if ok_count != N:
            rc = 1

        print()
        print("=" * 62)
        print("2. API 模式：追加（row=None）")
        print("=" * 62)
        before = len(values(s))
        r = dw.write_expression_api(s, None, r"y=\sin(x)")
        print("   ->", r, "| readback:", r.readback)
        after = len(values(s))
        print(f"   条数 {before} -> {after}")
        if not r.ok or after != before + 1:
            rc = 1

        print()
        print("=" * 62)
        print("3. API 模式：定点覆盖第 1 行")
        print("=" * 62)
        r = dw.write_expression_api(s, 1, r"y=\cos(x)")
        print("   ->", r, "| readback:", r.readback)
        print("   第1行现在是:", values(s)[0])
        if not r.ok or values(s)[0] != r"y=\cos(x)":
            rc = 1

        print()
        print("=" * 62)
        print("4. API 模式：越界应报错")
        print("=" * 62)
        r = dw.write_expression_api(s, 9999, "y=nope")
        print("   ->", r)
        if r.ok:
            rc = 1

        print()
        print("=" * 62)
        print("5. API 模式：原样传入（$ @ latex: 都不再特殊）")
        print("=" * 62)
        r = dw.write_expression_api(s, None, "y=1$2")
        print("   -> readback:", r.readback, "(期望 y=1$2，原样保留)")
        if r.readback != "y=1$2":
            rc = 1

        print()
        print("=" * 62)
        print("6. API 模式：解析失败要能被抓到（普通写法不再自动转换）")
        print("=" * 62)
        r = dw.write_expression_api(s, None, "y=sin(x)")
        print("   ->", r)
        print("   warnings:", r.warnings)
        if r.ok:
            print("   !! 没能识别出解析失败")
            rc = 1

        print()
        print("=" * 62)
        print("7. 键盘模式与 API 模式混用后，图表仍然正常")
        print("=" * 62)
        print("   最终条数:", len(values(s)))
        s.page.screenshot(path=os.path.join(HERE, "verify_upgrade.png"))
        print("   已截图 verify_upgrade.png")
    finally:
        s.close()
    print("\n结果:", "全部通过" if rc == 0 else "有失败")
    return rc


if __name__ == "__main__":
    sys.exit(main())
