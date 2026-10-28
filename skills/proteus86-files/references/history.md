# Historical acceptance and provenance

Consult this only for old versions/evidence. These scopes do not certify a changed runtime, new firmware, new machine or other AI harness.

| Version | Recorded scope |
|---|---|
| 0.9.0 | Historical independent run: 32/48-part native save/fresh reopen, unlocked timed capture, and 16 sequential matrix keys in 5/5/5/1 groups; 25 reconstructed displays/670 native samples, at least two agreeing full scans each. K0 short pulse/bounce/rearm and all-key finite hold checks passed. Root regressions were 234/0 skipped, public candidate 234 including 2 optional private-fixture skips. Details are in the unchanged 0.9.0 release/native/digital history; historical course direction/speed was not rerun. |
| 0.8.3 | 119 file regressions, interruption rollback and 600 complete quality-report comparisons. Successful 25/42-component ROOT.CDB/ROOT.DSN matched prior output byte-for-byte. No native rerun in that revision. |
| 0.8.2 | 112 file regressions; explicit 25-component spacing/straightness with native save/reopen/netlist/geometry checks. No new dynamic simulation. |
| 0.8.1 | 105 file regressions; endpoint-order/layout native acceptance and independent counter/probe scenes. |
| 0.8.0 | 100 file regressions; shared native I/O, checkpoints/failure reporting and limited independent/external-firmware native scenes. |
| 0.7 | File-speed/router comparison, native editor save/reopen/netlists and separate external-firmware dynamic evidence. |
| 0.6 | Earlier import/resource/visibility/layout/digital-control acceptance. |

The current 0.9.1 scope is in `docs/release-0.9.1.md`; unchanged `docs/release-0.9.0.md` retains its own scope in the checkout; a separately prepared public source tree may include sanitized validation summaries. Local complete historical evidence may be in `artifacts/validation_v083.json`, `validation_v082.json`, `validation_v081.json`, `validation_v08.json`, `validation_v07.json`, `validation_v07_dynamic.json`, `validation_v07_file.json` and `validation_v06.json`. Raw runs, proprietary templates, course inputs and personal path inventories are not distributed.

The 0.8.2 explicit profile used 10.16 mm LED rows and 7.62 mm vertical lanes, retaining fixed 2.54 mm MCU pin pitch. It recorded 33/44 straight wires and 23 bends with zero reported overlap/non-node-contact/near-parallel issues at its thresholds. Those are that example's metrics, not a guarantee for new diagrams.

Preserve upstream MIT attribution in `proteus86/_codec/LICENSE` and `THIRD_PARTY.md`. Format extensions require actual observed native evidence and bounded codec checks. That MIT license does not license redistribution of Proteus binaries, models/sample definitions or private artifacts.

## Retained historical detail

The following entries were previously in the main README. They remain version-scoped history, not fresh 0.9.1 acceptance. Raw local evidence and its original hashes are preserved without publishing private inputs or path inventories.

