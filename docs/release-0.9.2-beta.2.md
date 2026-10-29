# 0.9.2b2 Windows 便携版

Releases 提供 Windows x64 便携 ZIP，内含隔离的 Python、Pillow 和同一份 Proteus 工具源码。无需另装 Python、pip 或修改全局 PATH。用户仍需自行准备合法的兼容 Proteus 8.6 安装与模板；包内不含厂商程序/器件库/模型/模板、私人固件或运行截图，独立示例 A51/HEX 保留。

Codex 与 dsh 共用画图、固件、布线和原生仿真核心。`Install-Codex.cmd`、`Install-DSH.cmd` 是两个薄安装入口；Agent 可使用 `Install-Agent.cmd --platform codex|dsh --home "目录" --json`，并通过 `--dry-run` 预览、`--update` 更新。结果提供内置解释器路径、技能目录、备份和待执行步骤。安装不会自动修改模型、权限或现有 MCP 配置；dsh 配置文件在安装后生成。

启动方式、移动后的更新方法及 dsh 配置步骤见 [便携版说明](portable.md)。依赖来源和 SHA-256 固定在 `portable/dependencies.json`，包内保留 Python、Pillow 及其依赖的原始许可；项目 MIT 不替代这些许可或 [Proteus 使用条款](publication.md)。

本次文件回归、隔离运行、双平台安装、搬移、Agent JSON 接口及原生验证分别记录在 [验收记录](validation/portable-20261029.json)。既有失败与历史原生验收不改写；文件测试不算原生仿真，截图也不替代完整电气或实物验证。

本轮原生验证为便携运行时兼容性检查，包含真实计时、K0 状态回读、三次数码管重建、运行截图和异步子进程清理，不是重新执行历史 16 键完整验收。dsh 检查包含实际 CLI 配置合成及其使用的 MCP 客户端通信，没有新跑模型对话或网页界面交互。
