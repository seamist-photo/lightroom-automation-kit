# lrc-kit

给 Adobe Lightroom Classic 做自动化的实用工具集。三个小工具，每个都对应一个真实痛点：要么让你少重启一次 Lightroom，要么让你少点一次鼠标，要么让"颜色像不像"变成数字而不是感觉。

```bash
pip install lrc-kit              # 核心：零依赖
pip install "lrc-kit[color]"     # 加 numpy + pillow（颜色校验）
pip install "lrc-kit[preflight]" # 加 lupa（跑 Lua 逻辑测试）
```

## 三个工具

**`preflight` —— 不用重启 Lightroom 就能验插件代码**

用**真正的 Lua 5.1 编译器**（`luac5.1 -p`）做语法检查。这件事的重要性在于：Lightroom 跑的是 5.1，而 Python 的 lupa 绑定跑的是 5.4/5.5，会拒绝 5.1 里完全合法的写法（`attempt to assign to const variable` 就是最典型的误报）。用错版本去查，你会去找一个根本不存在的逻辑 bug。

```console
$ lrc-kit preflight syntax MyPlugin.lua
{"ok": true, "items": [{"file": "MyPlugin.lua", "status": "ok", "detail": ""}],
 "notes": ["checked with Lua 5.1.5  Copyright (C) 1994-2012 Lua.org, PUC-Rio"]}
```

**`catalog` —— 不打开 Lightroom 直接读 `.lrcat`**

它就是一个 SQLite 库，只读连接，Lightroom 开着也能读。带两个关键判断：

- **空壳检测**：一个新建的库约 2MB，真实库是几百 MB。把空壳当成"库是空的"，是很常见的错结论。
- **撞号检测**：`_MIS7102.NEF` 在两个不同场次目录里各有一张，这是正常现象。按文件名找图必须返回全部副本并标记冲突，而且要用**目录名**去区分，不能用日期窗口（导出的 JPG 和它的 RAW 常常不是同一个拍摄时间）。

此外，它能区分"这张有调色参数"和"这张真的被调过"——`Adobe_imageDevelopSettings` 对每张照片都有一行，是否编辑过要看 `Adobe_libraryImageDevelopHistoryStep`。

```console
$ lrc-kit catalog style /path/to/Catalog.lrcat --pretty
{"images_total": 9351, "top_sliders": ["Temperature", "Exposure2012", ...],
 "exposure_stdev_by_day": {...}, "reading": "editing is concentrated on a few sliders ..."}
```

**`color` —— 把"像不像"变成数字**

两张图可以看起来差不多，但在高光区差 6 个 dE。`color eval` 给的是分位数和分区偏差，不是形容词。

CIEDE2000 是按 CIE 规范手写的实现，并且用 **Sharma 等人发表的 11 组标准测试向量**验证过——不是拿自己的输出当标准。

## 文档（真正的价值在这里）

代码是小头，知道"为什么必须这么写"才是大头：

| 文档 | 省掉什么 |
|---|---|
| [插件加载与执行上下文](docs/plugin-loading-and-execution-contexts.md) | 为什么你的插件显示"正在运行"但 `Init.lua` 从没执行；三个执行上下文各自对 yield 和写锁的规则 |
| [catalog 直读](docs/catalog-sqlite.md) | 四表联查、空壳陷阱、撞号、以及"有参数行 ≠ 编辑过" |
| [XMP 三种形态](docs/xmp-and-profiles.md) | 三个同名不同义的"XMP"；为什么把预设文件丢到照片目录里毫无作用 |
| [专有 RAW 解码](docs/raw-decoding.md) | 为什么尼康 HE-NEF 这类格式开源栈根本解不了（是编解码缺口，不是画质差异） |
| [现有方案对照](docs/prior-art.md) | 有哪些现成方案，用实测数字而不是印象，以及什么时候别自己写 |

`examples/minimal-bridge/` 是一个能装的四文件插件骨架，专门演示那几处要命的地方：eager load 标志、init 脚本里自启动、带写锁的写路径、以及一个永远不会打断运行中服务的状态面板。

## 设计原则

不是为了好看，每一条都是先答错过一次才写下来的：

1. **只给数字或退出码，不给叙述。** 每个检查输出 JSON 或非零状态码。
2. **绝不写 catalog。** 只读连接，改参数走插件 API 或 `.xmp` sidecar。
3. **不抽样。** 调色是成批做的，抽样会把你要找的规律打散。
4. **优用真运行时。** Lua 5.1 编译器胜过更新的内嵌解释器；真实结构的 fixture 胜过 mock。
5. **标明来源。** 需要专有素材才能复现的结论，在文档里明确标注，不伪装成 CI 验证过的结果。

## 状态

38 个测试，`python -m unittest discover` 即可跑，不联网、不用私有素材；色彩数学用公开标准向量验证。

## 许可

MIT。
