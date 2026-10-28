# 两个独立 8051 验证固件的可复现构建

`blink8051.a51` 和 `key_counter.a51` 是本工具独立编写的验证例程，适用根目录 MIT 许可。`build_demo_firmware.py` 直接解析它们的源码、解析标签并编码 8051 指令，不调用 Keil、链接器、外部库或仿真器，也不从已有 HEX 拷贝机器码。

从源码目录使用 Python 3.10+；每次选择新的输出目录：

```powershell
python examples/build_demo_firmware.py --source examples/blink8051.a51 --output-dir output/blink-build-NEW --check-against examples/blink8051.hex
python examples/build_demo_firmware.py --source examples/key_counter.a51 --output-dir output/counter-build-NEW --check-against examples/key_counter.hex
```

构建结果为 39 字节与 42 字节程序及各自的 `manifest.json`。`--check-against` 验证 Intel HEX 校验和，并要求全部占用地址和每个字节一致；记录分段和换行不同不影响地址字节比较，原始 HEX 字节是否相同另有字段。若参考缺字节、多字节或某地址不同，构建在创建输出前失败并报告第一个差异地址。原 A51/HEX 保持不变。

清单记录源文件、此构建器、复用的 `build_matrix_firmware.py` HEX 编解码器、生成 HEX、参考 HEX 以及地址字节流的 SHA-256，还有标签和逐条指令清单。地址字节摘要按地址递增，拼接每项的双字节大端地址和单字节数据后计算。只有 HEX 编解码复用现有自有模块；两个程序的指令编码来自新解析的源码。

这是有意限制的汇编子集：`CSEG AT`、`END`、标签、分号注释，以及列明形式的 `NOP`、`MOV`、`LCALL`、`SJMP`、`DJNZ Rn,label`、`RET`、`JB`、`JNB`、`INC`、`CPL A`。`SP` 仅作为已定义直接地址 81H 使用；其余常量支持无符号十进制、前置数字的 H 后缀十六进制和 `0x` 十六进制。它拒绝未知指令、任意表达式、INCLUDE/EXTRN、宏、未定义/重复/保留标签、代码地址重叠、数值/地址溢出和超出有符号八位范围的相对跳转，不是通用 A51 工具。

构建与字节相等只证明这两个程序的来源可复现，**没有执行固件，也不是 Proteus 原生仿真、时序正确性或实物验证**。本轮不以新构建记录替换旧原生验收，也不改变旧固件或其历史哈希。
