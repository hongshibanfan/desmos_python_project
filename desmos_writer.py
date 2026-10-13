#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 Playwright 把数学表达式写入 Desmos 网页指定行的输入框，并回车确定。

表达式里可以用 $ 表示光标左移一个字符、@ 表示右移一个字符，
\\$ 和 \\@ 表示这两个符号本身；latex: 前缀表示原样输入，不解析光标指令。

命令行：
    python desmos_writer.py "z=x^2+y^2" "z=sin($x)"

代码里调用：
    from desmos_writer import open_desmos, write_expression

    s = open_desmos(keep_open=True)
    write_expression(s, 1, "z=x^2+y^2")
    s.close()
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺少 playwright，请先运行：\n"
             "  python -m pip install playwright\n"
             "  python -m playwright install chromium")

__all__ = [
    "WriteResult",
    "DesmosSession",
    "open_desmos",
    "plain_to_latex",
    "write_expression",
    "write_expression_api",
    "same_expression",
]

DEFAULT_URL = "https://www.desmos.com/calculator?lang=zh-CN"

STATE_JS = """
() => {
  const c = window.Calc;
  if (!c || !c.getState) return null;
  try {
    const s = c.getState();
    return ((s && s.expressions && s.expressions.list) || []).map(e => e.latex || '');
  } catch (e) { return null; }
}
"""

ROW_COUNT_JS = """
() => Array.prototype.slice
  .call(document.querySelectorAll('.dcg-expressionitem'))
  .filter(r => r.querySelector('textarea')).length
"""

IDS_JS = """
() => {
  const c = window.Calc;
  if (!c || !c.getState) return null;
  try { return c.getState().expressions.list.map(e => e.id); }
  catch (e) { return null; }
}
"""


REVEAL_JS = """
(args) => {
  const id = args[0], rowNumber = args[1];
  const row = document.querySelector('.dcg-expressionitem[expr-id="' + id + '"]');
  const panel = document.querySelector('.dcg-exppanel');
  if (row && row.querySelector('textarea')) {
    if (panel && panel.scrollHeight > panel.clientHeight) {
      const pr = panel.getBoundingClientRect();
      const rr = row.getBoundingClientRect();
      panel.scrollTop += (rr.top - pr.top) - (pr.height - rr.height) / 2;
    } else {
      row.scrollIntoView({ block: 'center', behavior: 'instant' });
    }
    return 'found';
  }
  if (!panel) return 'nopanel';
  const rows = Array.prototype.slice.call(
      panel.querySelectorAll('.dcg-expressionitem'));
  if (!rows.length) return 'norows';
  const label = rows[0].getAttribute('aria-label') || '';
  const m = label.match(/(\\d+)/);
  const firstNumber = m ? parseInt(m[1], 10) : 1;
  const dir = rowNumber >= firstNumber ? 1 : -1;
  const before = panel.scrollTop;
  panel.scrollTop = before + dir * Math.max(40, panel.clientHeight * 0.8);
  return panel.scrollTop === before ? 'edge' : 'scrolled';
}
"""

FOCUS_JS = """
(id) => {
  const row = document.querySelector('.dcg-expressionitem[expr-id="' + id + '"]');
  if (!row) return false;
  const t = row.querySelector('textarea');
  if (!t) return false;
  t.focus();
  return document.activeElement === t;
}
"""

ERROR_JS = """
(id) => {
  const c = window.Calc;
  if (!c || !c.expressionAnalysis) return null;
  const a = c.expressionAnalysis[id];
  if (!a) return null;
  return { isError: !!a.isError, message: a.errorMessage || '' };
}
"""


@dataclass
class WriteResult:
    """一次写入的结果：是否成功、写到了第几行、校验回读到的内容。"""

    ok: bool
    expression: str
    row: int
    message: str = ""
    committed: bool = False
    readback: str = ""
    before: list = field(default_factory=list)
    after: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        mark = "OK " if self.ok else "FAIL"
        return f"[{mark}] 第{self.row}行 {self.expression!r} -> {self.message}"


def _normalise(s: str) -> str:
    t = re.sub(r"\s+", "", str(s))
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\cdot", "*").replace("\\times", "*")
    t = t.replace("\\", "")
    t = t.replace("{", "").replace("}", "")
    return t


