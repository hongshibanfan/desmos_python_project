"""确认检查外层单文件版和包内版的关键实现是否一致。"""
from __future__ import annotations

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


outer = load(os.path.join(ROOT, "desmos_writer.py"), "outer_mod")
pack = load(os.path.join(ROOT, "desmos_writer_pack", "desmos_writer.py"), "pack_mod")

conv_cases = [
    "z=sin(x)cos(y)", "z=sqrt(x)", "z=sqrt(x+1)", "z=sqrt(sin(x))",
    "z=arcsin(x)", "z=sinh(x)", "z=nthroot(x,3)", "z=abs(x)",
    "z=floor(x)+ceil(x)", "z=sin(pi x)", "z=2 pi", r"z=\sin(x)",
    "z=asin(x)", "z=spin(x)", "z=tanh(x)", "z=arctan(x)", "z=x^2+y^2",
    "y=5cos(x/5)", "y=2sin(x)", "y=xcos(t)", "Rcos(θ)", "zcos(x)",
]

bad = 0
for t in conv_cases:
    if outer.plain_to_latex(t) != pack.plain_to_latex(t):
        bad += 1
        print("  plain_to_latex 不一致:", t,
              outer.plain_to_latex(t), pack.plain_to_latex(t))

print(f"转换逻辑 {len(conv_cases)} 项：",
      "全部一致" if bad == 0 else f"{bad} 项不一致")

checks = {
    "write_expression_api": (hasattr(outer, "write_expression_api"),
                             hasattr(pack, "write_expression_api")),
    "plain_to_latex": (hasattr(outer, "plain_to_latex"), hasattr(pack, "plain_to_latex")),
    "DesmosSession.write_via_api": (hasattr(outer.DesmosSession, "write_via_api"),
                                    hasattr(pack.DesmosSession, "write_via_api")),
    "DesmosSession._scroll_row_into_view": (
        hasattr(outer.DesmosSession, "_scroll_row_into_view"),
        hasattr(pack.DesmosSession, "_scroll_row_into_view")),
    "DesmosSession._row_has_error": (hasattr(outer.DesmosSession, "_row_has_error"),
                                     hasattr(pack.DesmosSession, "_row_has_error")),
}
for name, (a, b) in checks.items():
    print(f"  {name:<38} 外层={a} 包内={b}", "" if a == b else "  <<< 不一致")

sys.exit(1 if bad else 0)