| 验证 | 结果 |
|---|---|
| 0.8.2 的回归测试 | 112 项通过：保留路径/资源、导入诊断、性能边界、原生接口离线回归及场景异常记录；新增 7 项线距诊断检查，覆盖真实结点引用、叠线、交叉/T 接触、间距阈值、短区段、冗余点与只读 CLI。排版回归检查最短区段、接地/电源直连与重复应用。单元测试本身不启动仿真 |
| 0.8.2 间距与拉直 | 25 元件示例零叠线、零非结点交叉、零阈值以下并行区段，33/44 条直线、23 个折弯；LED 行距 10.16 mm，竖向输出通道 7.62 mm。原生保存、Python 重读、再次原生打开后几何/网表/属性一致。未重跑动态场景 |
| 0.8.1 原生编辑器 | 排版前后 25 元件、10 元件正反向路径和 42 元件副本通过原生保存、Python 重读、再次独立打开；全已知非 PP 引脚分组、原生属性与几何一致；最终排版另行复核 |
| 0.8.1 独立原生动态 | 新生成 30 元件电路，81 次原生数字采样通过按键抖动、长按计数 0→1→2，原生保存后可重读；LOGICSTATE/探针为 0→1→0，两个自有进程均退出。未把历史课程换向调速结果改标为 0.8.1 重测 |
| 0.8 批量原生 I/O | 15 帧双输入场景与保存的 0.7 代码逐样本一致，SDF 导出 37→21（少 43.2%），本机单组墙钟 29.28→18.62 秒；只代表此负载，逐点纯采样仍需每帧新鲜导出 |
| 0.8 场景稳定性 | 逐帧进度和途中 JSON 可读；实际取消、回调报错、自有进程被关闭时，分别保留 3/1/3 个样本并明确失败/未完成。100 项离线回归通过；异常处理检查不计作成功仿真 |
| 0.8 原生功能 | 独立 30 元件计数 81 次采样保持 0→1→2，37 元件课程副本 133 次采样通过换向及 150→300→75→150 ms 调速；前后 SDF 全已知非 PP 引脚分组及原生保存/Python 重读一致，五个自有进程均退出 |
| 0.7 路由对照 | 固定种子 250 组障碍、保留线、引脚走廊和转弯代价案例，与优化前路由器的可达性及长度/转弯/交叉加权代价一致；属于离线路由检查 |
| 0.7 原生复核 | 25/编辑后25/42/37/30 元件共 5 个副本、10 个自有进程通过：原生 SDF、保存、Python 重读、再次独立原生打开及 SDF 全引脚分组/属性一致；全部源文件哈希不变，自有进程均关闭 |
| 0.7 布线与显示 | 5 例导线和结点几何、元件位置/数值/旋转保存前后一致；所有已知非 PP 引脚（含悬空引脚）与原生 SDF 分组一致，PP 隐式电源绑定单列记录。仍有局部文字拥挤/估算碰撞警告，未发现本轮连接或保存错误 |
| 0.7 课程原生动态 | 37 元件/12 MHz/P0 低有效与 30 元件/6 MHz/P1 缓冲高有效，共六场景、518 次原生采样、64 次输入回读通过：10 ms 短脉冲拒绝、按下/释放抖动、600 ms 长按只在释放时前进一步，换向及三次 500 ms 调速长按后周期 150→300→75→150 ms；原生前后网表和保存重读一致，六个自有进程均退出 |
| 0.6 独立 30 元件原生场景 | 输入探针高→低→高；81 次原生采样，抖动和长按的 8 位 LED 计数 0→1→2；SDF 网络一致，原生保存后 Python 可读，源文件不变且自有进程关闭 |
| 0.6 LOGICSTATE | 原生 LOGICPROBE 状态 0→1→0，诊断通过；不使用离线 HEX 执行器 |
| 0.6 参考工程副本 | 8.3 副本另存到 8.6 后仍有编码/匿名对象限制；8.11 副本被原生明确拒绝。原件哈希不变，自有进程均关闭 |
| 25 / 42 元件复杂电路 | 21 / 43 个预期逻辑网络通过；44 / 81 段原生导线、3 / 5 个结点，文件几何及引脚表通过 |
| 复杂原生往返 | 25 元件、编辑后的 25 元件、42 元件均通过真实 SDF 核网、Proteus 保存、Python 再读回；元件位置、值、旋转和网络保持，源文件保留 |
| 0.4 运行工程原生检查 | 两份整理文字、隐藏模型参数后的工程通过真实 SDF 和保存往返；原生网表的 PROGRAM/CLOCK 数值正确 |
| 0.5 实际原生仿真 | 25/42 元件启动、暂停、恢复、1 秒/0.25 秒定时运行及停止通过；原生日志确认加载 39 字节固件，无错误/警告；进程关闭且源文件不变 |
| 固件重新加载与反例 | 25 元件工程实际加载 2 字节循环固件，再恢复 39 字节；继电器故意写成 `RELAY` 的反例返回失败并捕获模型参数错误 |
| 无 MCU 的命令行仿真 | 电源/电阻/LED 电路实际运行 0.25 秒，原生计时与日志通过，输出结果与源文件保护通过 |
| 实际仿真 | 独立 39 字节 8051 固件成功加载；25 元件的 8 路 LED、42 元件的黄灯/驱动绿灯/继电器触点均观察到切换，修正后日志仅有正常信息 |
| 并联电阻、AT89C52 自动布局流程 | 摆件→保存→读文件布线→核网→SVG；源文件哈希和元件位置不变；真实 Proteus SDF 网表一致 |
| 8 电容两组总线 | 原生结点度数 2–4、文件读回、真实网表通过 |
| RC / LED / MCU / 障碍与线标签 | 原生进程验收通过；RC 另通过 ADI 改值保存读回 |
| 其他器件 | `1N4007`、`2N2222`、`RELAY`、`ULN2003A`、`ATMEGA328P`、`LOGICSTATE`、`SW-SPST`、`CRYSTAL` 原生读取与网表核对通过 |

Historical same-machine file benchmark medians (0.6 to 0.7):

| File workflow | 0.6 | 0.7 |
|---|---:|---:|
| 25-component generation/routing | 0.753 s | 0.549 s |
| 42-component generation/routing | 11.166 s | 4.622 s |
| 25-component generation/save/reopen/netcheck/SVG | 1.046 s | 0.847 s |
| 42-component generation/save/reopen/netcheck/SVG | 11.700 s | 5.109 s |

These timings exclude AI work, reports, native simulation and per-sample SDF cost. The 42-component case still required a spacing retry; machine/game load was not controlled. The 0.8 paired native I/O example exported 37 to 21 SDFs and took 29.28 to 18.62 seconds in that one comparison. The 0.8.3 quality-analysis comparison improved its analysis phase about 2.7 to 3.4 times, while the 25-part full diagnostic changed about 94.2 to 86.5 ms. None is a universal routing or simulation speed guarantee. Use a fresh benchmark for new changes.

## 0.9.1 evidence boundary

Current work adds a public opt-in matrix verifier, revised terminal/caption layout, a public absolute caption-anchor API, checked optional Pillow window capture and exact-owned-Popen startup interruption cleanup. The final root suite passed 295 tests with no skips in 120.379 seconds. The independent public candidate ran 295 tests with two optional private-fixture skips, otherwise passed, in 120.654 seconds. The public current CLI passed 16 sequential keys, 25 reconstructed displays, 658 SDF samples and 118 actuator readbacks; its owned capture and both 32/48-part save/fresh-independent-reopen paths also passed with full geometry/caption and topology preservation. The two real startup-interruption cleanup checks remain separate negative evidence and deliberately did not simulate. Final current totals are in `docs/validation/v0.9.1.json`; do not copy 0.9.0's 234 regression or 670 native-sample totals forward. The paired 12-generation example-strategy comparison under one current core/Python 3.12.14 showed 14.57%/14.35% lower medians for these 32/48-part examples, not general core/native acceleration. Previous ZIPs, release notes and raw evidence remain unchanged.
