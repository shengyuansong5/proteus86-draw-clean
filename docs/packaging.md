# 安装与发行包

`0.9.2b1` 是双平台 Beta，打包时为私有候选；后续源码公开授权及许可风险见 [公开说明](publication.md)。源码包包含一份核心、两套薄入口、完整公共技能与引用、独立例程、测试和许可；Codex / dsh 入口 ZIP 的共享文件逐字节相同，仅根目录的 `INSTALL.md` 指引不同。解压到固定位置后再安装技能，不要随后删除该源码目录。

```powershell
python scripts/install_codex_skill.py --home <Codex主目录>
python scripts/install_dsh_skill.py --home <DSH主目录>
```

已有技能需要显式 `--update`；安装器先校验可恢复备份，备份放在自动加载的 skills 目录之外。未指定 `--home` 时分别读取 `CODEX_HOME` / `DSH_HOME`。安装不会自动重启服务、修改模型、改变全局权限或注册 MCP。DSH 注册参数见 [共享配置](proteus86-mcp.patch.yml)与 [dsh 说明](dsh-integration.md)。

普通 Python 运行库也可从 wheel 安装到自己的虚拟环境：

```powershell
python -m pip install --no-deps <proteus86_draw-0.9.2b1-py3-none-any.whl>
proteus86 --help
proteus86-mcp --help
```

wheel 不包含技能安装器或厂商资源。调用原有例程 / MCP 的矩阵功能所需的批准辅助脚本和独立 A51/HEX 已包含；无需依赖源码工作目录。按原有说明设置本机 Proteus 目录及模板环境变量。MCP 仍要求启动者显式指定工作区和输出根，原生功能另需 `--allow-native --native-root`；模型不能自行放宽权限。源码方式继续使用 `python scripts/dsh_mcp.py`，安装 wheel 后可用 `proteus86-mcp` 代替这条启动命令。

开发者构建需 setuptools 和 wheel；它们仅是构建工具，不是项目运行时依赖。从审核源码在隔离构建环境运行 `python -m pip wheel --no-deps --no-build-isolation .`。生成文件和 egg-info 应放入独立临时树，不应混入源码清单。`setup.py` 明确限定 wheel 辅助模块，其他本地脚本不会被自动收集。

验证边界、可选私人样本跳过及原生待验状态见 [本次记录](validation/release-v092b1-20261028.json)。发布包的 SHA-256 与逐文件清单放在包外，避免循环摘要。公开授权仅限此次审核的 clean 仓库；原私有仓库、其他工作区和本机资源保持原边界。
