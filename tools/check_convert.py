"""转换器 / 光标模拟 的自检（不启动浏览器）。"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from desmos_writer_pack import plain_to_latex

CONV = [

    ("z=sin(x)cos(y)",              r"z=\sin(x)\cos(y)"),
    ("z=x^2+y^2",                   "z=x^2+y^2"),
    ("z=sqrt(x)",                   r"z=\sqrt{x}"),
    ("z=sqrt(x+1)",                 r"z=\sqrt{x+1}"),
    ("z=sqrt(sin(x))",              r"z=\sqrt{\sin(x)}"),
    ("z=sqrt(sqrt(x))",             r"z=\sqrt{\sqrt{x}}"),
    ("z=arcsin(x)",                 r"z=\arcsin(x)"),
    ("z=sinh(x)",                   r"z=\sinh(x)"),
    ("z=nthroot(x,3)",              r"z=\nthroot(x,3)"),
    ("z=abs(x)",                    r"z=\abs(x)"),
    ("z=exp(x)",                    r"z=\exp(x)"),
    ("z=floor(x)+ceil(x)",          r"z=\floor(x)+\ceil(x)"),
    ("z=mod(x,y)",                  r"z=\mod(x,y)"),
    ("z=min(x,y)+max(x,y)",         r"z=\min(x,y)+\max(x,y)"),
    ("z=gcd(x,y)lcm(x,y)",          r"z=\gcd(x,y)\lcm(x,y)"),
    ("z=ln(x)+log(x)",              r"z=\ln(x)+\log(x)"),
    ("z=sin(pi x)",                 r"z=\sin(\pi x)"),
    ("z=2 pi",                      r"z=2 \pi"),
    (r"z=\sin(x)",                  r"z=\sin(x)"),
    ("z=asin(x)",                   "z=asin(x)"),
    ("z=spin(x)",                   "z=spin(x)"),
    ("z=tanh(x)",                   r"z=\tanh(x)"),
    ("z=arctan(x)",                 r"z=\arctan(x)"),

    ("y=5cos(x/5)",                 r"y=5\cos(x/5)"),
    ("y=2sin(x)",                   r"y=2\sin(x)"),
    ("y=xcos(t)",                   r"y=x\cos(t)"),
    ("Rcos(θ)",                     r"R\cos(θ)"),

    ("zcos(x)",                     "zcos(x)"),
    ("acos(x)",                     "acos(x)"),
]


def main() -> int:
    failed = 0
    print("=== plain_to_latex ===")
    for plain, want in CONV:
        got = plain_to_latex(plain)
        ok = got == want
        failed += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {plain!r}")
        if not ok:
            print(f"        期望 {want!r}")
            print(f"        实际 {got!r}")

    print(f"\n{len(CONV) - failed}/{len(CONV)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
