# Proteus 8.6 使用手册

本页收录详细操作、API 和历史验证记录。所有命令均从源码根目录运行；功能简介见 [项目首页](../README.md)。

源码公开范围、MIT 归属及尚未解决的 Proteus 使用条款风险见 [公开与许可说明](publication.md)。源码许可不替代 Proteus 商业软件许可；本项目不包含厂商程序、器件库或模板。

> **适用范围：Codex 与 DeepSeek Harness 共用同一套 Python 核心、结构化接口、技能及验收规则。** 能力与证据范围见 [双平台适配](platform-parity.md)，dsh 配置见 [使用说明](dsh-integration.md)。其他 harness 仍需独立集成；不能把某个平台的历史仿真结果当作另一个平台的新验收。

已在本机 **Proteus 8.6 SP2，build 23525** 验证。供 Codex 与 dsh 共用的核心通过 Python 直接读写保存的 `.pdsprj`，完成摆件、布线、修改、核网和预览。常规文件流程不启动 Proteus，不用 Computer Use。

功能目标参考 [RACErace/pdsprj-auto](https://github.com/RACErace/pdsprj-auto)，适配已验证的 Proteus 8.6 保存格式。当前候选版本 **0.9.2b1（双平台 Beta）**，见 [发布说明](release-0.9.2-beta.1.md)和[安装与打包](packaging.md)。文件生成、布线与检查只需 Python 3.10+ 标准库；原生验证需要本机已授权安装，运行截图另需可选的 Pillow>=11.2.1。来源与许可见 [THIRD_PARTY.md](../THIRD_PARTY.md)，共用流程见 [SKILL.md](../skills/proteus86-files/SKILL.md)。

优先级：**功能 → 稳定性 → 速度 → 排版**。0.9.1 增加公开可复现的矩阵/数码管验证脚本、端子文字坐标接口和启动中断清理，改善独立示例的短直线与端子排版。`scripts/verify_matrix_display.py` 默认只准备文件；只有显式 `--execute-native` 才启动本次自有 Proteus，`--capture` 另行请求运行截图。

历史 0.9.1 的 48 元件布局已通过原生起仿、运行画面、保存/Python 重读、29 个期望网络和 39 个原生网络检查；118/120 条导线为直线、共 4 个折弯，在默认及一个原生单位的最短并行区段检查下均无报告的叠线、非结点接触或过近并行。仍保留 35 条保守文字估算警告。该版本 CLI 原生验收包含 16 键按 5/5/5/1 顺序分组、25 次显示重建、658 个原生 SDF 样本、118 次输入状态回读；四个自有进程正常关闭且源文件不变，295 项回归通过、0 跳过。双平台实际模型与原生验收另见 [dsh 适配记录](validation/dsh-parity-20261028.json)，其中的 646 次采样不与历史 658/670 次混用。

本次发布包的文件回归、隔离安装与双平台技能检查见 [Beta 打包记录](validation/release-v092b1-20261028.json)。打包阶段没有启动 Proteus；既有双平台原生结果仍属于打包前的源码验证，安装后的 wheel 未重新进行原生仿真，dsh 网页界面交互也仍未验证。[0.9.1 说明](release-0.9.1.md)、[0.9.0 说明](release-0.9.0.md)及[历史验收](../skills/proteus86-files/references/history.md)保留原版本范围。

## 立即使用

在本目录打开 PowerShell，无需 pip 安装：

```powershell
python -m proteus86 doctor
python -m proteus86 generate proteus86\examples\parallel.txt -o output\my_parallel86.pdsprj
python -m proteus86 netcheck output\my_parallel86.pdsprj --design proteus86\examples\parallel.txt
python -m proteus86 render output\my_parallel86.pdsprj -o output\my_parallel86.svg
```

用 Proteus 打开结果后，元件和导线可继续编辑。目标已存在时默认拒绝写入；工程命令明确加 `--overwrite` 才能覆盖，并先创建、核对独立备份。布局文本和 SVG 使用新文件名。

Codex 在本项目会读取 `AGENTS.md`，优先使用文件接口。要让其他项目也发现此技能，运行 `python scripts\install_codex_skill.py`，将已校验的技能复制到当前用户的 Codex 技能目录；目标内容不同时默认拒绝覆盖，明确加 `--update` 才会备份并更新。技能名为 `$proteus86-files`，描述匹配时也可自动选用；若当前对话未刷新技能列表，在后续对话使用。

本机现成结果：

- 并联电阻工程（本机生成记录，不随源码分发）：两个电阻、VCC/GND，真实 Proteus 网表验收通过。
- AT89C52 自动布局布线工程（本机生成记录，不随源码分发）及 SVG 预览（本机生成记录，不随源码分发）：芯片、电阻、LED 的文件画图示例，未加载固件。
- LED 工程（本机生成记录，不随源码分发）：此前已在 Proteus 界面实际点亮。
- 25 元件运行工程（本机生成记录，不随源码分发）：8 路 LED 固件验证通过。
- 42 元件运行工程（本机生成记录，不随源码分发）：已修复继电器额定值，实际运行日志无错误/警告，LED 与触点随固件切换。
- 25 元件工程（本机生成记录，不随源码分发）和 42 元件工程（本机生成记录，不随源码分发）：标号避让、隐藏 PROGRAM/CLOCK 显示，几何检查无警告；已通过原生保存读回和 0.5 的实际运行/计时/日志检查。
- 无 MCU 的原生 LED 仿真包（本机生成记录，不随源码分发）及 实际运行结果（本机生成记录，不随源码分发）：真实引擎运行 0.25 秒仿真时间，日志无错误/警告，源工程未改动。

两个运行工程需要保留旁边的 `output/firmware/blink8051.hex`。源码为 [blink8051.a51](../examples/blink8051.a51)，随附编译好的 HEX，无需 Keil 即可生成和运行这些示例。重新生成独立副本：

```powershell
python scripts\create_runtime_examples.py --output-dir output\runtime_demo_new
```

该脚本只写文件、配置 `VCC=5V/GND=0V`、核网和导出 SVG，不启动软件。生成后用 Proteus 打开对应工程并点击运行。输出目录必须是新目录，避免改动已有结果。示例中的 `K1 RELAY 5V` 的值是模型需要的额定电压；写成 `RELAY` 会使其内部开关阈值解析失败。

模型参数显示和标号整理也可单独调用，不需要改变元件或导线：

```python
c = Circuit.open("input.pdsprj")
c.set_property_visibility("U1", PROGRAM=False, CLOCK=False)
c.tidy_labels(max_shift_mm=20.32)  # 在 batch 结束后执行
c.save("output/polished.pdsprj")
```

`set_property_visibility` 使用 Proteus 原生的属性显示语法，值和模型参数仍保留；设为 `True` 恢复显示。`tidy_labels` 在限定距离内避让符号、引脚、已有文字和真实导线，成对移动标号和值，保留元件、导线和网络。未找到位置的标号记录到 `c.label_report['unresolved']`，外观不足不会静默修改电路拓扑。

## 安装平台技能

在工具目录运行；安装脚本复制整个技能及 `references/`：

```powershell
python scripts/install_codex_skill.py
# 只有明确更新已有安装时才覆盖：
python scripts/install_codex_skill.py --update

# DSH 使用相同技能、引用文件及可恢复安装流程。
python scripts/install_dsh_skill.py --update
```

目标为 `CODEX_HOME/skills/proteus86-files`（未指定 `CODEX_HOME` 时用当前用户的 `.codex`）。更新前核对旧树并在 `CODEX_HOME/skill-backups/` 创建完整可恢复备份，备份不放入技能自动扫描目录。源文件在复制中变化、目标并发变化或中断时拒绝半安装；保留用户无关配置，恢复被系统锁阻止时保留原树和备份并报告路径。强制结束 Python 或断电无法执行回滚。

安装后的 `.proteus86-install.json` 含本机 `checkout_root`，用于定位工具，不应进入源码发行。技能目录不包含 Python 运行库。Codex 与 dsh 安装时各自加入短平台入口，公共引用文件相同；除此之外的 harness 仍需自行适配和验证。

## 器件清单与网络表

文本沿用参考项目的分节方式。元件可以不写坐标；连接使用本机器件库的真实引脚：

```text
[parts]
R1 RES 10k
R2 RES 10k

[terms]
VCC POWER
GND GROUND

[nets]
R1.1,R2.1,VCC
R1.2,R2.2,GND
```

`RES/R`、`CAP/C` 映射到 `RESISTOR`、`CAPACITOR`。值含空格时加引号。可选参数为 `at=25.4,0 deg=90 library=DEVICE`；**本工具 `at` 的单位是毫米**，Y 轴向上，旋转是 90 度的整数倍。指定坐标的元件默认固定，其他元件自动摆放。

终端支持 `GROUND/POWER/LABEL/INPUT/OUTPUT/BIDIR`。网络每行至少两个条目，可以使用物理编号 `U1.1` 或完整逻辑名 `U1.P1.0/T2`。同名电源和标签按同网处理。

`generate` 一步生成。自动布局的拥挤电路会最多尝试三档间距（默认 12.7、15.24、19.05 mm），保留原网络；固定坐标不参与移动。完全自动布局会按实际导线范围居中并按需扩大画布；Python `from_design(..., fit=False)` 或 JSON `layout.fit_sheet=false` 可关闭。也可分步操作保存文件：

```powershell
python -m proteus86 autoplace proteus86\examples\parallel.txt -o output\parallel_layout.txt
python -m proteus86 place output\parallel_layout.txt -o output\parallel_placed.pdsprj
python -m proteus86 route output\parallel_placed.pdsprj -o output\parallel_routed.pdsprj --net 'R1.1,R2.1,VCC' --net 'R1.2,R2.2,GND'
python -m proteus86 netcheck output\parallel_routed.pdsprj --design proteus86\examples\parallel.txt
```

`place` 保存元件和终端，等待部件间布线。`route` 读保存文件，保留元件位置，并另存结果；`--net` 可重复。默认追加连接；`--replace` 清除原有显式元件连线后建立新连接，终端仍保留。源与目标相同时需明确加 `--overwrite`。

## Python 接口

从清单生成，再对保存文件布线和编辑：

```python
from pathlib import Path
from proteus86 import Circuit, from_design, parse_design, route_file

text = Path("proteus86/examples/parallel.txt").read_text(encoding="utf-8")
placed = from_design(text, route=False)
placed.save("output/py_placed.pdsprj")
route_file("output/py_placed.pdsprj", "output/py_routed.pdsprj",
           parse_design(text)["nets"])

c = Circuit.open("output/py_routed.pdsprj")
c.update("R1", value="22k")
c.move_mm("R2", 38.1, 0)
c.autoroute(clearance_mm=1.27, lead_mm=2.54)
c.save("output/py_edited.pdsprj")
```

直接调用元件与布线 API：

```python
from proteus86 import Circuit

c = Circuit()
with c.batch():
    c.add_mm("RESISTOR", "R1", "10k", 0, 0)
    c.add_mm("CAPACITOR", "C1", "100n", 25.4, 0)
    c.connect_net("R1.2", "C1.2")
    c.add_terminal("ground", "", "C1.1")
    c.label_wire("R1.2", "C1.2", "SENSE")
    c.arrange_labels()
c.save("output/py_rc.pdsprj")
```

`batch()` 在整组编辑完成后统一校验和计算路径，失败回滚。常用接口：

| 接口 | 用途 |
|---|---|
| `add_mm` / `move_mm` | 毫米坐标摆件/移动；`add` / `move` 是原生整数坐标，100000 = 1 mm |
| `pins(ref)` | 引脚名、物理编号、坐标、出线方向 |
| `connect(first, second)` / `connect_net(*pins, name=None)` | 两引脚或多引脚网络，写入真实原生导线及结点 |
| `connect_bus("U1", "U2", pairs)` | 按引脚名/编号的二元组列表批量逐对连接 |
| `autoplace(nets=None, gap_mm=12.7, fixed=())` | 按网络与引脚几何摆件，保留指定元件 |
| `autoroute(clearance_mm=1.27, lead_mm=2.54, obstacles_mm=())` | 正交避障；额外障碍为 `(left,bottom,right,top)` 毫米矩形 |
| `set_route(first, second, points)` | 手工原生整数折线；首尾按参数顺序与真实引脚重合，保存时自动兼容原生端点顺序 |
| `label_wire(first, second, name)` | 真正的 WIRE LABEL，支持保存后编辑和重排保留 |
| `arrange_labels(gap_mm=2.54)` | 按引脚方向将标号、值文字放到符号上方或侧方 |
| `arrange_terminals(reposition=False)` | 新终端避让符号、标签和引脚出线；`True` 时也调整已有终端 |
| `terminal_label_position(id)` / `set_terminal_label_position(id, position)` | 读取/设置端子文字的绝对原生整数锚点（100000/mm）；`None` 恢复当前默认锚，保留字体/样式与连接身份 |
| `translate_mm(dx, dy)` | 整图平移，同时移动元件、导线、结点和标签，保持相对几何及网络 |
| `fit_sheet(margin_mm=5.08, footer_mm=17.78, center=True)` | 批量编辑结束后按实际几何扩大画布并居中；`center=False` 保留坐标 |
| `tidy_labels(max_shift_mm=20.32)` | 在现有导线和符号之间寻找文字位置；最大允许 50.8 mm，返回 `label_report` |
| `set_property_visibility(ref, PROGRAM=False, CLOCK=False)` | 只改变原生模型参数是否显示，保留数值；未知参数拒绝处理 |
| `update` / `rename` / `copy_component` / `delete_component` | 修改、改名、复制、删除元件 |
| `disconnect` / `add_terminal` / `update_terminal` | 编辑连接和终端 |
| `set_properties(ref, **properties)` | 写属性，例如 `CLOCK="12MHz"`、`PROGRAM=...` |
| `bind_firmware(ref, path, visible=None)` | 校验中文/空格固件路径，保存时复制为英文相对资源 |
| `arrange_modules(modules)` | 按指定分区、行列和间距对齐阵列；保留网络，记录 `module_report` |
| `configure_power({"VCC": 5, "GND": 0})` | 配置原生电源轨电压 |

旋转、镜像参数为 `rotation`、`mirror_x`、`mirror_y`。自动重布线重算文件中读回的路径，保留标签；本次显式指定的手工路径保留。失败时应调整位置/间距或指定路径，工具不会静默删网。

## 中文路径、资源绑定与打包

高层接口处理资源路径，底层 ASCII 编码保护保留：

```python
from proteus86 import Circuit, package_project
c = Circuit()
with c.batch():
    c.add_mm('AT89C52', 'U1', 'AT89C52', 0, 0)
    c.set_property_visibility('U1', PROGRAM=False)  # 可以先隐藏尚未绑定的固件槽
    c.set_properties('U1', PROGRAM=r'D:\工程 文件\中文固件\流水 灯.hex')
    # 也可使用 c.bind_firmware('U1', path, visible=False) 立即检查路径和固件格式
c.save('output/中文 工程/电路图.pdsprj')
print(c.resource_report)
package_project('output/中文 工程/电路图.pdsprj', 'output/portable_new')
```

已存在的 PROGRAM 文件路径、绝对路径、中文/空格路径会绑定到 `resources/firmware/REF-SHA256.ext`。绑定记录输入哈希，保存前检查输入未改变，复制后再次检查源文件和副本；相同资源复用，内容冲突拒绝覆盖。绑定后重新编译了固件时，应再次绑定。保存失败保留原工程，已复制的资源是不可变文件，可以被其他工程共享。

保存后的 PROGRAM 只有英文相对路径。**搬移整个工程目录，包括旁边的 resources 文件夹**，固件引用仍然有效；只搬 `.pdsprj` 不包含外置固件。`Circuit.open(...).save(另一个目录)` 也会带上可解析的固件。普通 `save` 仍允许未找到的英文相对 PROGRAM 作为待绑定占位；交付前用 `bind_firmware` 或严格打包检查，不能把占位当成已加载固件。

新电路 Python 的相对属性路径默认按当前目录解析；已打开电路按源工程目录解析。`from_spec(..., resource_base=...)` / `from_design(..., resource_base=...)` 可指定设计目录。CLI JSON `build` 按 JSON 文件所在目录解析；JSON 元件允许 `properties` 与 `property_visibility` 同时设置。显式 `bind_firmware` 路径按当前目录解析。

```powershell
python -m proteus86 bind-firmware input.pdsprj -o output\bound_new.pdsprj --firmware 'U1=D:\工程 文件\中文固件\灯.hex'
python -m proteus86 package input.pdsprj -o output\package_new --firmware 'U1=D:\工程 文件\中文固件\灯.hex'
```

`package` / `package_project` 与 `prepare-run` 共用校验和复制实现，不启动 Proteus。它们要求新目录，输出 `circuit.pdsprj`、`firmware/` 和 `bundle.json`；清单包含 `project_relative`、资源相对路径及 SHA-256，绝对输入路径只作来源记录。目前自动收集范围为外置 PROGRAM 固件，不包括任意 SPICE 模型、图片或嵌入式构建资源。对带嵌入构建的已加载工程，固件绑定会明确拒绝，避免构建配置覆盖外置固件后误称可移植。

`PropertyError` 提供 `ref`、`property`、`reason`、`hint`，错误文字例如 `U1.CLOCK: 值包含非 ASCII… 修复方法…`。只有器件已声明的 PROGRAM 槽允许延后应用显示设置；`PROGARM` 等拼写错误仍立即拒绝，电阻不能绑定 MCU 固件。设置非文件属性仍要求 ASCII；不会通过删除编码校验接受未知格式。

## 模块与阵列排版

已有自动布局保留。需要指定 LED/电阻阵列及晶振、复位、输入、输出分区时，用明确的模块网格：

```python
with c.batch():
    c.arrange_modules({
        'outputs': {'rows': [['R1', 'D1'], ['R2', 'D2']],
                    'origin_mm': [-70, 25], 'pitch_mm': [-20.32, 15.24]},
        'clock': {'rows': [['CX1', 'X1', 'CX2']],
                  'origin_mm': [-40, 80], 'pitch_mm': [20.32, 15.24]},
    })
c.tidy_labels()
c.fit_sheet()
c.save('output/layout_new.pdsprj')
```

位置和间距总是毫米，行向下排列，X 间距可以为负数。只移动列出的元件，不改元件型号、值、旋转或网络；按已有规则重新连接导线并整理终端。重复/未知编号在移动前拒绝；批量失败回滚。JSON 的 `layout.modules` 使用相同结构。`module_report` 中估计的符号重叠只是警告，布线无法通过时需扩大间距。该功能提供明确分区和阵列对齐，不保证全局最少交叉或最短线；保存后仍应核网、检查几何并查看预览。

25 元件示例的排版可直接复用（输出目录须不存在）：

```powershell
python examples\draw_8051_neat.py --output-dir output\neat_8051_new
```

脚本生成独立的 `before.pdsprj`、`after.pdsprj`、资源、SVG 和文件检查记录，不启动软件。`--source PATH` 可整理相同编号/型号的原始 25 元件示例；其他电路应使用模块接口或自己的排版规则，脚本会在修改前拒绝不匹配的器件集合。方向根据真实引脚出口选择，新生成与已读取的模板均可处理；重复应用排版不会漂移。

0.8.2 明确排版示例零叠线、零非结点交叉，33/44 条导线为直线，总折弯 23 个。其原生网表、属性以及保存/重读的几何一致；历史原生显示截图（本机生成记录，不随源码分发）与工程副本（本机生成记录，不随源码分发）可查看。为拉开间距，总线长由上一版 997.0 增至 1344.98 mm；优先清晰，未声称最短线。移动工程时保留整个目录及资源，新布局仍需自己的检查。

任意受支持的已保存工程可单独检查线距，无需启动 Proteus：

```powershell
python -m proteus86 wire-quality input.pdsprj --min-gap 2.54 --min-parallel 2.54
```

Python：`from proteus86 import wire_quality; report = wire_quality(path, min_gap_mm=2.54, min_parallel_mm=2.54)`。仅把同时引用同一真实结点、且确实在结点结束的导线视为正常连接；无结点的十字、T 形和端点接触会报告。默认检查投影重合至少 2.54 mm 的并行区段，恰好达到间距可通过；示例回归还将最短区段降至 1 个原生单位核查短回折线。返回具体导线索引、交点坐标、间距及直线/折弯数，不移动线路。`passed` 只表示该绘图规则通过；它不检查所有斜对角接近、完整原生字体/控件边界，不代表电气或仿真通过，也不会绕过不支持对象的保护。

## Python 原生仿真

仿真必须启动真实 Proteus，普通文件画图仍不启动进程。使用本机已验证的 32 位 8.6 SP2 配置；状态适配器校验 `WINCORE.DLL` 指纹和控件所属 PID，其他版本明确拒绝。不会接管或关闭已有的 Proteus 窗口。

一次定时仿真：

```powershell
python -m proteus86 simulate output\runtime_v04\controller_complex_run86.pdsprj -o output\controller_run_new --seconds 1
```

也可以指定外置固件，或只准备仿真包而不启动软件：

```powershell
python -m proteus86 firmware-info examples\blink8051.hex
python -m proteus86 prepare-run input.pdsprj -o output\prepared_new --firmware U1=examples\blink8051.hex
python -m proteus86 simulate input.pdsprj -o output\run_new --firmware U1=examples\blink8051.hex --seconds 0.25 --timeout 30
```

输出目录必须是新目录。工具复制源工程和所需固件，写入可搬移的 ASCII 相对固件名；原工程和原固件保留。原工程已有 `PROGRAM` 相对路径按原工程目录解析，显式固件覆盖路径按当前工作目录解析。HEX 检查记录、校验和、EOF、扩展地址和重叠；ELF 检查头部及机器类型，BIN/COF/COFF 仅进行基本文件检查。这些检查不代替固件与 MCU 型号的兼容性判断。嵌入式 VSM Studio 构建暂不支持，工具不会执行工程中的构建脚本。

Python 控制流程：

```python
from proteus86 import Simulation, simulate

with Simulation.open("input.pdsprj", "output/run_new",
                     firmware={"U1": "examples/blink8051.hex"}) as sim:
    sim.start()
    print(sim.status())
    sim.pause()
    sim.start()                         # 从暂停恢复
    result = sim.run_for(1.0)            # 仿真时间，不是 sleep(1)
    print(result["simulation_seconds"])
    print(sim.diagnostics())             # 原生条目、错误、警告
    print(sim.log())                     # 不占用剪贴板
    sim.load_firmware("U1", "examples/blink8051.hex")  # 停止、复制、校验、导入、保存独立副本
    sim.run_for(0.25)
    sim.stop()

report = simulate("input.pdsprj", "output/another_run_new", duration=1.0)
assert report["passed"]
```

`Simulation(session)` 也能封装调用者新建的 `Session`。重新加载固件只允许 `Simulation.open()` 创建的独立包；成功后会留下独立固件、原生保存备份和 `firmware-history.jsonl`。`reset()` 停止当前仿真，下次启动重新初始化易失状态，保留器件持久数据。

`run_for` 用原生定时断点，读取引擎自己的计时来确认完成。持续时间至少 1 微秒，按整数微秒指定。默认接受 3 毫秒的原生计时量化误差；旧引擎可能在达到目标时留下微小定时余量，此时暂停并再次核实实际时间，结果的 `completion` 会标记 `target_reached_pause`。时间超出容限、状态不符或超时不会被报告成成功。

0.6 记录 `time_resolution_seconds`、`timing_error_seconds` 和 `tolerance_seconds`。原生显示在超过 1 秒后可能只有微秒精度，判断同时考虑半个显示量化单位，避免把小于显示精度的差异误当成未完成。`Session.save()` 等待两个相同、完整且 CRC 正确的 ZIP 快照，再允许调用者立即重读；修改时间和菜单可用性不再单独作为保存完成证据。

`Session.menu(path, timeout=15)` 对唯一匹配但仍禁用的菜单做有界就绪等待；每轮重新核对自有进程、主窗口和完整菜单路径，派发前再次读取当前命令。缺失/歧义路径、PID 或主窗口身份变化立即拒绝，不缓存命令 ID，也不把等待扩展为任意错误重试。本轮 32/48 元件各自通过原生保存与另一独立进程重开/SDF，修复前菜单尚禁用的失败记录保留。

`simulate` 总是尝试关闭自己创建的进程，输出 `bundle.json`（初始输入）、`result.json`（完成状态/实际时间/错误/源文件校验）和可用时的 `simulation.log`。`passed` 同时要求实际计时完成且原生日志未发现错误；诊断按消息文字分类，原生图像编号只作为原始数据保留，警告单独列出。原生失败返回 `passed=false`，CLI 退出码为 1；固件/输入预检失败在进程启动前拒绝，CLI 退出码为 2。

当前未加入任意引脚电压、波形、任意模型变量采集或 PCB 仿真；成功运行和无错误日志不等于完整电气正确性验证。原生日志读取使用标准 [ListView 消息](https://learn.microsoft.com/en-us/windows/win32/controls/lvm-getitemtext) 和有界的跨进程缓冲区；发送遵循 [Windows 消息的封送规则](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw)，不通过剪贴板取日志。

原生日志现在按已验证的自有控件层级识别：VSM Debugger 内的 Log Window，以及独立 Simulation Log 窗口。后者是 Proteus 自有窗口类，不是标准 Windows 对话框。日志定位核对真实父/所有者链、PID、控件签名与唯一性；身份或层级不明确时拒绝选取任意列表。三个原生失败副本已实际读出 SPICE 初始化失败；正常独立 Simulation Log 窗口修正后也已在本轮成功路径中，通过严格自有链读取日志。SDF 拓扑正确不能替代 `diagnostics()`、实际计时和功能断言。排错细节见 [原生参考](../skills/proteus86-files/references/native.md)。

## 运行截图

在工具源码目录，为运行工具的同一个 Python 环境安装可选截图依赖：

```powershell
python -m pip install -e ".[capture]"
# 已使用源码运行时，也可只安装或升级图像依赖：
python -m pip install --upgrade "Pillow>=11.2.1"
```

Windows 单窗口 `ImageGrab.grab(window=HWND)` 从 [Pillow 11.2.1](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html#PIL.ImageGrab.grab) 开始提供。工具在移动/调整窗口前检查该明确参数，缺失或旧接口会给出安装建议；常规文件 API 不导入 Pillow。

```python
with Simulation.open('input.pdsprj', 'output/capture_run_new') as sim:
    sim.run_for(.2)  # 初始化时间按固件选择
    image = sim.capture('output/images/running-new.png', advance_seconds=.01)
    assert image['passed']
    assert image['paused_after_capture']['state'] == 'paused'
```

`capture(destination, *, advance_seconds=.01, animation_seconds=10000, timeout=20, fit=True, width=1600, height=1000, foreground=True)` 只恢复、适配、激活并捕获自己创建的窗口，写新 PNG 及相邻 `.png.json`。它重新设定原生定时运行目标，要求截图前后实际时钟分别推进，最后暂停，并检查原生日志。`start()` 后显示 ANIMATING 不能替代这些检查。

WTS 检出锁定/断开的桌面会在截图前拒绝。捕获图中必须识别真实主画布，且其内部不是单色；工具栏、边框或缩略图有内容不能替代电路画面。非空画布也不证明数码管显示正确。失败会保留未通过报告、尽力暂停并继续抛出异常。0.9.1 公开 CLI 的真实运行截图已通过：图前 0.372412 秒、图后 0.422412 秒、最终暂停 0.472412 秒；主画布非空、日志零错误/警告，自有进程正常关闭。0.9.0 及较早受控预览保留各自原始时间记录。目视可见初始 `01234567`；这不替代全键、消抖或长按数字断言。先前锁屏拒绝保留为有效失败负例，旧白画布报告的 passed 不作截图证据。截图只保留本地验证，不加入公开源码。详见 [原生保存与截图流程](../skills/proteus86-files/references/native.md)。

## 原生输入与动态场景

0.6 已验证 **BUTTON、LOGICSTATE** 二态输入。生成时调用 `c.bind_controls('B1', ...)`，保存并重新打开；原生键槽 0–9 每个控件占两个，最多五个控件，并检查和其他器件 KEY/INC/DEC 的冲突。仿真中 `press` / `release` / `set_switch` 定向发送给自己 PID 的命令，导出真实 SDF 回读 STATE，不移动鼠标或发送全局键盘输入。重复设置同一状态不再触发命令。绑定在打开后改变时拒绝操作，需保存并重新打开。

`control_state('B1')` 是按钮位置，不是下游电压。输出观测需在生成时添加并接好 **LOGICPROBE**，然后 `sim.observe(['P0', ...])`。工具暂停、用原生 SDF 导出器读取探针 STATE、确认前后引擎计时一致，再恢复此前运行状态。只接受明确的 0/1，未知或非二态值不当作有效测量。LED 逻辑可按其已知接法由探针推断，例如本例阳极接 VCC 的 LED 为低有效；探针不测 LED 光强或电流。

以下例子可使用随验收保存的 30 元件电路（本机生成记录，不随源码分发），含 B1、P0–P7 和独立计数固件：

```python
from proteus86 import Simulation, Scenario
scene = (Scenario()
         .bounce('B1', at=.04, intervals=[.01]*4)          # 按下后抖动，最后稳定按下
         .bounce('B1', at=.22, intervals=[.01]*4, state=0) # 释放抖动，最后稳定释放
         .hold('B1', at=.36, seconds=.36))                 # 长按后释放
with Simulation.open('input.pdsprj', 'output/scenario_new') as sim:
    sim.run_for(.05)  # 初始化；预热时间按实际固件/复位电路调整
    result = sim.run_scenario(scene, probes=['P'+str(i) for i in range(8)],
                             until=.8, sample_every=.01, max_timing_error=.003,
                             expected_words=['11111111', '01111111', '10111111'],
                             expected_changes={'P0': 2, 'P1': {'falling': 1}})
    assert result['passed'], result
```

也可分别调用 `scene.press(ref, at=...)`、`scene.release(...)` 或 `scene.set(ref, 0/1, at=...)`。`bounce` 每个间隔后翻转状态，要求偶数个间隔以最终稳定在指定状态。所有时刻相对报告中的 `base_seconds`，动作记录请求时刻、实际原生时刻和回读状态；输出采样给出完整 LED 位字、压缩序列和观察到的上升/下降/变化次数。每次调用保存新的 `scenario-*.json`，标记 `backend=proteus_native_sdf`、`native_run_completed`、原生日志诊断和 `offline_isa_executor_used=false`。

0.8 可以在同一暂停时刻批量设置输入并读取探针：`io = sim.interact(controls={'K0': 1, 'K1': 1}, probes=['Q0','Q1'])`，返回 `actions`、`observation`、`simulation_seconds` 和 `native_exports`。器件必须预先绑定，所有输入、键位冲突和探针类型均先校验；有变化时用一个最终快照核对全部输入并读取输出，无变化时只取一个快照。仍逐项检查 STATE、所属 PID、绑定和原生时间，旧的 `press/release/observe` 接口保持可用。命令在暂停时依次发送，不是原子硬件写入；电路传播可能需要随后 `run_for(...)`，回读结果只是当时的原生状态。同一 Simulation 应串行使用。 0.9.1 的 Session 构造及 Simulation.open() 在原生启动后遇到 BaseException 时，清理各自确切的 Popen 并重抛原异常；分组报告保留启动 PID/关闭状态。检查点写盘失败不能吞掉已在传播的 KeyboardInterrupt/SystemExit，失败/中断记录不会改成通过。

长场景可以显示进度并提前取消：

```python
def progress(info):
    print(info['frames_completed'], '/', info['frames_total'],
          'native time:', info['simulation_seconds'], flush=True)
    # 返回 False 可取消；返回 None 则继续。

with Simulation.open('input.pdsprj', 'output/scenario_new') as sim:
    sim.run_for(.05)
    result = sim.run_scenario(scene, probes=['P'+str(i) for i in range(8)],
                             until=.8, sample_every=.01, progress=progress,
                             checkpoint_every=25)
    assert result['passed'] and result['native_run_completed'], result
```

在第一帧、输入动作帧及每 `checkpoint_every` 帧后，场景将完整 JSON 写到同目录临时文件并原子替换，避免读到半个 JSON。文件从运行开始就存在，`status` 为 `running/completed/failed/cancelled`，另有 `frames_completed/frames_total/native_sdf_exports/wall_seconds`；墙钟耗时仅描述进度，不能证明仿真完成。回调每完成一帧收到独立摘要；返回 `False` 时保存取消结果并保持暂停，调用方仍应通过上下文关闭自己的进程。回调异常、引擎退出或 `KeyboardInterrupt/SystemExit` 都会保存已收集证据，后两者继续向调用方抛出。未完成结果不会标成通过。硬终止整个 Python 进程时，只保证最近一次完整检查点，可能遗漏之后尚未落盘的采样。原生导出窗口仍可能短暂出现。

**这些次数仅覆盖采样点观察到的变化**，采样间短脉冲可能遗漏，原生显示/步进刷新也限制分辨率。默认允许 3 ms 时间误差，必须小于最短时间间隔的一半；更短的抖动需更严格容差，若引擎达不到即失败，不能声称验证通过。`evaluate_samples(...)` 只分析给定样本，是离线断言；手工样本或 HEX 指令级执行器的结果不能标成原生结果。0.6 的独立计数固件和 0.7 的两套课程固件分别保留原生证据，不能互相替代；新的课程程序仍需接入对应输入、探针及期望序列验收。其他交互器件、任意电压/连续波形、完整事件捕获仍未支持。

## 矩阵键盘与数码管示例

独立示例生成 32 元件工程；`--probes` 添加 16 个观测探针。固件可用本项目自有的受限 8051 汇编器从源文件重建，无需 Keil：

```powershell
python examples/build_matrix_firmware.py --output-dir output/matrix_firmware_new --check-against examples/matrix_display.hex
python examples/draw_matrix_display.py --output-dir output/matrix_display_new --firmware output/matrix_firmware_new/matrix_display.hex --probes
```

构建清单记录源文件、汇编器与 HEX 哈希、地址和机器码；比较检查实际地址/字节，而非 HEX 文本换行。此汇编器只支持该示例需要的严格子集，不是通用 A51/Keil 替代。构建可复现不等于执行过固件。见 [构建及限制](../examples/matrix_firmware_build.md)和[完整使用流程](../skills/proteus86-files/references/matrix-example.md)。

`prepare_control_batches()` 为每组最多五个输入创建独立副本；`run_control_batches()` 逐组创建自有仿真进程并执行调用者的 `callback(sim, ref)`。16 键可以分组覆盖，不能宣称一次原生绑定 16 键。`read_display_frame()` 根据指定的段/位探针、顺序和有效电平，要求至少两轮完整扫描结果一致；报告保留实际采样时间窗口，它不是八位同时测量。`decode_seven_segment()` 仅做离线段码解码。返回示例、错误对照和限制见 [数字验证参考](../skills/proteus86-files/references/digital.md)。`observe()` 的时间字段是 `simulation_seconds`，不是场景记录中的 `actual_at`。

本例选用 AT89C51RD2 的 DIL40 定义，原生 `PP(VCC)=40` / `PP(GND)=20` 自动按全局电源名绑定，不再在这两脚重复挂显式端子。受控对比只移除这两个冗余端子、其余保持不变后，48 元件副本可推进 0.22 秒原生时间；这是起仿受控对比，完整数字动态另按下述最终场景验收。保留全部 29 个期望网络（含 40/20），逻辑连接检查依据选中 PACKAGE 的真实 PP 声明归并，`physical=True` 保持物理显式连接视图。不要为补文件检查而重新挂回冗余端子，也不要将这一实例外推成所有隐藏脚或 MCU 的规则。示例电容明确选用 `DEVICE/CAP` 模型；电容模型调整不是本轮已定位的 SPICE 根因。详见[文件与 PP 边界](../skills/proteus86-files/references/file-workflow.md)。

示例初始显示 `01234567`，接受按键后末两位分别为响应计数和键值，便于检查长按是否重复响应。仅看到相同键值稳定不变不足以证明单次响应。0.9.0 的 16 键原生结果保留为历史；新版布局及新公开验证脚本需要本轮独立结果。

公开复现入口（两次执行必须使用不同的新输出目录）：

```powershell
# 只构建固件、生成/核网并准备四组输入，不启动 Proteus：
python scripts/verify_matrix_display.py --output-dir artifacts/matrix-prepare-091-NEW
# 明确启动自有原生进程；此处用另一个输出和新的独立 ASCII 绝对 TEMP：
python scripts/verify_matrix_display.py --output-dir artifacts/matrix-native-091-NEW --execute-native --temp-dir D:/Proteus86Temp/matrix-091-NEW
```

第二条可加 `--capture`，需要解锁且连接的交互桌面和已检查的 Pillow 单窗口捕获能力；只激活自有窗口。TEMP 必须是尚不存在的绝对 ASCII 目录，与输出目录彼此独立、互不嵌套；默认文件准备把临时文件放在自身输出目录，不回退到系统 TEMP。文件模式 `passed=true/status=prepared/scope=file_contract_preparation_only` 只表示准备成功，`native_run_completed` 和 `simulation_executed` 仍为 false。

原生模式请求相同的独立固件合同：16 键按 5/5/5/1 顺序分组，目标 25 次非原子显示重建，每次至少两轮完整扫描一致；每键稳定按下 80 ms 再保持 120 ms 后检查显示及模 16 响应计数。K0 额外检查 3 ms 短脉冲、三轮 2/3 ms 抖动拒绝和释放重按。本轮真实 CLI 运行得到 25 次重建、658 个原生样本和 118 次输入状态回读，所有显示/响应计数及诊断断言通过，四个自有进程正常关闭、源文件未改。实际采样数以本次 `result.json` 为准；不同时操纵 16 键，不声明任意长按、实体硬件或连续波形正确。详见[矩阵示例流程](../skills/proteus86-files/references/matrix-example.md)。

## JSON、转换与检查工具

JSON 示例位于 `proteus86/examples/`。省略元件坐标即可自动摆件：

```json
{
  "units": "mm",
  "components": [
    {"device": "RESISTOR", "ref": "R1", "value": "10k"},
    {"device": "CAPACITOR", "ref": "C1", "value": "100n"}
  ],
  "nets": [["R1.2", "C1.2"]],
  "terminals": [{"kind": "ground", "name": "", "pin": "C1.1"}],
  "layout": {"auto": true, "gap": 12.7},
  "routing": {"clearance": 1.27, "lead": 2.54, "avoid_labels": true}
}
```

`connections` 接受 `[first,second]` 或 `{first,second,points}`；`nets` 也支持 `{ "pins": [...], "name": "SIGNAL" }`。元件 `label_offsets` 可指定相对文字位置。坐标遵循 `units`（`mm` 或 `native`）。

```powershell
python -m proteus86 check proteus86\examples\led.json
python -m proteus86 build proteus86\examples\led.json -o output\custom_led.pdsprj
python -m proteus86 search AT89C52
python -m proteus86 device CRYSTAL --library DEVICE
python -m proteus86 inspect output\my_parallel86.pdsprj --geometry
python -m proteus86 pincheck output\my_parallel86.pdsprj
python -m proteus86 fix-pins output\my_parallel86.pdsprj -o output\pins_checked.pdsprj
python -m proteus86 wiringcheck output\my_parallel86.pdsprj
python -m proteus86 fit-sheet input.pdsprj -o output\fitted86.pdsprj --keep-coordinates
python -m proteus86 tidy-labels input.pdsprj -o output\tidied86.pdsprj --max-shift 20.32
```

`check` 编译校验但不保存。`inspect --geometry` 读取实际导线、引脚和结点。`netcheck` 检测指定网络漏接和相互意外短接，不代替完整电气规则检查。`pincheck` 比较 CDB 引脚表与嵌入符号；`fix-pins` 只在名称集合一致时等长重排，其他 ZIP 成员保持原字节，不猜测缺失引脚。

`wiringcheck` 检查出界和导线共线重叠，并单独报告估计文字/符号遮挡。默认只有错误导致失败；`--strict` 才会将这些外观警告也作为失败。`from proteus86 import wiringcheck` 提供相同 Python 报告。按功能优先，先确认 `netcheck` 和原生兼容，再处理外观警告。`fit-sheet` 不加 `--keep-coordinates` 时整图居中。

Protel NETLIST 2.0 可先转换，器件字段必须对应本机库名：

```powershell
python -m proteus86 convert-net input.net -o output\converted.txt --device-field FOOTPRINT
python -m proteus86 generate output\converted.txt -o output\converted86.pdsprj
```

接受带 `DESIGNATOR/FOOTPRINT/PARTTYPE/VALUE/DESCRIPTION` 字段的 2.0 格式。`--device-field` 可选 `PARTTYPE/FOOTPRINT`；`--device-map map.json` 接受 `{ "旧名称": "实际器件名" }`。不自动猜测封装到仿真模型的对应。

## 验证

| 0.9.1 范围 | 当前结果与边界 |
|---|---|
| 完整回归 | `python -m unittest discover -s tests -v`：295 项全通过、0 跳过，120.379 s。最终本机证据见 `artifacts/validation_v091.json`；不代表 295 次原生仿真。 |
| 公开候选回归 | 独立运行同样 295 项，2 项可选私有 fixture 检查跳过，其余通过，0 失败/错误，120.654 s；与本机 0 跳过的完整结果分别报告。 |
| 公开 CLI 原生动态 | 实际通过 16 键 5/5/5/1 顺序分组、25 次显示重建、658 个原生 SDF 样本、118 次输入状态回读。显示/有限保持单次响应及 K0 短脉冲/抖动拒绝、释放重按通过；四个自有进程正常关闭、源文件不变。 |
| 原生运行截图 | 图前 0.372412 秒、图后 0.422412 秒、暂停 0.472412 秒，主画布非空，目视初始 `01234567`，诊断零错误/警告。图像本身不代替数字功能断言。 |
| 32/48 元件保存往返 | 每例用独立的保存与 fresh-reopen 进程，共四个自有进程正常关闭；29 个期望网络/39 个原生网络、完整引脚分组/属性、元件模型/位置/值、线/结点和端子文字锚点一致，源文件未改。 |
| 新布局文件几何 | 32 元件 102/104 条直线、48 元件 118/120 条直线，各 4 个折弯；默认及一个原生单位最短并行区段检查均无报告的叠线、非结点接触或过近并行。各保留 35 条保守文字警告。 |
| 端子文字接口 | 9 项专项回归通过，绝对 int32 坐标/默认锚、字体样式、ID 及事务行为受检查；新原生往返也确认文字锚点保留。 |
| 启动中断清理 | 11 项专项回归及两个真实 PDS 受控 KeyboardInterrupt 清理检查通过；仅清理本次 Popen、原中断重抛，记录仍 interrupted/unpassed。没有运行电路，不能计作仿真成功。 |
| 可选截图依赖 | `Pillow>=11.2.1` 与明确的 `ImageGrab.grab(window=...)` 能力校验；文件模式不导入 Pillow、不回退截取整个桌面。 |

本轮完整结果见 [0.9.1](release-0.9.1.md)及 `artifacts/validation_v091.json`。旧版说明、ZIP 与 `validation_v09.json` 保留不变，见[历史范围](../skills/proteus86-files/references/history.md)。历史课程换向/调速未重测，未知实体格式及 native PID/profile/时钟保护保留。公开候选验收与私有同步按各自实际执行记录报告。

文件生成的配对测量使用独立 Python 3.12.14 环境：同一当前核心、模板和显式固件，32/48 元件每种旧/新例程策略各三次、共 12 次交错生成，完整模型/网络/固件一致。结果为：

| 例程规模 | 旧布局策略中位数 | 新布局策略中位数 | 耗时下降 |
|---|---:|---:|---:|
| 32 元件 | 1.89940 s | 1.62266 s | 14.57% |
| 48 元件 | 2.28485 s | 1.95703 s | 14.35% |

计时覆盖例程 `generate()` 的布线、保存、重读、检查、预览和结果写入；独立的等价性比较在计时之外。它比较相同核心下的例程布局策略，不是版本间通用核心、任意电路或原生仿真的性能保证。证据为 `artifacts/skill-v091-followup-20261028-3c78b0/paired-generation-r3-20261028/result.json`。

文件性能可运行 `python scripts/benchmark_files.py --repeat 3`，生成到新 D 盘目录，包含核网和源文件保护。常规回归、文件基准不启动 Proteus。需要实际原生兼容/仿真时，按相关脚本的 `--help` 选择独立新输出并配置英文 D 盘 TEMP；游戏期间不运行，只关闭本次自有进程。截图和 SDF 对话框可能短暂显示。

私有课程资料、报告、交付物与恢复归档保存在工具目录之外；工具只保留源码、独立示例、测试与验证证据。历史迁移清单作为本机恢复资料保留，不加入公开源码或说明。

## 导入拒绝与转换流程

`python -m proteus86 diagnose input.pdsprj` 只读检查 ZIP、CDB 版本、保存版本及已知记录保护，输出分类、具体 guard、来源哈希和转换步骤；可读返回 0，不支持返回 1。`Circuit.open()` 的格式异常也附带 `.diagnostic`。部分实体/组件证据只用于定位，不能作为完整解析或绕过保护的依据。

历史两份外部参考副本的实测结果见 诊断与原生另存记录（本机生成记录，不随源码分发）：

| 参考 | 具体原因 | 本机转换结果与下一步 |
|---|---|---|
| IO 开关量输入实验 | CDB v3，RELEASE 803 / FILEVER 805 | 在项目目录中的副本原生打开、导出 21 元件 SDF、另存为 CDB v5 / 806 / 814；仍含匿名按钮和 U1 非 ASCII 属性块，未完整可读 |
| IO 驱动实验 | CDB v5，RELEASE 811 / FILEVER 828；另有匿名实体与 U1 非 ASCII 属性块 | 本机原生提示必须 Proteus 8.11 或更高，拒绝打开。不能靠改版本号降级 |

`Unknown CDB component table` 在这些文件中不能直接解释成“文件损坏”：现有解析器拒绝 U1 的非 ASCII 属性块后，剩余记录不足以验证完整组件表；同时存在匿名实体。诊断现在指出 U1、`Non-ASCII component properties`、匿名实体和保存版本，分别归类为编码、结构和版本问题。

可行流程是先复制工程。在可打开它的 Proteus 中为匿名按钮分配唯一编号、检查 U1 的 PROGRAM 等路径，复制外置固件并绑定英文相对路径，然后原生另存并重新 `diagnose`。嵌入式 VSM Studio 的构建配置需在原生副本中明确处理为外置固件，工具不执行它。若仍有不支持对象，则原生导出逻辑 SDF，明确提供器件/编号映射（例如 `BUTTON#005B`→`B1`），用本机已支持器件重建新图，再比较原生网表；重建不承诺保留原排版/注释。8.11 工程的导出步骤需要 8.11 或更高版本。没有猜测未知结构、删除原对象字节或修改原始资料。

`python scripts/diagnose_references.py` 复现只读诊断；明确加 `--native` 才在本项目 `artifacts/` 创建副本并原生另存。它不运行参考工程固件或构建脚本，不写原始资料目录。

## 兼容与安装

本机 8.6 自己保存的格式是 **RELEASE=806 / FILEVER=814 / CDB v5**。工具按结构识别，不能保证所有名为 8.6 的文件都兼容。

- 支持已验证结构的单用户页、单单元器件工程。复杂多页、多单元、未知图形/图表对象会拒绝重写。旧 CDB 文件需先在原生兼容版本中保存为当前结构并重新诊断；另存不保证消除未知对象。
- 其他库器件可能含未支持结构。重名器件需指定库，例如 `1N4007 library=DIODE`、`CRYSTAL library=DEVICE`。
- 布线采用压缩网格正交 A*、估计的元件包围框/文字框，保留出线方向，避免共线重叠，支持多引脚结点。有搜索上限，不能保证任意复杂电路都自动布通；完整图形轮廓、精确字体、电气规则尚未建模。
- SVG 是几何预览（元件框、引脚、真实导线、结点、文字），不复刻 Proteus 完整符号。
- 扩大画布后的默认标题框可能不显示，符号和字体的碰撞检测仍是估计。文字整理、参数隐藏已通过文件/原生数据和 0.5 仿真检查，窗口外观需按具体工程原生复核；本轮独立矩阵示例的运行画面已单独检查。
- 原生字段仍要求可打印 ASCII；高层 PROGRAM 绑定和工程保存路径支持中文/空格，并通过资源复制保持相对引用。器件属性写入不代表固件、供电、仿真行为已验证。

本机已准备 `templates/base86.pdsprj`。安装自动从注册表/常见目录发现，或指定：

```powershell
python -m proteus86 --install 'D:\Program Files (x86)\Labcenter Electronics\Proteus 8 Professional' doctor
```

环境变量 `PROTEUS86_HOME` 指向安装，`PROTEUS86_TEMPLATE` 指向模板；CLI 支持命令前的 `--template`。换机器时，复制该机官方 `SAMPLES/Graph Based Simulation/Rescap.pdsprj` 到工作目录，在当地 Proteus 8.6 打开并保存副本，再指定为模板，工具会核对结构。

无需安装；可选 `python -m pip install -e .`。普通 wheel 安装需另行指定本机模板。Labcenter 样例、模板及派生工程包含其器件定义，适用原许可，排除在源码发行之外。工具不修改安装目录、原始样例及其他实验。

## 干净源码发行补充

两个旧独立固件现可用自有 Python 汇编器重建，全部程序地址/字节与随附 HEX 一致；两个上游已固定到逐文件核对的提交。新增构建与来源核对没有运行 Proteus，不改写原生验收、原固件或旧记录。此前已从审核源码建立无父初始提交的私有仓库；本次双平台版本沿用该仓库，原私有仓库仍保留。后续源码公开授权及未解决的许可风险见 [公开说明](publication.md)。详见 [本轮补充](clean-source-preparation.md)。
