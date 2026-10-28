# Proteus 8.6 电路自动化

让 Codex 或 DeepSeek Harness 根据文字需求，生成、修改和检查可继续编辑的 Proteus 8.6 原理图。

当前版本：**0.9.2b1 · Beta**。

## 能做什么

- **画电路**：添加器件、电源与网络标签，生成可在 Proteus 中打开的工程。
- **改电路**：调整元件参数、位置、方向和标号，修改连接并保存新副本。
- **自动排版与布线**：自动布局、正交连线，检查重叠和连通关系。
- **绑定固件**：为支持的单片机绑定程序，整理工程所需的固件资源。
- **验证运行**：通过本机 Proteus 完成受支持的原生保存、数字输入、显示读回和运行截图。

普通画图与文件检查无需启动 Proteus；原生验证会使用本机已安装的软件。

## 支持哪些平台

**Codex 和 DeepSeek Harness 共用一套核心功能与校验规则。** 两个平台只有接入方式不同：各自安装技能、注册工具并处理权限；画图、布线和仿真代码共用。

| 使用平台 | 安装入口 |
|---|---|
| Codex | [安装说明](docs/packaging.md) |
| DeepSeek Harness（dsh） | [安装与 MCP 配置](docs/dsh-integration.md) |

## 开始使用

[下载共通版源码 ZIP](https://github.com/shengyuansong5/proteus86-draw-clean/archive/refs/heads/main.zip)，解压到固定位置，再按对应平台的说明安装。

需要 **Python 3.10+**。使用者需自行准备合法的 **Proteus 8.6 SP2** 安装及兼容模板；项目不附带厂商程序、器件库或模板。

目前主要支持已验证的单页原理图与数字电路流程。PCB 自动布线、任意波形采集和实物验证不在支持范围内；具体兼容性与验证状态见[双平台说明](docs/platform-parity.md)。

## 更多信息

[详细用法与 API](docs/manual.md) · [版本说明](docs/release-0.9.2-beta.1.md) · [平台适配](docs/platform-parity.md)

源码采用 [MIT 许可](LICENSE)，第三方归属见 [THIRD_PARTY.md](THIRD_PARTY.md)。与 Proteus 使用条款有关的未解决风险见[公开与许可说明](docs/publication.md)。
