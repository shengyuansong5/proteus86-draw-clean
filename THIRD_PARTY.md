# 第三方来源与许可

## Windows 便携包运行环境

便携 Release 附件另含 Python 官方 Windows x64 嵌入式运行环境，以及 PyPI 发布的 Pillow wheel；固定版本、来源和 SHA-256 见 `portable/dependencies.json`。Python 的完整原始许可位于包内 `runtime/LICENSE.txt`，Pillow 及其图像库许可保留在 `runtime/site-packages` 的对应 dist-info 许可目录。除隔离搜索路径配置外，不修改这些运行时二进制；它们不改授项目 MIT 许可。源码仓库不包含这些二进制，构建时从固定来源校验后打包。

## 功能参考

[RACErace/pdsprj-auto](https://github.com/RACErace/pdsprj-auto)（MIT）是清单、布局、布线、引脚检查、Protel 转换与预览流程的功能参考，未将其代码复制进运行时。本项目的坐标单位为毫米。

自动布局、A* 路由及搜索缓存、公开 API、文本/JSON/Protel 转换、几何检查、画布适配、文字避让、资源管理、诊断、模块网格与场景记录由本项目实现。

## 改编的 MIT 代码

编解码器和可选原生接口基于 [kudoumakoto6523-design/Proteus_automatic_package](https://github.com/kudoumakoto6523-design/Proteus_automatic_package) 0.2.0（2026-10-14 获取）。

- 原始 MIT 声明完整保存在 [proteus86/_codec/LICENSE](proteus86/_codec/LICENSE)。
- 原始模块 SHA-256 在 [upstream-sha256.json](proteus86/_codec/upstream-sha256.json)。
- 原始下载地址和 ZIP 摘要在 [docs/provenance](docs/provenance)。

发行准备已将来源固定到实际核对的提交：编解码器为 `7439819a7ea4cff47fb9b321d8b0e97ac74fafb2`，功能参考 pdsprj-auto 为 `d3a07201fcf9aa7929df0f5a421d0902f9dcce38`。原 main 归档摘要、固定提交归档、完整 Git blob 树和保留源码逐文件字节一致；MIT 原文也一致。固定地址与校验范围分别记录在 [codec-source.json](docs/provenance/codec-source.json) 和 [pdsprj-auto-source.json](docs/provenance/pdsprj-auto-source.json)。归档只用于本地来源核对，不随本项目分发，不将其第三方/厂商资产纳入本项目 MIT 许可。

采用并改编的模块为 `proteus_project`、`component_codec`、`device_library`、`pin_geometry`、`wire_codec`、`net_objects`、`net_edit`、`proteus_native`、`proteus_session`。调整包内导入、CDB v5 / FILEVER 814、实体/属性表、旧库语法、电源脚和逻辑引脚名，接入本地库发现、批量操作、路由缓存、保存保护、原生属性显示及 SDF 回读。

`native_simulation.py`、`simulation.py` 参考并适配该上游的 `api/simulation.py`；输入控制参考其 INC/DEC 键槽和定向命令方式，沿用 MIT 归属。本机 8.6 二进制指纹和计时格式经过重新验证；未移植 8.16 任意模型内存适配器。日志通过 Windows ListView 和独立 IPC 缓冲区读取，数字输入输出通过已验证的原生 SDF 检查。

## 本项目独立示例

`examples/blink8051.a51`、`examples/key_counter.a51` 及对应 HEX 是本项目独立验证固件，不来自课程交付。它们的源码及程序不包含外部链接库，适用根 MIT 许可；源码与 HEX 摘要见[独立示例清单](docs/provenance/independent-examples.json)。`examples/build_demo_firmware.py` 可从原 A51 重新编码全部 39/42 字节，与随附 HEX 的全部占用地址和字节一致；它只复用自有矩阵构建器的 HEX 编解码，不调用外部编译器、链接器或运行库。counter 的规范 LF 输出与原 CRLF 文本摘要不同，地址字节完全相同；原 HEX 保留不变。构建方式见 [demo_firmware_build.md](examples/demo_firmware_build.md)，记录见 [demo-firmware-build.json](docs/provenance/demo-firmware-build.json)。构建相等是可复现性证据，不是新原生执行或作者权利的绝对证明；也不允许私人 HEX 进入发布内容。

新增的 `examples/matrix_display.a51`、`examples/draw_matrix_display.py`、`examples/build_matrix_firmware.py` 和对应 `matrix_display.hex` 同为本项目独立编写，适用根 [MIT 许可](LICENSE)。矩阵固件由自有纯 Python 8051 子集汇编器直接解析源码、解析标签并编码指令；构建不用外部编译器、链接库、运行库或 HEX 模板。它不是通用 A51 编译器。

构建命令、语法边界和验证限制见 [matrix_firmware_build.md](examples/matrix_firmware_build.md)。源码、构建器、HEX 及地址字节摘要见 [matrix-firmware.json](docs/provenance/matrix-firmware.json)。本轮重建的 235 个程序字节在全部占用地址上与随附 HEX 一致；这证明该例程的构建可复现性，不代表真实原生仿真通过。厂商评估工具日志、OBJ/MAP/LST、编译器和库不分发。

## Proteus 与其他数据

本项目与 Labcenter Electronics 无隶属、授权或合作关系。Proteus 是其商标。软件、器件库、模板、官方样例和它们的器件定义仍适用原许可，不随源码分发。用户需自行安装 Proteus，并在本地准备兼容模板。源码快照不包含 Proteus 截图。

本项目及上游 MIT 许可只覆盖其有权授权的源码，不授予 Proteus 软件使用权或厂商许可例外。[厂商协议](https://www.labcenter.com/downloads/licencing-agreement.pdf)第 7.2 条限制逆向工程，适用法律明确允许的情况除外。当前适配包含私有保存格式解析及特定版本原生控件的固定偏移状态读取；是否适用互操作或其他法律例外尚未确认。维护者了解该风险后授权源码公开，不代表取得厂商授权、专业法律意见或侵权认定。详见 [公开与许可说明](docs/publication.md)。
