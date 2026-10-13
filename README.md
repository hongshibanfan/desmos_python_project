# desmos-writer

用 Playwright 或者官方api把数学表达式写入 Desmos 网页的自动化工具。

提供两种写入方式：

- **模拟键盘输入**：像真人一样把表达式敲进输入框并按回车确定，支持 `$` / `@` 控制光标位置。
- **官方 API 输入**：用 调Desmos 的 `Calc.setExpression`

两种方式可以混用。

- 行号从 **1** 开始，可与"第几条表达式"直接对应；越界不写入并返回失败结果
- 键盘模式在写入前会把目标行滚进可视区，表达式条数再多也能继续写
- API 模式完全不受鼠标拖动、窗口焦点、面板滚动的影响
- 写入后用 Desmos 自身的解析结果（`expressionAnalysis`）校验，解析失败会给出原因
- 附带环境自检、离线测试和真实站点验证脚本

## 安装

在本项目目录下执行：

```bat
python -m pip install -e .
python -m playwright install chromium
```

第一条命令会安装本包以及它依赖的 `playwright`；第二条下载浏览器内核（只需执行一次）。

安装完成后：

- 在**任意目录**都可以 `import desmos_writer_pack`
- 命令行多出一个 `desmos-writer` 命令
- 也可以 `python -m desmos_writer_pack` 运行

如果不想安装，在项目目录内直接运行脚本也可以（包就在当前目录下）。

### 浏览器数据目录

浏览器配置和临时文件默认放在用户目录，而不是包目录里：

| 系统 | 位置 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\desmos-writer\` |
| macOS | `~/Library/Application Support/desmos-writer/` |
| Linux | `~/.local/share/desmos-writer/` |

其中 `profile/` 是浏览器配置（登录状态保存在这里），`tmp/` 是临时文件。
可用环境变量 `DESMOS_WRITER_HOME` 指定到别处，也可以在 `open_desmos(profile_dir=...)` 里单独指定。

## 安装依赖包playwright

```bat
python -m pip install playwright
python -m playwright install chromium
```

## 快速开始

```python
#关键api
write_expression()    #使用日常手写写法

write_expression_api()   #使用latex写法

```






```python
from desmos_writer import open_desmos, write_expression, write_expression_api

s = open_desmos(keep_open=True)

write_expression(s, 1, "z=x^2+y^2")          # 模拟键盘，写入第 1 行并回车
write_expression(s, 2, "z=sin(x)cos(y)")     # 模拟键盘，写入第 2 行

write_expression_api(s, None, r"z=\cos(x)")  # API 追加一条（注意是 LaTeX 写法）
write_expression_api(s, 1, r"z=\sin(x)")     # API 覆盖第 1 行

