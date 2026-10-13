r"""desmos-writer：把数学表达式写入 Desmos 网页的自动化工具。

典型用法：

    from desmos_writer_pack import open_desmos, write_expression, write_expression_api

    s = open_desmos(keep_open=True)
    write_expression(s, 1, "z=x^2+y^2")
    write_expression_api(s, 2, r"z=\sin(x)")
    s.close()
"""
from .desmos_writer import (
    DEFAULT_URL,
    DesmosSession,
    WriteResult,
    open_desmos,
    plain_to_latex,
    same_expression,
    write_expression,
    write_expression_api,
)

__all__ = [
    "DEFAULT_URL",
    "DesmosSession",
    "WriteResult",
    "open_desmos",
    "plain_to_latex",
    "same_expression",
    "write_expression",
    "write_expression_api",
]

__version__ = "0.1.0"
