# DeepSeek Harness 与 Codex 共用适配

当前入口已经由早期仅文件生成的桥接器扩展成共用接口，见 [能力与边界](platform-parity.md) 和技能的 [bridge.md](../skills/proteus86-files/references/bridge.md)。原 `draw_circuit` 入口继续兼容；旧的有限验收记录 [dsh-20261028.json](validation/dsh-20261028.json) 不改写为新结果。

两平台共用 Python 3.10+ 核心、技能资源、结构化操作和原生保护，平台入口分别在 `adapters/codex/`、`adapters/dsh/`。默认安装器兼容原 Codex 命令；dsh 用 `python scripts/install_dsh_skill.py --update`，旧的 `--platform dsh` 方式也继续兼容。指定自定义目录可加 `--home`。安装器核对全部支持文件，更新前保留可恢复备份，不发布机器定位清单。

## 从项目启动

先在本机准备合法安装的 Proteus 库与基础模板。需要时设置 `PROTEUS86_HOME`、`PROTEUS86_TEMPLATE`，不要把厂商资源放进源码发行。

```powershell
python -m proteus86 doctor
New-Item -ItemType Directory -Force output/proteus86
# 工具源码不在当前项目时：设置 DSH_PROTEUS_CHECKOUT。
# Python 不在 PATH 时：设置 DSH_PROTEUS_PYTHON 为 Python 3.10+ 的绝对路径。
dsh headless --patch ./docs/dsh-headless.patch.yml --patch ./docs/proteus86-mcp.patch.yml --json '加载 proteus86-files，读取 bridge.md，先调用 capabilities，再通过公共接口完成任务。'
```

`dsh-headless.patch.yml` 显式恢复 headless 默认关闭的已有账户登录，并选择官方 `deepseek-flash`、推理 `low`；本机目录将该标识命名为 `DeepSeek-V4.1-Flash`。不会复制凭据到源码。原生操作只有在启动时额外设置专用、已存在的 ASCII `DSH_PROTEUS_NATIVE_ROOT` 后才会启用。未设置的可选环境变量被过滤，避免 dsh 对 env 的字符串校验失败。

`DSH_PROTEUS_OUTPUT_ROOT` 可指定当前项目内已存在的输出目录，否则为当前项目 `output/proteus86`。输入路径以配置工作区为准，写入路径以输出根为准；`capabilities` 返回实际路径和完整签名。不必使用有故障的 pwsh 工具，也不需要完全权限模式。原生会话仍须检查真实时间、诊断、读回与清理。

`headless` 是独立自动化会话。如果使用独立临时 `DSH_HOME`，它不会出现在原网页聊天中。网页使用相同 MCP 配置与同一完整技能；用户全局配置以实际安装核对结果为准，已有聊天可能需要新建会话以刷新工具和技能。不要把配置文件存在当作已经通过网页会话实测。

## 验证与维护

初次测试发现仓库 `skills/` 不在 dsh 默认扫描目录，因此增加显式发现/完整技能安装。早期直接 shell 路线仍因 Windows 目录授权、临时目录授权失败；详见 [权限分析](platform-parity.md)。当前 Proteus MCP 只暴露显式允许的 Python API，并按已配置目录限制文件操作；不是任意命令执行接口。

早期 RC 文件测试为 5 个元件、4 组网络；模型调整摆放后，保存/重开、核网与导线几何检查通过。SVG 是简化元件预览，不是原生符号或运行截图。新的跨平台文件/原生验收见独立 [对齐记录](validation/dsh-parity-20261028.json)，每项只按本轮实际证据报告。测试工程、截图、会话、运行包和临时认证不进入源码发行；历史版本和验收保留原样。
