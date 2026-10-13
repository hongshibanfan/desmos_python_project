"""desmos_writer 的离线测试：用真实浏览器跑在模拟的 Desmos 页面上。

    python test_desmos_writer.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import mock_desmos
import desmos_writer_pack as dw

PORT = 8791
URL = f"http://127.0.0.1:{PORT}/"
PROFILE = os.path.join(tempfile.gettempdir(), "desmos_writer_test_profile")


def _open(**kwargs):
    return dw.open_desmos(
        url=URL,
        headless=True,
        profile_dir=PROFILE,
        verbose=False,
        **kwargs,
    )


def _non_empty(session):
    return [x for x in (session.state_latex() or []) if x and x.strip()]


def test_public_api_exists():
    for name in dw.__all__:
        assert hasattr(dw, name), f"缺少 {name}"
    assert callable(dw.write_expression)


def test_write_expressions_removed():
    assert not hasattr(dw, "write_expressions"), "write_expressions 应该已删除"
    assert not hasattr(dw.DesmosSession, "write_many"), "write_many 应该已删除"


def test_write_expression_signature():
    """write_expression(session, 行号, 表达式) —— 行号在第二位。"""
    params = list(inspect.signature(dw.write_expression).parameters)
    assert params[:3] == ["session", "row", "expression"], params
    method_params = list(inspect.signature(dw.DesmosSession.write).parameters)
    assert method_params[:3] == ["self", "row", "expression"], method_params


def test_keep_open_is_accepted():
    assert "keep_open" in inspect.signature(dw.open_desmos).parameters
    s = _open(keep_open=True)
    try:
        assert s.keep_open is True
    finally:
        s.keep_open = False
        s.close()


def test_same_expression_normalisation():
    assert dw.same_expression("z=x^2+y^2", "z=x^{2}+y^{2}")
    assert dw.same_expression("z=sin(x)", "z=\\sin\\left(x\\right)")
    assert not dw.same_expression("z=x", "z=y")


def test_write_to_first_row():
    s = _open()
    try:
        r = s.write(1, "z=x^2+y^2")
        print("   ->", r)
        assert r.ok, r.message
        assert r.row == 1
        assert r.committed
        assert any(dw.same_expression("z=x^2+y^2", x) for x in _non_empty(s))
    finally:
        s.close()


def test_module_level_write_expression():
    s = _open()
    try:
        r = dw.write_expression(s, 1, "z=x*y")
        print("   ->", r)
        assert r.ok, r.message
        assert r.row == 1
    finally:
        s.close()


def test_write_to_specific_rows():
    s = _open()
    try:
        for row, expr in [(1, "z=a"), (2, "z=b"), (3, "z=c")]:
            r = s.write(row, expr)
            print("   ->", r)
            assert r.ok, r.message
            assert r.row == row
        assert _non_empty(s) == ["z=a", "z=b", "z=c"], _non_empty(s)
    finally:
        s.close()


def test_overwrite_same_row():
    """同一行写两次应该覆盖，不会多出一行。"""
    s = _open()
    try:
        assert s.write(1, "z=a+b").ok
        assert s.write(1, "z=c*d").ok
        values = _non_empty(s)
        print("   values:", values, "| row1:", repr(s.read_row(1)))
        assert values == ["z=c*d"], values
        assert s.read_row(1).strip() == "z=c*d"
    finally:
        s.close()


def test_row_out_of_range_fails():
    s = _open()
    try:
        r = s.write(99, "z=nowhere")
        print("   ->", r)
        assert not r.ok
        assert "超出范围" in r.message
        assert not _non_empty(s), "越界时不应该写入任何内容"
    finally:
        s.close()


def test_row_zero_fails():
    s = _open()
    try:
        r = s.write(0, "z=zero")
        print("   ->", r)
        assert not r.ok, "行号从 1 开始，0 应该失败"
    finally:
        s.close()


def test_real_keyboard_events_and_enter():
    s = _open()
    try:
        assert s.write(1, "z=x*y").ok
        keys = s.page.evaluate("() => window.__keys || []")
        assert any(k.endswith(":x") for k in keys), keys
        assert "down:Enter" in keys, f"没有检测到回车：{keys}"
        inputs = s.page.evaluate("() => window.__inputs || 0")
        assert inputs > 0, "没有触发 input 事件，说明不是真实输入"
    finally:
        s.close()


def test_typing_without_enter_does_not_commit():
    s = _open()
    try:
        expr_id = s._expression_ids()[0]
        assert s._reveal_row(expr_id, 1)
        assert s._focus_expression(expr_id)
        s.page.keyboard.type("z=never_committed")
        time.sleep(0.4)
        assert not any("never_committed" in x for x in _non_empty(s))
        s.page.keyboard.press("Enter")
        time.sleep(0.6)
        assert any(dw.same_expression("z=never_committed", x) for x in _non_empty(s))
    finally:
        s.close()


def test_latex_prefix_is_verbatim():
    s = _open()
    try:
        r = s.write(1, r"latex:\frac{1}{2}")
        assert r.ok, r.message
        assert s.read_row(1).strip() == r"\frac{1}{2}"
    finally:
        s.close()


def test_parse_cursor_commands():
    """$ 左移、@ 右移、\\$ 和 \\@ 是字面量。"""
    parse = dw.desmos_writer._parse_cursor_commands
    assert parse("ab") == [("text", "ab")]
    assert parse("a$b") == [("text", "a"), ("left", 1), ("text", "b")]
    assert parse("a@b") == [("text", "a"), ("right", 1), ("text", "b")]
    assert parse("$$") == [("left", 1), ("left", 1)]
    assert parse("@$@") == [("right", 1), ("left", 1), ("right", 1)]
    assert parse(r"a\$b") == [("text", "a$b")]
    assert parse(r"a\@b") == [("text", "a@b")]
    assert parse(r"\sin") == [("text", r"\sin")]


def test_cursor_left_moves_one_char():
    """z=ab$c：输入 z=ab 后左移一格，再输入 c -> z=acb。"""
    s = _open()
    try:
        r = s.write(1, "z=ab$c")
        print("   ->", r, "| row1:", repr(s.read_row(1)))
        assert r.ok, r.message
        assert s.read_row(1).strip() == "z=acb", s.read_row(1)
    finally:
        s.close()


def test_cursor_right_moves_one_char():
    """z=ab$@c：左移再右移回到末尾 -> z=abc。"""
    s = _open()
    try:
        assert s.write(1, "z=ab$@c").ok
        assert s.read_row(1).strip() == "z=abc", s.read_row(1)
    finally:
        s.close()


def test_cursor_moves_accumulate():
    """z=abc$$X：左移两格 -> z=aXbc。"""
    s = _open()
    try:
        assert s.write(1, "z=abc$$X").ok
        assert s.read_row(1).strip() == "z=aXbc", s.read_row(1)
    finally:
        s.close()


def test_cursor_user_example():
    """你给的例子 z=sin($x)；模拟页面没有自动补括号，所以结果是 z=sinx)(。"""
    s = _open()
    try:
        assert s.write(1, "z=sin($x)").ok
        print("   row1:", repr(s.read_row(1)))
        assert s.read_row(1).strip() == "z=sinx)(", s.read_row(1)
    finally:
        s.close()


def test_escaped_symbols_are_literal():
    s = _open()
    try:
        assert s.write(1, r"z=a\$b").ok
        assert s.read_row(1).strip() == "z=a$b", s.read_row(1)
    finally:
        s.close()


def test_latex_mode_does_not_move_cursor():
    """latex: 模式下 $ 和 @ 原样输入。"""
    s = _open()
    try:
        assert s.write(1, "latex:a$b@c").ok
        assert s.read_row(1).strip() == "a$b@c", s.read_row(1)
    finally:
        s.close()


def test_plain_to_latex():
    """普通写法 -> LaTeX：函数名补反斜杠，sqrt 换成花括号。"""
    assert dw.plain_to_latex("z=sin(x)cos(y)") == r"z=\sin(x)\cos(y)"
    assert dw.plain_to_latex("z=sqrt(x)") == r"z=\sqrt{x}"
    assert dw.plain_to_latex("z=sqrt(sin(x))") == r"z=\sqrt{\sin(x)}"
    assert dw.plain_to_latex("z=arcsin(x)") == r"z=\arcsin(x)"
    assert dw.plain_to_latex("z=sinh(x)") == r"z=\sinh(x)"
    assert dw.plain_to_latex("z=nthroot(x,3)") == r"z=\nthroot(x,3)"
    assert dw.plain_to_latex(r"z=\sin(x)") == r"z=\sin(x)"
    assert dw.plain_to_latex("z=asin(x)") == "z=asin(x)"
    assert dw.plain_to_latex("z=spin(x)") == "z=spin(x)"
    assert dw.plain_to_latex("z=sin(pi x)") == r"z=\sin(\pi x)"


def test_plain_to_latex_implicit_multiplication():
    """数字 / x / y / R / θ 紧挨在函数名前，要当成隐含乘法并转换。"""
    assert dw.plain_to_latex("y=5cos(x/5)") == r"y=5\cos(x/5)"
    assert dw.plain_to_latex("y=2sin(x)") == r"y=2\sin(x)"
    assert dw.plain_to_latex("y=xcos(t)") == r"y=x\cos(t)"
    assert dw.plain_to_latex("Rcos(θ)") == r"R\cos(θ)"
    assert dw.plain_to_latex("y=ycos(t)") == r"y=y\cos(t)"


def test_plain_to_latex_other_letters_block():
    """其他字母紧挨在函数名前，一律当变量，不转换。"""
    assert dw.plain_to_latex("zcos(x)") == "zcos(x)"
    assert dw.plain_to_latex("acos(x)") == "acos(x)"
    assert dw.plain_to_latex("bsin(x)") == "bsin(x)"


def test_simulate_cursor():
    """（已移除）API 模式改为原样传入，这条历史接口不再提供。"""
    assert not hasattr(dw, "simulate_cursor"), "simulate_cursor 已经删除"


def test_api_write_to_row():
    """API 模式定点写入第 2 行。"""
    s = _open()
    try:
        assert dw.write_expression_api(s, 1, "y=1").ok
        assert dw.write_expression_api(s, 2, "y=2").ok
        r = dw.write_expression_api(s, 1, "y=99")
        print("   ->", r, "| readback:", r.readback)
        assert r.ok, r.message
        assert r.row == 1
        assert (s.state_latex() or [])[0] == "y=99"
    finally:
        s.close()


def test_api_append_row():
    """row=None 时 API 追加新行，可以无限追加。"""
    s = _open()
    try:
        for k in range(1, 6):
            r = dw.write_expression_api(s, None, f"y={k}")
            assert r.ok, r.message
        vals = [x for x in (s.state_latex() or []) if x.strip()]
        print("   ->", vals)
        assert vals == ["y=1", "y=2", "y=3", "y=4", "y=5"], vals
    finally:
        s.close()


def test_api_row_out_of_range():
    s = _open()
    try:
        r = dw.write_expression_api(s, 99, "y=nope")
        print("   ->", r)
        assert not r.ok
        assert "超出范围" in r.message
    finally:
        s.close()


def test_api_passes_latex_through_unchanged():
    """API 模式原样传入，不做任何转换。"""
    s = _open()
    try:
        raw = r"y=\sin(x)\cos(x)"
        r = dw.write_expression_api(s, 1, raw)
        print("   ->", r, "| readback:", r.readback)
        assert r.ok, r.message
        assert r.readback == raw, r.readback
    finally:
        s.close()


def test_api_plain_notation_is_not_converted():
    """普通写法不会被自动转换，Desmos 会判定为变量而报错。"""
    s = _open()
    try:
        r = dw.write_expression_api(s, 1, "y=sin(x)")
        print("   ->", r, "| warnings:", r.warnings)
        assert not r.ok
        assert "没能解析" in r.message
    finally:
        s.close()


def test_api_latex_prefix_is_not_special():
    """latex: 前缀不再特殊，会原样传进去。"""
    s = _open()
    try:
        r = dw.write_expression_api(s, 1, r"latex:y=\sin(x)")
        print("   ->", r, "| readback:", r.readback)
        assert r.readback == r"latex:y=\sin(x)", r.readback
    finally:
        s.close()


def test_api_cursor_symbols_are_literal():
    """$ / @ 在 API 模式下不再特殊，按字面传入。"""
    s = _open()
    try:
        r = dw.write_expression_api(s, 1, "y=1$2")
        print("   ->", r, "| readback:", r.readback)
        assert r.readback == "y=1$2", r.readback
    finally:
        s.close()


def test_api_and_keyboard_independent():
    """两种模式可以在同一页面上混用。"""
    s = _open()
    try:
        assert dw.write_expression_api(s, None, "z=100").ok
        assert s.write(1, "z=200").ok
        assert dw.write_expression_api(s, None, "z=300").ok
        vals = [x for x in (s.state_latex() or []) if x.strip()]
        print("   ->", vals)
        assert "z=100" in vals and "z=300" in vals, vals
    finally:
        s.close()


def test_api_next_row_is_created():
    """回归：全新页面只有 1 条，写第 1 行后写第 2 行必须成功（API 不会自动补行）。"""
    s = _open()
    try:
        ids = s._expression_ids()
        assert len(ids) == 1, f"模拟页面初始应只有 1 条，实际 {len(ids)}"

        r1 = dw.write_expression_api(s, 1, r"y=5\cos(x/5)")
        print("  第1行 ->", r1, "| readback:", r1.readback)
        assert r1.ok, r1.message
        assert r1.readback == r"y=5\cos(x/5)", r1.readback

        r2 = dw.write_expression_api(s, 2, "y=x")
        print("  第2行 ->", r2, "| readback:", r2.readback)
        assert r2.ok, r2.message
        assert r2.row == 2
        assert r2.readback == "y=x", r2.readback

        vals = _non_empty(s)
        assert vals == [r"y=5\cos(x/5)", "y=x"], vals
    finally:
        s.close()


def test_api_far_row_still_fails():
    """离得太远的行号仍然要报错。"""
    s = _open()
    try:
        r = dw.write_expression_api(s, 5, "y=nope")
        print("   ->", r)
        assert not r.ok
        assert "超出范围" in r.message
    finally:
        s.close()


TESTS = [
    test_public_api_exists,
    test_write_expressions_removed,
    test_write_expression_signature,
    test_keep_open_is_accepted,
    test_same_expression_normalisation,
    test_write_to_first_row,
    test_module_level_write_expression,
    test_write_to_specific_rows,
    test_overwrite_same_row,
    test_row_out_of_range_fails,
    test_row_zero_fails,
    test_real_keyboard_events_and_enter,
    test_typing_without_enter_does_not_commit,
    test_latex_prefix_is_verbatim,
    test_parse_cursor_commands,
    test_cursor_left_moves_one_char,
    test_cursor_right_moves_one_char,
    test_cursor_moves_accumulate,
    test_cursor_user_example,
    test_escaped_symbols_are_literal,
    test_latex_mode_does_not_move_cursor,
    test_plain_to_latex,
    test_plain_to_latex_implicit_multiplication,
    test_plain_to_latex_other_letters_block,
    test_simulate_cursor,
    test_api_write_to_row,
    test_api_append_row,
    test_api_row_out_of_range,
    test_api_next_row_is_created,
    test_api_far_row_still_fails,
    test_api_passes_latex_through_unchanged,
    test_api_plain_notation_is_not_converted,
    test_api_latex_prefix_is_not_special,
    test_api_cursor_symbols_are_literal,
    test_api_and_keyboard_independent,
]


def main() -> int:
    srv = mock_desmos.serve(PORT)
    print(f"mock server on {URL}")
    failed = 0
    for t in TESTS:
        try:
            t()
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {t.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"[PASS] {t.__name__}")
    srv.shutdown()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