s.close()
```

`keep_open=True` 时，`close()` 会等待回车再关闭浏览器，便于查看结果。

命令行方式：

```bat
python desmos_writer.py "z=x^2+y^2"                       :: 依次写入第 1、2… 行
python desmos_writer.py -i                                :: 交互式，输入「行号 表达式」
```

## 两种方式对比

| | 模拟键盘 `write_expression` | 官方 API `write_expression_api` |
| --- | --- | --- |
| 是否经过输入框 | 是，真实敲键盘并回车 | 否，直接改数据 |
| 表达式写法 | 日常数学写法，如 `z=sin(x)` | **LaTeX**，如 `z=\sin(x)` |
| `$` / `@` 光标控制 | 支持 | 不支持，按字面传入 |
| 鼠标拖动图形时 | 可能丢失焦点导致中断 | 完全不受影响 |
| 适合场景 | 需要还原人工输入过程 | 批量、长时间、无人值守 |

## 方式一：模拟键盘

```python
write_expression(session, row, expression, delay=0.0, retries=1) -> WriteResult
```

| 参数 | 说明 |
| --- | --- |
| `session` | `open_desmos()` 返回的会话对象 |
| `row` | 写入第几行，从 **1** 开始 |
| `expression` | 表达式，可以是日常数学写法 |
| `delay` | 每个字符的输入间隔秒数，默认 0（最快）。设成 `0.05` 左右更接近真人输入 |
| `retries` | 写入失败时的重试次数，默认 1 |

**行号规则**：`row` 必须落在 `1 … 当前条数` 之间。超出范围时不写入，直接返回
`ok=False` 的结果，`message` 中说明原因。

该行已有内容会先被清空，再输入新内容并回车确定。

### 光标控制

表达式中可以插入两个符号来移动输入光标：

| 符号 | 作用 |
| --- | --- |
| `$` | 光标左移一个字符 |
| `@` | 光标右移一个字符 |
| `\$` | 真正的 `$` 字符 |
| `\@` | 真正的 `@` 字符 |

每个符号生效一次，因此 `$$$` 表示左移三次。加了 `latex:` 前缀时这两个符号按字面输入，
不做移动。

示例：

```
z=12$3       →  z=132       输入 12 后左移一格，再输入 3
z=12$@3      →  z=123       左移再右移，回到末尾
z=123$$4     →  z=1423      左移两格后输入 4
```

光标移动优先使用硬件方向键 `ArrowLeft` / `ArrowRight`；若未生效，会改为点击
Desmos 小键盘上的 `.dcg-icon-arrow-left` / `.dcg-icon-arrow-right` 按钮。
两者实测行为一致，均移动一个字符。

### 影响结果的两条 Desmos 自身规则

1. **自动补括号**：输入 `(` 时 Desmos 会立即补上 `)`。因此 `z=sin($x)` 的实际结果
   是 `\left(z=\sin x\right)\left(\right)` 而不是 `z=sinx)(`——括号先就位，左移一格
   会直接退出空括号。
2. **单字母变量会生成滑块**：`z=ab` 这类含未定义变量的表达式，Desmos 会自动创建
   `a=1`、`b=1` 等滑块行。这与本工具无关。

## 方式二：官方 API

```python
write_expression_api(session, row, expression) -> WriteResult
```

| 参数 | 说明 |
| --- | --- |
| `session` | `open_desmos()` 返回的会话对象 |
| `row` | 写入第几行，从 **1** 开始；传 `None` 表示追加 |
| `expression` | **按 LaTeX 原样传入**，程序不做任何转换 |

**行号规则**：

- `1 ≤ row ≤ 当前条数`：覆盖该行
- `row == 当前条数 + 1`：新建一条，成为第 `row` 行
- `row > 当前条数 + 1`：报错，不写入
- `row = None`：追加到最后

第二条规则是必要的：API 覆盖已有行不会让列表变长，如果"下一行"也报错，
那么 `写第 1 行` 紧接着 `写第 2 行` 这种最自然的用法第二步就会失败。

### 表达式写法

`expression` 会被原样交给 Desmos，因此需要写成 **LaTeX**：

```
通常写法                  API 模式应写
z=sin(x)cos(y)      →     z=\sin(x)\cos(y)
z=sqrt(x)           →     z=\sqrt{x}
z=x^2+y^2           →     z=x^2+y^2           （幂不必加花括号）
z=nthroot(x,3)      →     z=\nthroot(x,3)
```

写成日常写法（如 `z=sin(x)`）不会报错退出，但 Desmos 会把 `sin` 拆成 `s`、`i`、`n`
三个变量，此时 `ok=False`，`message` 中会给出 Desmos 的原始提示。

### 解析校验

每次写入后，工具会读取 Desmos 的 `expressionAnalysis`：

- 解析成功：`ok=True`
- 解析失败：`ok=False`，`message` 形如
  `已写入，但 Desmos 没能解析：变量太多。请尝试定义"s"、"i"或"n"。`

## plain_to_latex（可选工具，任然存在一些bug，待修理）

`plain_to_latex` 把日常数学写法转成 Desmos 可用的 LaTeX。**API 模式不会自动调用它**，
需要时手动使用：

```python
from desmos_writer import plain_to_latex

latex = plain_to_latex("z=sin(x)cos(y)")   # -> 'z=\\sin(x)\\cos(y)'
write_expression_api(s, 1, latex)
```

转换只做一件事：**给函数名补反斜杠**。`sqrt` 例外，会连同括号一起换成 `\sqrt{...}`。

覆盖的函数名：

```
sin cos tan cot sec csc arcsin arccos arctan ln log sqrt abs exp
sinh cosh tanh floor ceil round sign min max gcd lcm mod nthroot
```

常量：`pi` → `\pi`

**函数名前的字符判定**：

| 前面的字符 | 是否转换 | 示例 |
| --- | --- | --- |
| 数字 | 是（隐含乘法） | `5cos(x)` → `5\cos(x)` |
| `x` `y` `R` `θ` | 是（隐含乘法） | `xcos(t)` → `x\cos(t)`、`Rcos(θ)` → `R\cos(θ)` |
| 其他字母 | 否（视为变量名的一部分） | `asin(x)`、`spin(x)`、`zcos(x)` 原样保留 |
| 其他符号 | 是 | `5*cos(x)` → `5*\cos(x)` |

已经带反斜杠的部分不会重复添加。

## open_desmos 参数

```python
open_desmos(
    url=DEFAULT_URL, headless=False, channel=None, profile_dir=None,
    attach_port=None, wait_timeout=45.0, commit_delay=0.6,
    verbose=True, keep_open=False,
) -> DesmosSession
```

| 参数 | 说明 |
| --- | --- |
| `url` | 目标页面，默认 `https://www.desmos.com/calculator?lang=zh-CN` |
| `headless` | 无界面运行；图形不可见，仅适合批量任务 |
| `channel` | 指定浏览器内核（`"msedge"` / `"chrome"`），默认使用 Playwright 自带的 chromium |
| `profile_dir` | 浏览器配置目录，默认在用户数据目录（见上文"浏览器数据目录"） |
| `attach_port` | 接管已用调试端口启动的浏览器，不会新开窗口 |
| `wait_timeout` | 等待页面加载完成的秒数 |
| `keep_open` | 为 `True` 时 `close()` 会等待回车再关闭浏览器 |

### WriteResult

`write_expression` 与 `write_expression_api` 都返回 `WriteResult`：

| 字段 | 说明 |
| --- | --- |
| `ok` | 是否成功 |
| `row` | 实际写入的行号 |
| `message` | 结果说明；失败时说明原因 |
| `committed` | 表达式是否已进入图表 |
| `readback` | 从 Desmos 读回的 LaTeX |
| `warnings` | 需要留意的提示（不会导致失败） |

`WriteResult` 支持布尔判断，可直接用于 `if`。


## 目录结构

```
desmos-writer/
├── desmos_writer_pack/        包本体（分发的就是这个）
│   ├── __init__.py            对外导出
│   ├── __main__.py            支持 python -m desmos_writer_pack
│   └── desmos_writer.py       全部实现
├── desmos_writer.py           单文件版，内容与包内一致，可直接拷走使用
├── tests/                     离线测试
│   ├── mock_desmos.py         模拟的 Desmos 页面
│   └── test_desmos_writer.py  自动化测试
├── tools/                     自检与验证脚本
│   ├── check_convert.py       转换规则自检
│   ├── check_sync.py          两个副本是否一致
│   ├── check_env.py           环境自检
│   └── verify_upgrade.py      真实站点验证
├── examples/                  示例脚本
├── pyproject.toml             打包配置
├── MANIFEST.in                源码包包含哪些文件
├── LICENSE
└── README.md
```

| 文件 | 用途 |
| --- | --- |
| [desmos_writer_pack/](desmos_writer_pack) | 包本体，`import desmos_writer_pack` |
| [desmos_writer.py](desmos_writer.py) | 单文件版，可脱离包单独拷贝使用 |
| [tests/](tests) | 离线自动化测试与模拟页面，不联网 |
| [tools/check_convert.py](tools/check_convert.py) | 普通写法 → LaTeX 的转换规则自检 |
| [tools/check_sync.py](tools/check_sync.py) | 检查包内版与单文件版是否一致 |
| [tools/check_env.py](tools/check_env.py) | 环境自检：解释器、依赖、临时目录、浏览器 |
| [tools/verify_upgrade.py](tools/verify_upgrade.py) | 连真实 Desmos 的实弹验证 |
| [examples/](examples) | 使用示例 |

## 测试与自检

| 命令 | 用途 | 是否联网 |
| --- | --- | --- |
| `python tests/test_desmos_writer.py` | 离线自动化测试，跑在本地模拟页面上 | 否 |
| `python tools/check_convert.py` | 普通写法 → LaTeX 的转换规则自检 | 否 |
| `python tools/check_sync.py` | 检查包内版与单文件版是否一致 | 否 |
| `python tools/check_env.py` | 环境自检：解释器、依赖、临时目录、浏览器启动 | 是 |
| `python tools/verify_upgrade.py` | 真实站点验证：自动滚动、API 写入、解析校验 | 是 |

`verify_upgrade.py` 还可以指定要验证的模块：

```bat
python tools/verify_upgrade.py desmos_writer_pack     :: 验证包
python tools/verify_upgrade.py desmos_writer          :: 验证单文件版
```

这些脚本都会自动把项目根目录加入 `sys.path`，所以在仓库里直接运行即可，不需要先安装。

## 常见问题

**启动浏览器时报 `EPERM ... mkdtemp '...\playwright-artifacts-XXXXXX'`**

临时目录不可写。程序会自动检测并切换到用户数据目录下的 `tmp/`，并在输出中提示。
也可以手动指定：

```powershell
$env:DESMOS_TEMP_DIR="D:\temp"
```
```bat
set DESMOS_TEMP_DIR=D:\temp
```

**提示"行号 N 超出范围"**

`row` 超过了当前表达式条数。API 模式下允许等于"当前条数 + 1"以新建一行，再往后则报错。
可用 `row=None` 直接追加。

**API 写入后 `ok=False`，提示"Desmos 没能解析"**

表达式不是合法 LaTeX。常见原因是函数名缺少反斜杠，例如写成了 `z=sin(x)`。
可参考本文档"表达式写法"一节，或先用 `plain_to_latex` 转换。

**键盘模式写入中途停止**

通常是手动拖动了图形区域，输入框失去焦点。可改用 API 模式，该模式不依赖焦点。

**想使用已登录的浏览器**

以调试端口启动浏览器后接管：

```bat
msedge.exe --remote-debugging-port=9222
```
```python
s = open_desmos(attach_port=9222)
```

## 已知限制

- 页面结构依赖 Desmos 当前的 DOM（表达式行的 `expr-id` 属性、面板类名等）。
  若 Desmos 大幅改版，定位逻辑可能需要相应调整。
- 本工具用于自动化操作 desmos.com，公开分发前请自行确认符合该站点的使用条款。
