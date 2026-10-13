"""Offline mock of the Desmos expression list, mirroring the REAL DOM.

Key details copied from the live calculator (see probe results):
  * each expression row is ``div.dcg-expressionitem.dcg-mathitem``
  * the row's ``<textarea>`` is a 0x0 hidden scratch input (MathQuill pattern),
    so it is NOT "visible" and Playwright's fill() cannot be used on it
  * there is a trailing ``.dcg-expressionitem.dcg-new-expression`` row with no
    textarea; clicking it turns into a fresh editable row
  * only committed expressions appear in ``window.Calc.getState()``

Run standalone:  python mock_desmos.py [port]      (default 8765)
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>未命名图表 | Desmos (mock)</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0;background:#fff;color:#111}
  #panel{width:360px;padding:8px;border-right:1px solid #ddd;height:100vh;box-sizing:border-box;overflow:auto}
  .dcg-expressionitem{border:1px solid #e3e3e3;border-radius:4px;margin:6px 0;padding:6px;min-height:34px}

  .dcg-expressionitem textarea{width:0;height:0;padding:0;border:0;opacity:1}
  .shown{font:15px monospace;color:#111;min-height:18px}
  .dcg-new-expression{color:#999;cursor:pointer}
  .bad .shown{color:#d33}
</style></head>
<body>
<div id="panel">
  <div id="expression-list"></div>
  <div class="dcg-expressionitem dcg-new-expression" id="newrow" onclick="activateNew()">+ 新建表达式</div>
</div>
<script>
var _seq = 0;

function newRow() {
  var id = _seq++;
  var item = document.createElement('div');
  item.className = 'dcg-expressionitem dcg-mathitem';
  item.setAttribute('data-mock-id', id);
  item.setAttribute('expr-id', 'e' + id);
  item.setAttribute('aria-label', '表达式' + (id + 1));
  var shown = document.createElement('div');
  shown.className = 'shown';
  var ta = document.createElement('textarea');

  ta.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); commit(item); }
  });
  item.appendChild(shown);
  item.appendChild(ta);
  document.getElementById('expression-list').appendChild(item);
  return item;
}

function analyse(item) {
  var latex = item.getAttribute('data-latex') || '';
  var id = item.getAttribute('expr-id');

  var bad = !!(latex && (/(^|[^\\\w])(sin|cos|tan|sqrt)\s*\(/.test(latex)
                         || /@@@/.test(latex)));
  window.Calc.expressionAnalysis[id] = {
    isGraphable: !!latex && !bad,
    isError: bad,
    errorMessage: bad ? '变量太多。请尝试定义"s"、"i"或"n"。' : ''
  };
}

function commit(item) {
  var ta = item.querySelector('textarea');
  var v = ta.value.trim();
  item.querySelector('.shown').textContent = v;
  item.setAttribute('data-committed', '1');
  item.setAttribute('data-latex', v);
  item.classList.toggle('bad', !v);
  analyse(item);

  var rows = editableRows();
  if (v && rows[rows.length - 1] === item) newRow();
}


function activateNew() {
  var item = newRow();
  item.querySelector('textarea').focus();
  return item;
}

function editableRows() {
  return [].filter.call(document.querySelectorAll('.dcg-expressionitem'),
                        function (r) { return r.querySelector('textarea'); });
}

window.Calc = {
  expressionAnalysis: {},
  getState: function () {
    return { version: 9, expressions: { list: [].map.call(editableRows(), function (it) {

      return { id: 'e' + it.getAttribute('data-mock-id'),
               latex: it.getAttribute('data-latex') || '',
               committed: it.hasAttribute('data-committed') };
    }) } };
  },
  setExpressions: function (state) {
    document.getElementById('expression-list').innerHTML = '';
    _seq = 0;
    (state.expressions.list || []).forEach(function (e) {
      var r = newRow();
      r.querySelector('textarea').value = e.latex || '';
      commit(r);
    });
  },

  setExpression: function (expr) {
    var rows = editableRows();
    var target = null;
    if (expr && expr.id) {
      for (var k = 0; k < rows.length; k++) {
        if ('e' + rows[k].getAttribute('data-mock-id') === expr.id) {
          target = rows[k];
          break;
        }
      }
    }
    if (!target) target = newRow();
    var latex = (expr && expr.latex) || '';
    target.setAttribute('data-latex', latex);
    target.setAttribute('data-committed', '1');
    target.querySelector('.shown').textContent = latex;
    analyse(target);

    var all = editableRows();
    if (all[all.length - 1].getAttribute('data-latex')) newRow();
    return target;
  },
  removeExpression: function (expr) {
    var rows = editableRows();
    for (var k = 0; k < rows.length; k++) {
      if ('e' + rows[k].getAttribute('data-mock-id') === (expr && expr.id)) {
        rows[k].remove();
        return;
      }
    }
  }
};


window.__keys = [];
document.addEventListener('keydown', function (e) { window.__keys.push('down:' + e.key); });
document.addEventListener('keyup', function (e) { window.__keys.push('up:' + e.key); });
document.addEventListener('input', function () { window.__inputs = (window.__inputs || 0) + 1; });


newRow();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = serve(p)
    print(f"mock Desmos serving at http://127.0.0.1:{p}/  (Ctrl+C to stop)")
    print(json.dumps({"ok": True}))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
