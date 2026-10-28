# 0.9.1 干净源码发行补充

本轮补齐来源与构建记录，并从审核源码建立独立 Git 历史。仍面向 **Codex**；其他 harness 需要自行适配和端到端验证。仓库保持私有，实际公开需用户后续授权。

## 已补齐的来源证据

- 编解码器来源固定到 `7439819a7ea4cff47fb9b321d8b0e97ac74fafb2`，功能参考 pdsprj-auto 固定到 `d3a07201fcf9aa7929df0f5a421d0902f9dcce38`。原 main ZIP 摘要、固定提交归档、完整 Git blob 树及保留来源逐文件一致，原 MIT 声明一致。详见 [codec-source.json](provenance/codec-source.json)、[pdsprj-auto-source.json](provenance/pdsprj-auto-source.json)。原始上游归档不分发。
- 新增自有 [build_demo_firmware.py](../examples/build_demo_firmware.py)，从两份原 A51 真正编码 39/42 字节程序，全部占用地址及字节与随附 HEX 相等。它不调用 Keil、链接库或外部编译器，不把既有 HEX 作为生成模板。详见 [构建方法](../examples/demo_firmware_build.md)、[构建记录](provenance/demo-firmware-build.json)及[独立例程清单](provenance/independent-examples.json)。
- `key_counter.hex` 的原 CRLF 文本保持原样；规范 LF 构建输出的文件 SHA 不同，但程序地址和字节完全一致。记录同时保留两种摘要，未伪造文件字节相等。

## 干净历史与发行边界

新仓库从逐文件审核清单建立单个无父提交的初始提交，不继承原私有仓库的 Git 对象、分支、标签、旧截图或其他历史。原私有仓库保留其代码、可见性和历史。提交使用项目通用署名与 noreply 地址；托管平台仍会显示仓库所属账号，这不是匿名托管。

只发行工具源码、独立例程、测试、说明和许可；课程作业、个人标识、凭据、安装定位清单、运行截图、运行包、厂商程序/库/模型/模板和派生工程均不进入清单。保留 [MIT 与第三方归属](../THIRD_PARTY.md)。来源和构建核对不替代绝对法律保证，也不重新授权上游排除的第三方资产。

## 验证范围

本轮新增测试覆盖真实指令编码、标签重定位、数值/跳转/地址范围、非法输入、HEX 校验及地址对照、原文件保护与中文/空格路径。完整回归与脱敏源码检查见 [本轮记录](validation/clean-source-20261028.json)。文件构建没有执行固件，不是原生仿真。

现有 36 个运行时模块、矩阵构建器、原 A51/HEX、原生验收脚本保持字节不变。此前 [0.9.1 原生验收](validation/v0.9.1.json)及[发布说明](release-0.9.1.md)保留原测量范围；本轮没有重新运行 Proteus，不能把旧原生结果改标成本轮新运行。此前的 295 项与本轮增加测试后的数量分别记录；私人参考样本的可选跳过明确披露。
