# Windows 便携版

下载 Releases 中的 `windows-x64-portable.zip`，完整解压到固定位置。不需要安装 Python、pip 或修改系统 PATH；包内提供独立运行环境和截图依赖，不包含 Proteus 软件、器件库或模板。

1. Codex：双击 `Install-Codex.cmd` 安装技能。
2. dsh：双击 `Install-DSH.cmd` 安装技能，再将生成的 `config/DSH-MCP.patch.yml` 加入所用启动命令或配置。安装器不会覆盖已有 dsh 配置或更改模型。
3. 自行配置兼容的合法 Proteus 安装和模板。打开新的模型会话以刷新技能；具体路径设置见 [配置说明](dsh-integration.md)。

需要指定平台主目录时，可运行 `Install-Codex.cmd --home "目录"` 或 `Install-DSH.cmd --home "目录"`。未指定时分别读取 `CODEX_HOME` / `DSH_HOME`，再回退到当前用户的 `.codex` / `.dsh`；自定义安装必须选对目录。更新已有技能或移动便携目录后，加 `--update` 重新安装，保留经校验的旧技能备份。

例如在项目工作目录启动 dsh 的独立会话：

```text
dsh headless --patch "便携目录/config/DSH-MCP.patch.yml" --json "先调用 capabilities，再完成电路任务"
```

账号登录与模型选择仍使用自己的 dsh 配置；本项目不附带凭据。原生能力需在启动前另设 `DSH_PROTEUS_NATIVE_ROOT` 为专用、已存在的 ASCII 绝对目录；默认配置只启用文件功能。MCP 的输入工作区为 dsh 启动目录，输出限于该工作区的 `output/proteus86`；缺少时由启动入口按相同目录保护创建。

`Proteus86.cmd` 提供原 CLI；`Proteus86-MCP.cmd` 提供同一结构化 MCP/JSON-RPC 接口。两平台共用 `app/proteus86`，没有第二套画图或仿真代码。运行时位于 `runtime`，公共源码、示例与许可位于 `app`。

## Agent 安装

Agent 可先读取包根目录的 `INSTALL.json` 获取机器可读的入口和参数，再使用不暂停、不提问的统一入口：

```text
Install-Agent.cmd --platform codex --home "平台主目录" --json --dry-run
Install-Agent.cmd --platform codex --home "平台主目录" --json
Install-Agent.cmd --platform dsh --home "平台主目录" --json
```

`--dry-run` 不写入任何安装文件；已有技能需显式 `--update`。成功返回退出码 0 和一份 JSON，失败返回非零退出码及错误 JSON。结果包含技能目录、内置解释器、MCP 配置、备份和 `next_actions`。Agent 应继续执行返回的会话刷新及 dsh 配置加载步骤；`mcp_registered: false` 表示尚未修改现有 MCP 配置，不应误报已完成工具注册。

便携版目标为 Windows x64。它未提供 Windows ARM64、32 位系统或 Windows 7 的兼容保证。原生仿真只支持既有已验证的 Proteus 8.6 配置；完整能力边界及原生待验状态仍以版本记录为准。文件测试不等同于原生仿真或实物验证。

包内保留 Python、Pillow 和其依赖的原始许可。工具源码使用 MIT；这不替代 Proteus 的使用权或消除 [厂商条款风险](publication.md)。构建依赖来源和 SHA-256 固定在 `portable/dependencies.json`。