def same_expression(expected: str, actual: str) -> bool:

    if actual is None:
        return False
    return _normalise(expected) == _normalise(actual)


def _parse_cursor_commands(text: str) -> list:
    """把表达式拆成执行步骤：文字段与光标移动指令。

    $ 表示光标左移一个字符，@ 表示右移一个字符，每个符号生效一次；
    """
    steps: list = []
    buf: list = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in "$@":
            buf.append(text[i + 1])
            i += 2
            continue
        if ch in "$@":
            if buf:
                steps.append(("text", "".join(buf)))
                buf = []
            steps.append(("left" if ch == "$" else "right", 1))
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        steps.append(("text", "".join(buf)))
    return steps


FUNCTION_NAMES = (
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "floor", "ceil", "round", "sign", "nthroot", "sqrt",
    "gcd", "lcm", "mod", "min", "max", "csc", "sec", "cot",
    "sin", "cos", "tan", "log", "ln", "abs", "exp",
)

CONSTANT_NAMES = ("pi",)

IMPLICIT_MULTIPLIER = "xyRθ"


def _matching_paren(text: str, open_index: int) -> Optional[int]:
    """返回与 text[open_index] 处左括号配对的那个右括号的下标，找不到返回 None。"""
    depth = 0
    for j in range(open_index, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return None


def _match_function(text: str, i: int) -> Optional[str]:
    """若 text 从下标 i 开始是一个“函数名 + 左括号”，返回函数名，否则返回 None。

    """
    if i > 0:
        prev = text[i - 1]
        if prev == "\\":
            return None
        if prev.isalpha() and prev not in IMPLICIT_MULTIPLIER:
            return None
    for name in FUNCTION_NAMES:
        if text.startswith(name, i) and text[i + len(name):i + len(name) + 1] == "(":
            return name
    return None


def plain_to_latex(text: str) -> str:
    """把普通数学写法转成 Desmos 能正确解析的 LaTeX。。
    """
    out: list = []
    i = 0
    while i < len(text):
        name = _match_function(text, i)
        if name is not None:
            open_index = i + len(name)
            if name == "sqrt":
                close_index = _matching_paren(text, open_index)
                if close_index is not None:
                    inner = text[open_index + 1:close_index]
                    out.append("\\sqrt{" + plain_to_latex(inner) + "}")
                    i = close_index + 1
                    continue
            else:
                out.append("\\" + name + "(")
                i = open_index + 1
                continue
        if text[i].isalpha():
            for const in CONSTANT_NAMES:
                if (text.startswith(const, i)
                        and not (i + len(const) < len(text)
                                 and text[i + len(const)].isalnum())):
                    out.append("\\" + const)
                    i += len(const)
                    break
            else:
                out.append(text[i])
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _is_temp_error(exc: Exception) -> bool:
    """判断异常"""
    msg = str(exc)
    return ("mkdtemp" in msg) or ("EPERM" in msg and "temp" in msg.lower())


def _user_data_dir() -> Path:
    """返回本工具的用户级数据目录（用于放浏览器配置和临时文件）。

    安装到 site-packages 后，包目录通常是只读的，不能再往里写东西，
    所以统一放到用户目录。可用环境变量 DESMOS_WRITER_HOME 覆盖。
    """
    override = os.environ.get("DESMOS_WRITER_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        path = Path(base) / "desmos-writer"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "desmos-writer"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / "desmos-writer"

    path = Path(path).expanduser()
    if not path.is_absolute():
        path = Path(tempfile.gettempdir()) / "desmos-writer"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(tempfile.gettempdir()) / "desmos-writer"
        path.mkdir(parents=True, exist_ok=True)
    return path


def _fallback_temp_dir() -> str:
    """返回一个可写的备用临时目录。"""
    override = os.environ.get("DESMOS_TEMP_DIR")
    if override:
        Path(override).mkdir(parents=True, exist_ok=True)
        return override
    fallback = _user_data_dir() / "tmp"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)


def _use_temp_dir(path: str) -> None:
    """让 Playwright 的驱动进程改用指定临时目录。"""
    for var in ("TEMP", "TMP", "TMPDIR"):
        os.environ[var] = path


def _boot_context(pw, attach_port: Optional[int], kwargs: dict):
    """连接或启动浏览器"""
    if attach_port:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{attach_port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        return ctx, False
    ctx = pw.chromium.launch_persistent_context(**kwargs)
    return ctx, True


class DesmosSession:
    """持有一个 Desmos 页面，负责等待加载、定位输入框、写入并校验表达式。"""

    def __init__(
        self,
        playwright,
        context,
        page,
        owned: bool = True,
        commit_delay: float = 0.6,
        verbose: bool = True,
        keep_open: bool = False,
    ) -> None:
        self._pw = playwright
        self.context = context
        self.page = page
        self.owned = owned
        self.commit_delay = commit_delay
        self.verbose = verbose
        self.keep_open = keep_open
        self._waited = False

    def close(self) -> None:
        """关闭会话；keep_open=True 时先等你按回车再关浏览器。"""
        if self.keep_open and not self._waited:
            self._waited = True
            self.wait_forever()
        try:
            if self.owned:
                self.context.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass

    def wait_until_ready(self, timeout: float = 40.0, settle: float = 2.0) -> bool:
        """等 Desmos 加载完成，返回是否就绪。


        """
        deadline = time.time() + timeout
        stable = 0
        last = None
        while time.time() < deadline:
            try:
                loaded = self.page.evaluate(
                    """() => {
                        const ld = document.querySelector('.dcg-loading-div-container');
                        const c = window.Calc;
                        return {
                            loading: !!ld && ld.offsetParent !== null,
                            calc: !!(c && c.getState)
                        };
                    }"""
                )
            except PWError:
                loaded = {"loading": True, "calc": False}

            if not loaded["loading"] and loaded["calc"] and self.row_count() > 0:
                cur = self.state_latex()
                if cur is not None and cur == last:
                    stable += 1
                    if stable >= 2:
                        if settle:
                            time.sleep(settle)
                        return True
                else:
                    stable = 0
                last = cur
            time.sleep(0.3)
        return False

    def row_count(self) -> int:
        """返回当前表达式条数。"""
        ids = self._expression_ids()
        if ids is not None:
            return len(ids)
        try:
            return int(self.page.evaluate(ROW_COUNT_JS))
        except Exception:
            return 0

    def _expression_ids(self) -> Optional[list]:
        """返回所有表达式在 Desmos 里的 id（。"""
        try:
            return self.page.evaluate(IDS_JS)
        except PWError:
            return None

    def _wait_for_row(self, row: int, timeout: float = 3.0) -> bool:
        """等第 row 条表达式出现。

        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            ids = self._expression_ids()
            if ids is not None and row <= len(ids):
                return True
            time.sleep(0.15)
        return False

    def _row_textareas(self) -> list:
        """按页面顺序返回当前已渲染出来的行输入框。"""
        boxes: list = []
        try:
            rows = self.page.query_selector_all(".dcg-expressionitem")
        except PWError:
            rows = []
        for row in rows:
            try:
                box = row.query_selector("textarea")
            except PWError:
                continue
            if box is not None:
                boxes.append(box)
        return boxes

    def _reveal_row(self, expr_id: str, row_number: int, timeout: float = 6.0) -> bool:
        """滚动表达式面板，直到目标行被渲染出来（虚拟滚动下屏幕外的行不在 DOM 里）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                status = self.page.evaluate(REVEAL_JS, [expr_id, row_number])
            except PWError:
                return False
            if status == "found":
                return True
            time.sleep(0.2)
        return False

    def _focus_expression(self, expr_id: str) -> bool:
        """把光标放进指定表达式的输入框，返回是否成功。"""
        try:
            return bool(self.page.evaluate(FOCUS_JS, expr_id))
        except PWError:
            return False

    def expression_error(self, expr_id: str) -> Optional[dict]:
        """返回 Desmos 对该表达式的解析结论。"""
        try:
            return self.page.evaluate(ERROR_JS, expr_id)
        except PWError:
            return None

    def _wait_for_analysis(self, expr_id: str, timeout: float = 2.5) -> Optional[dict]:
        """等 Desmos 把这条表达式的解析结论算出来。


        """
        deadline = time.time() + timeout
        info = None
        while time.time() < deadline:
            info = self.expression_error(expr_id)
            if info is not None:
                return info
            time.sleep(0.1)
        return info

    def _row_has_error(self, expr_id: str) -> bool:
        """判断指定表达式是否被 Desmos 判定为解析失败。"""
        info = self.expression_error(expr_id)
        return bool(info and info.get("isError"))

    def error_message(self, expr_id: str) -> str:
        """返回 Desmos 给出的错误说明，没有错误时返回空字符串。"""
        info = self.expression_error(expr_id)
        return (info or {}).get("message", "") if info else ""

    def state_latex(self) -> Optional[list]:
        """用 Desmos 自己的接口读取每一行的 latex"""
        try:
            return self.page.evaluate(STATE_JS)
        except PWError:
            return None

    def read_row(self, row: int) -> str:
        """读取第 row 行（从 1 开始）输入框里的内容。"""
        ids = self._expression_ids()
        if not ids or not 1 <= row <= len(ids):
            return ""
        expr_id = ids[row - 1]
        self._reveal_row(expr_id, row, timeout=2.0)
        try:
            return self.page.evaluate(
                "(id) => { const r = document.querySelector("
                "'.dcg-expressionitem[expr-id=\"' + id + '\"]');"
                "return r && r.querySelector('textarea')"
                " ? r.querySelector('textarea').value : ''; }",
                expr_id,
            )
        except PWError:
            return ""

    def snapshot(self) -> list:
        """返回所有行输入框里的内容。"""
        try:
            return self.page.evaluate(
                "() => Array.prototype.slice.call(document.querySelectorAll("
                "'.dcg-expressionitem')).filter(r => r.querySelector('textarea'))"
                ".map(r => r.querySelector('textarea').value)"
            )
        except PWError:
            return []

    @staticmethod
    def _to_steps(expression: str) -> list:
        """把表达式转成执行步骤；latex: 前缀表示原样输入，不解析光标指令。"""
        if expression.startswith("latex:"):
            return [("text", expression[len("latex:"):])]
        return _parse_cursor_commands(expression)

    def _press_arrow(self, direction: str) -> None:
        """把光标左移或右移一个字符，优先用硬件方向键，失败时点小键盘按钮。"""
        key = "ArrowLeft" if direction == "left" else "ArrowRight"
        try:
            self.page.keyboard.press(key)
            return
        except PWError:
            pass
        icon = (".dcg-icon-arrow-left" if direction == "left"
                else ".dcg-icon-arrow-right")
        try:
            self.page.locator(icon).first.click(timeout=2000)
        except Exception:
            pass

    def show(self) -> None:
        """把浏览器窗口切到最前面。"""
        try:
            self.page.bring_to_front()
        except PWError:
            pass

    def wait_forever(self) -> None:
        """保持浏览器打开，直到用户按回车。"""
        try:
            input("\n（浏览器保持打开，看完了按回车关闭…）")
        except (EOFError, KeyboardInterrupt):
            pass

    def write(
        self,
        row: int,
        expression: str,
        delay: float = 0.0,
        retries: int = 1,
    ) -> WriteResult:
        """把表达式写入第 row 行（从 1 开始）的输入框。

        """
        steps = self._to_steps(expression)
        typed_text = "".join(s[1] for s in steps if s[0] == "text")
        used_moves = any(s[0] in ("left", "right") for s in steps)

        ids = self._expression_ids()
        if ids is None:
            return WriteResult(False, expression, row, "读不到 window.Calc，无法定位表达式")
        if not ids:
            return WriteResult(False, expression, row, "页面上没有可编辑的表达式行")
        if row > len(ids) and row - len(ids) <= 1:
            if self._wait_for_row(row):
                ids = self._expression_ids() or ids
        if not 1 <= row <= len(ids):
            return WriteResult(
                False, expression, row, f"行号 {row} 超出范围，当前一共 {len(ids)} 行"
            )

        expr_id = ids[row - 1]
        warnings: list = []
        before_state = [s for s in (self.state_latex() or []) if s and s.strip()]

        last_error = ""
        for attempt in range(retries + 1):
            self._reveal_row(expr_id, row)
            focused = self._focus_expression(expr_id)
            if not focused:
                try:
                    self.page.locator(
                        f'.dcg-expressionitem[expr-id="{expr_id}"]'
                    ).click(timeout=3000)
                except Exception:
                    pass
                focused = self._focus_expression(expr_id)
            if not focused:
                last_error = "没能把光标放进该行的输入框"
                continue

            try:
                self.page.keyboard.press("Control+A")
                self.page.keyboard.press("Delete")
            except PWError:
                pass

            try:
                for step in steps:
                    if step[0] == "text":
                        if delay and delay > 0:
                            self.page.keyboard.type(step[1], delay=delay * 1000)
                        else:
                            self.page.keyboard.type(step[1])
                    else:
                        self._press_arrow(step[0])
                        if delay and delay > 0:
                            time.sleep(delay)
            except PWError as exc:
                last_error = f"输入失败：{exc}"
                continue

            try:
                self.page.keyboard.press("Enter")
            except PWError as exc:
                last_error = f"回车失败：{exc}"
                continue

            if self.commit_delay:
                time.sleep(self.commit_delay)

            after_state = self.state_latex()
            if after_state is not None:
                readback = ""
                for s in after_state:
                    if s and s.strip() and same_expression(typed_text, s):
                        readback = s
                        break
                if not readback:
                    after_list = [s for s in after_state if s and s.strip()]
                    new_ones = [s for s in after_list if s not in before_state]
                    if new_ones:
                        readback = max(
                            new_ones,
                            key=lambda s: difflib.SequenceMatcher(
                                None, _normalise(typed_text), _normalise(s)
                            ).ratio(),
                        )
                committed = bool(readback.strip())
                if committed and not used_moves and not same_expression(typed_text, readback):
                    warnings.append(
                        f"Desmos 记录的表达式是 {readback!r}，与输入不完全一致（通常只是排版差异）"
                    )
            else:
                readback = self.read_row(row)
                committed = bool(readback.strip())
                warnings.append("读不到 window.Calc.getState()，已改用输入框内容校验")

            message = ("已写入并回车确定" if committed
                       else (last_error or "回车后没有在图表中找到该表达式"))
            return WriteResult(
                ok=committed,
                expression=expression,
                row=row,
                message=message,
                committed=committed,
                readback=readback,
                before=before_state,
                after=[s for s in (after_state or []) if s and s.strip()],
                warnings=warnings,
            )

        return WriteResult(False, expression, row, last_error or "写入失败")

    def write_via_api(
        self,
        row: Optional[int],
        expression: str,
        settle: float = 0.4,
    ) -> WriteResult:
        """用 Desmos 官方 API 直接把表达式写进第 row 行（从 1 开始）
        """
        latex = expression

        state = self.state_latex()
        if state is None:
            return WriteResult(False, expression, row or 0,
                               "页面上读不到 window.Calc，无法用 API 方式写入")

        before_ids = list(self._expression_ids() or [])
        if row is None:
            payload = {"latex": latex}
        else:
            if not 1 <= row <= len(before_ids) + 1:
                return WriteResult(
                    False, expression, row,
                    f"行号 {row} 超出范围，当前一共 {len(before_ids)} 行",
                )
            if row == len(before_ids) + 1:
                payload = {"latex": latex}
            else:
                payload = {"id": before_ids[row - 1], "latex": latex}

        before = [s for s in state if s and s.strip()]
        try:
            self.page.evaluate(
                "(payload) => window.Calc.setExpression(payload)", payload
            )
        except PWError as exc:
            return WriteResult(False, expression, row or 0, f"调用 Desmos API 失败：{exc}")

        if settle:
            time.sleep(settle)

        after_ids = list(self._expression_ids() or [])
        after_state = self.state_latex() or []

        new_ids = [i for i in after_ids if i not in before_ids]
        appended = row is None or row == len(before_ids) + 1
        if appended:
            target_id = new_ids[-1] if new_ids else (after_ids[-1] if after_ids else None)
            row_number = (after_ids.index(target_id) + 1) if target_id in after_ids else len(after_ids)
        else:
            target_id = before_ids[row - 1]
            row_number = row

        readback = ""
        if target_id in after_ids:
            readback = after_state[after_ids.index(target_id)] or ""
        committed = bool(new_ids) or bool(readback.strip())
        if row is not None and target_id in after_ids:
            committed = bool(readback.strip())

        warnings: list = []
        err = self._wait_for_analysis(target_id) if target_id else None
        has_error = bool(err and err.get("isError"))
        message = "已通过 Desmos API 写入"
        if not committed:
            message = "API 调用后没有在图表中找到该表达式"
        elif has_error:
            reason = (err or {}).get("message") or "Desmos 无法解析这个表达式"
            message = f"已写入，但 Desmos 没能解析：{reason}"
            warnings.append("API 模式按 LaTeX 原样传入，请检查表达式写法"
                            "（函数名要带反斜杠，如 y=\\sin(x)）")

        return WriteResult(
            ok=committed and not has_error,
            expression=expression,
            row=row_number,
            message=message,
            committed=committed,
            readback=readback,
            before=before,
            after=[s for s in (after_state or []) if s and s.strip()],
            warnings=warnings,
        )


def _nudge_resize(page) -> None:
    """给页面补一次 resize 信号，让 Desmos 重算画布尺寸。"""
    try:
        page.evaluate("window.dispatchEvent(new Event('resize'))")
    except Exception:
        pass


def _maximize_window(page) -> None:
    """把浏览器窗口最大化到占满屏幕，并让页面按新尺寸重新布局。"""
    try:
        cdp = page.context.new_cdp_session(page)
        info = cdp.send("Browser.getWindowForTarget")
        cdp.send(
            "Browser.setWindowBounds",
            {"windowId": info["windowId"], "bounds": {"windowState": "maximized"}},
        )
    except Exception:
        return

    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            filled = page.evaluate(
                "() => window.outerWidth >= screen.availWidth - 4"
                " && window.outerHeight >= screen.availHeight - 4"
            )
        except Exception:
            break
        if filled:
            break
        time.sleep(0.15)
    _nudge_resize(page)


def open_desmos(
    url: str = DEFAULT_URL,
    headless: bool = False,
    channel: Optional[str] = None,
    profile_dir: Optional[str] = None,
    attach_port: Optional[int] = None,
    wait_timeout: float = 45.0,
    commit_delay: float = 0.6,
    verbose: bool = True,
    keep_open: bool = False,
) -> DesmosSession:
    """打开 Desmos 页面并返回会话对象。

    """
    if os.environ.get("DESMOS_TEMP_DIR"):
        _use_temp_dir(os.environ["DESMOS_TEMP_DIR"])
    elif os.environ.get("TEMP") and not os.path.isdir(os.environ["TEMP"]):
        _use_temp_dir(_fallback_temp_dir())

    pw = sync_playwright().start()

    if attach_port:
        if verbose:
            print(f"正在接管已打开的浏览器（调试端口 {attach_port}）…")
        kwargs: dict = {}
    else:
        if profile_dir is None:
            profile_dir = str(_user_data_dir() / "profile")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        kwargs = dict(
            user_data_dir=profile_dir,
            headless=headless,
            no_viewport=True,
            args=[
                "--start-maximized",
                "--no-default-browser-check",
                "--disable-logging",
                "--log-level=3",
            ],
        )
        if channel:
            kwargs["channel"] = channel
        if verbose:
            print(f"正在启动浏览器（配置目录：{profile_dir}）…")

    try:
        ctx, owned = _boot_context(pw, attach_port, kwargs)
    except PWError as exc:
        if attach_port or not _is_temp_error(exc):
            raise
        fallback = _fallback_temp_dir()
        if verbose:
            print(f"⚠ 临时目录不可写（{type(exc).__name__}），改用：{fallback}")
        _use_temp_dir(fallback)
        try:
            pw.stop()
        except Exception:
            pass
        pw = sync_playwright().start()
        try:
            ctx, owned = _boot_context(pw, attach_port, kwargs)
        except PWError as exc2:
            if _is_temp_error(exc2):
                raise RuntimeError(
                    "浏览器启动失败：临时目录不可写。\n"
                    f"已尝试：{fallback}\n"
                    "可以手动指定一个可写的临时目录再运行，例如：\n"
                    '  PowerShell:  $env:DESMOS_TEMP_DIR="D:\\temp"\n'
                    "  cmd:         set DESMOS_TEMP_DIR=D:\\temp"
                ) from exc2
            raise

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    session = DesmosSession(pw, ctx, page, owned=owned, commit_delay=commit_delay,
                            verbose=verbose, keep_open=keep_open)

    if owned and not headless:
        _maximize_window(page)

    current = ""
    try:
        current = page.url or ""
    except PWError:
        pass

    if "desmos.com" not in current:
        if verbose:
            print(f"正在打开：{url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    elif verbose:
        print(f"已接管当前页面：{current}")

    if not session.wait_until_ready(wait_timeout):
        session.close()
        raise RuntimeError(
            "等待 Desmos 加载超时：没有找到表达式列表。\n"
            "请确认网络能访问 desmos.com，或者去掉 headless 再试。"
        )

    session.show()
    if not headless:
        _maximize_window(page)
    if verbose:
        print(f"Desmos 已就绪（当前 {session.row_count()} 个可编辑表达式行）。")
    return session


def write_expression(
    session: DesmosSession,
    row: int,
    expression: str,
    delay: float = 0.0,
    retries: int = 1,
) -> WriteResult:
    """把表达式写入第 row 行（从 1 开始）的输入框，覆盖原有内容并回车确定。
    """
    return session.write(row, expression, delay=delay, retries=retries)


def write_expression_api(
    session: DesmosSession,
    row: Optional[int],
    expression: str,
) -> WriteResult:
    """用 Desmos 官方 API 把表达式写进第 row 行（从 1 开始）


    """
    return session.write_via_api(row, expression)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    p = argparse.ArgumentParser(
        description="用 Playwright 把数学表达式写入 Desmos 网页指定行的输入框并回车确定。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        '  python desmos_writer.py "z=x^2+y^2"\n'
        '  python desmos_writer.py "z=x^2+y^2" "z=sin(x)cos(y)"\n'
        "  python desmos_writer.py -i\n",
    )
    p.add_argument("expressions", nargs="*",
                   help="要写入的表达式，依次写入第 1、2、3… 行")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="交互式输入，格式为「行号 表达式」")
    p.add_argument("--url", default=DEFAULT_URL, help="Desmos 页面地址")
    p.add_argument("--channel", default=None, choices=("msedge", "chrome"),
                   help="用哪个浏览器内核（默认 Playwright 自带的 chromium）")
    p.add_argument("--headless", action="store_true", help="无界面模式（看不到图形）")
    p.add_argument("--profile-dir", default=None, help="浏览器配置目录（保存登录状态）")
    p.add_argument("--attach-port", type=int, default=None,
                   help="接管已打开浏览器，例如 9222")
    p.add_argument("--delay", type=float, default=0.0,
                   help="每个字符的输入间隔秒数（默认 0，最快）")
    p.add_argument("--close-browser", action="store_true", help="写完后关闭浏览器")
    return p


def _run_cli(args: argparse.Namespace) -> int:
    """执行命令行流程，返回进程退出码。"""
    session = open_desmos(
        url=args.url,
        headless=args.headless,
        channel=args.channel,
        profile_dir=args.profile_dir,
        attach_port=args.attach_port,
    )
    results = []
    try:
        for i, expr in enumerate(args.expressions or [], start=1):
            r = session.write(i, expr, delay=args.delay)
            print(r)
            for w in r.warnings:
                print(f"       ⚠ {w}")
            results.append(r)

        if not args.expressions and not args.interactive:
            args.interactive = True

        if not args.interactive:
            if not args.close_browser:
                session.wait_forever()
            return 1 if any(not r.ok for r in results) else 0

        print("\n交互模式：输入「行号 表达式」，例如  2 z=x^2+y^2")
        print("只输入表达式时会依次写到下一行；输入 q 退出。\n")
        next_row = len(args.expressions or []) + 1
        while True:
            try:
                line = input(f"第{next_row}行> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.lower() in ("q", "quit", "exit"):
                break
            if not line:
                continue
            m = re.match(r"^(\d+)\s+(.+)$", line)
            if m:
                row, expr = int(m.group(1)), m.group(2)
            else:
                row, expr = next_row, line
            r = session.write(row, expr, delay=args.delay)
            print(r)
            for w in r.warnings:
                print(f"       ⚠ {w}")
            results.append(r)
            next_row = r.row + 1

        if not args.close_browser:
            session.wait_forever()
        return 0 if all(r.ok for r in results) else 1
    finally:
        session.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    try:
        return _run_cli(args)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except PWError as exc:
        print(f"浏览器错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
