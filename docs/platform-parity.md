# Codex / DeepSeek Harness 共用适配

沿用同一个已审核的 GitHub 仓库（公开授权范围见 [公开说明](publication.md)）；共用 `proteus86.bridge` 分发器与 `bridge_operations.Operations`，底层仍是现有文件、固件、原生会话和数字验证模块。`adapters/codex/`、`adapters/dsh/` 分别提供薄平台入口；`scripts/dsh_mcp.py` 是 DSH 兼容启动器。不会复制两套核心，也不追求兼容所有 harness。核心统一推进，平台分别验证；0.9.2b1 提供共用 wheel 和两个平台安装入口包，见 [安装与打包](packaging.md)及 [Beta 验证](validation/release-v092b1-20261028.json)。

| 功能 | 两平台共用接口 |
|---|---|
| 清单/JSON 生成、器件库和完整引脚查询 | `project_action` |
| 读取、增删改、移动/旋转/镜像、连线/总线/端子、标题位置、模块整理 | `circuit_edit` 的公共方法清单 |
| 固件绑定、相对资源、显式覆盖及已校验备份 | 原 `Circuit` 机制，经 `circuit_edit` 调用 |
| 核网、几何、诊断、预览、打包、分组准备、引脚修复/转换 | `project_action` |
| 自有原生编辑器保存、独立复开与 SDF | `native_action` 的 editor 操作 |
| 原生计时、状态、诊断、按键/开关/探针、Scenario、扫描显示与运行截图 | `native_action`，保留原生保护 |
| 16 键顺序 5/5/5/1 验收 | `native_action.matrix_verify` 调用维护中的验收脚本 |

`capabilities` 返回当前完整方法、签名、参数、输出根目录、原生启用状态和工具清单 SHA-256。Codex 可经 MCP 或 `python -m proteus86.bridge --request` 使用该分发器；dsh 经标准 stdio MCP 使用。全部修改仍按 `with c.batch():` 执行，保存后重开核网；未知格式、固件哈希、正交出线、原生版本及进程所有权等原有守卫保持不变。

原生功能需要启动配置显式给出 `--allow-native --native-root`，模型不能自行开启。工作区、文件输出根和 ASCII 原生目录也由启动者确定。输入文件不接受越界、链接或重解析点；输出写入限定在输出根。JSON 不接受任意 Python、shell、私有属性或回调代码。需要回调的任意用户 Python 程序仍属于编程环境；常规 Scenario、分组与矩阵验收有结构化入口。两平台都不因此获得未支持的 PCB、任意波形/电压或实物测量能力。

`tests/test_bridge_parity.py` 对照真实公共 `Circuit` / `Simulation` 方法清单，新增核心方法未进入共享契约时回归失败。两个平台的技能从同一个目录用同一个完整、校验、可备份安装器安装：

```powershell
python scripts/install_codex_skill.py --update
python scripts/install_dsh_skill.py --update
```

默认分别读取 `CODEX_HOME` / `DSH_HOME`，也可用 `--home` 显式指定。机器定位清单仍不进入源码发行。dsh 启动配置使用 `docs/proteus86-mcp.patch.yml`；配置工具目录与工作区不同时，用 `DSH_PROTEUS_CHECKOUT` 指定工具源码，输出目录需先创建。完整参数见技能的 `references/bridge.md`。

平台差异只集中在技能发现、工具注册、权限交互和长任务跟踪。安装时从相同公共技能和引用文件组合各平台的短入口；公共资源逐文件相同，平台入口文本不同属于设计，不是核心分叉。长原生验收使用 `matrix_submit` / `recipe_submit` 与最长 30 秒的 `job_wait`，不依赖单次 MCP 请求；早期同步调用超时仍作为失败的传输证据保留，不能因后台最终完成而改称那次 RPC 通过。

## 本次 Windows 权限判断

“工作区内修改”会启动 dsh 的 Windows 沙箱授权流程；它不是“没有创建工作区”的同义错误。此前临时克隆目录已经存在，会话也记录了正确 cwd。代码在该目录上授予工作区 SID 时返回 `SetNamedSecurityInfoW ... grantWrite`。官方诊断发现当前用户对这些目录可改 DACL，但没有 `WRITE_OWNER`；新建测试目录的两个局部授权修复均验证成功，随后失败点移到每次随机创建的临时目录。原直接 shell 路线继续记为失败。

本机网页启动脚本同样通过 `Start-Process -WorkingDirectory .../workspace` 启动，那个目录实际存在；不要求先在网页额外点击“创建工作区”才有 cwd。不能把错误归因于目录没建，也不能用全权限模式掩盖它。共享 MCP 为现有 Proteus API 提供按根目录约束的调用，并没有修复或放宽 dsh 自带 shell 的沙箱。

具体本机验收与清理结果记录在独立的 `docs/validation/dsh-parity-20261028.json`；此前 `dsh-20261028.json` 仍保留当时仅文件画图的范围。文件通过、原生编辑器、动态仿真、截图、模型会话和安装分别记录。
