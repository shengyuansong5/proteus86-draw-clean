import argparse
import json
import sys
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import struct
import xml.etree.ElementTree as ET

from . import Circuit, Library, Project, Installation, from_spec, __version__
from .installation import DEFAULT_TEMPLATE, ROOT


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main():
    # File/automation consumers use UTF-8 even on a legacy Windows locale.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure') and not stream.isatty():stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Proteus 8.6 Python 原生画图工具")
    parser.add_argument("--install", help="Proteus 安装目录")
    parser.add_argument("--template", type=Path, help="本机保存过的 8.6 单页模板")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="检查安装、模板和兼容格式")
    search = commands.add_parser("search", help="查询本机器件库")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    info = commands.add_parser("device", help="查看器件的引脚和默认属性")
    info.add_argument("name")
    info.add_argument("--library")
    inspect = commands.add_parser("inspect", help="读取支持的原生工程元件")
    inspect.add_argument("project", type=Path)
    inspect.add_argument('--geometry', action='store_true', help='包含引脚、导线、结点及电源信息')
    item = commands.add_parser('diagnose', help='只读检查工程版本、对象结构和转换步骤')
    item.add_argument('project', type=Path)
    item = commands.add_parser('bind-firmware', help='给工程绑定中文或空格路径的外置固件，保存可移植副本')
    item.add_argument('project', type=Path)
    item.add_argument('--firmware', action='append', required=True, metavar='REF=PATH')
    item.add_argument('-o','--output',type=Path,required=True)
    for command in ('generate', 'autoplace', 'place'):
        item = commands.add_parser(command, help={'generate':'清单和网络表自动布局布线成工程', 'autoplace':'从清单计算布局文本', 'place':'生成已摆件的工程，等待 route 布线'}[command])
        item.add_argument('design', type=Path)
        item.add_argument('-o', '--output', type=Path, required=True)
        if command != 'autoplace':
            item.add_argument('--overwrite', action='store_true')
    item = commands.add_parser('route', help='直接给保存的工程布线，输出新工程')
    item.add_argument('project', type=Path)
    item.add_argument('-o', '--output', type=Path, required=True)
    item.add_argument('--net', action='append', required=True, help='REF.PIN,REF.PIN,TERMINAL 可重复')
    item.add_argument('--replace', action='store_true', help='重新建立显式连线')
    item.add_argument('--overwrite', action='store_true')
    item = commands.add_parser('convert-net', help='Protel 2.0 .net 转器件清单与网络表')
    item.add_argument('netlist', type=Path)
    item.add_argument('-o','--output',type=Path,required=True)
    item.add_argument('--device-field',choices=('PARTTYPE','FOOTPRINT'),default='PARTTYPE')
    item.add_argument('--device-map',type=Path,help='可选的器件名映射 JSON')
    item = commands.add_parser('pincheck', help='核对 CDB 引脚顺序与符号定义是否一致')
    item.add_argument('project',type=Path)
    item = commands.add_parser('fix-pins',help='等长修复 CDB 引脚顺序并另存')
    item.add_argument('project',type=Path)
    item.add_argument('-o','--output',type=Path,required=True)
    item = commands.add_parser('netcheck', help='直接从保存文件核对期望网络表')
    item.add_argument('project', type=Path)
    item.add_argument('--design', type=Path)
    item.add_argument('--net', action='append', default=[])
    item = commands.add_parser('render', help='从保存文件生成 SVG 几何预览')
    item.add_argument('project', type=Path)
    item.add_argument('-o', '--output', type=Path, required=True)
    item = commands.add_parser('wiringcheck', help='检查图幅、共线重叠和估计的文字/符号遮挡')
    item.add_argument('project', type=Path)
    item.add_argument('--strict', action='store_true', help='将几何估计警告也视为失败')
    item = commands.add_parser('wire-quality', help='只读检查叠线、非结点交叉、并行间距和折弯')
    item.add_argument('project', type=Path)
    item.add_argument('--min-gap', type=float, default=2.54, help='并行线最小间距，毫米')
    item.add_argument('--min-parallel', type=float, default=2.54, help='纳入间距检查的最短并行区段，毫米')
    item = commands.add_parser('fit-sheet', help='整体平移、按实际导线范围适配图幅，另存工程')
    item.add_argument('project', type=Path)
    item.add_argument('-o', '--output', type=Path, required=True)
    item.add_argument('--keep-coordinates', action='store_true')
    item = commands.add_parser('tidy-labels', help='避让标号和值文字，保留元件与导线位置')
    item.add_argument('project', type=Path)
    item.add_argument('-o', '--output', type=Path, required=True)
    item.add_argument('--max-shift', type=float, default=20.32, help='文字最大移动距离，毫米')
    item = commands.add_parser('firmware-info', help='检查固件格式、HEX 校验和与地址范围')
    item.add_argument('firmware', type=Path)
    for command in ('prepare-run','package','simulate'):
        item = commands.add_parser(command, help={'prepare-run':'复制工程与固件成独立仿真包','package':'只打包工程和外置固件，不启动软件','simulate':'原生定时仿真、收集日志并输出结果'}[command])
        item.add_argument('project', type=Path)
        item.add_argument('-o','--output',type=Path,required=True,help='新的输出目录')
        item.add_argument('--firmware',action='append',default=[],metavar='REF=PATH')
        if command=='simulate':
            item.add_argument('--seconds',type=float,default=1)
            item.add_argument('--timeout',type=float,default=30)
    for command in ("build", "check", "demo"):
        item = commands.add_parser(command, help={"build": "从 JSON 生成工程", "check": "校验 JSON 和连线，不写文件", "demo": "生成示例电路"}[command])
        if command == "demo":
            item.add_argument("example", choices=("rc", "led", "mcu"), default="rc", nargs="?")
        else:
            item.add_argument("spec", type=Path)
        if command != "check":
            item.add_argument("-o", "--output", type=Path, required=True)
            item.add_argument("--overwrite", action="store_true", help="先校验备份，再覆盖已有目标")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            install = Installation.discover(args.install)
            template = args.template or DEFAULT_TEMPLATE
            with ZipFile(template) as archive:
                metadata = ET.fromstring(archive.read("PROJECT.XML"))
                cdb_version = struct.unpack_from("<I", archive.read("ROOT.CDB"))[0]
            circuit = Circuit(template, install=install.home)
            output({"tool_version": __version__, "installation": str(install.home), "executable": str(install.executable),
                    "template": str(template), "CDB": cdb_version, "timestamp": metadata.find("TIMESTAMP").attrib,
                    "template_devices": list(circuit.templates), "file_codec_ready": True,
                    "simulation_api": "Simulation / simulate：本机已验证版本的原生控制；仅显式调用时启动独立进程"})
        elif args.command == "search":
            output(Library(install=args.install).search(args.query, args.limit))
        elif args.command == 'diagnose':
            from .diagnostics import diagnose_project
            result = diagnose_project(args.project)
            output(result)
            return 0 if result['readable'] else 1
        elif args.command == "device":
            output(Library(install=args.install).get(args.name, args.library))
        elif args.command == "inspect":
            if args.geometry:
                from .inspection import inspect_project
                output(inspect_project(args.project))
            else:
                output(Project(args.project).components())
        elif args.command in ('generate', 'autoplace', 'place'):
            from .design import parse_design, from_design, format_layout
            design = parse_design(args.design.read_text(encoding='utf-8-sig'))
            circuit = from_design(design, install=args.install, template_project=args.template, route=args.command == 'generate', resource_base=args.design.parent)
            if args.command == 'autoplace':
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open('x', encoding='utf-8') as stream:
                    stream.write(format_layout(circuit, design))
                output({'layout': str(args.output.resolve()), 'placements': circuit.layout_report})
            else:
                result = circuit.save(args.output, overwrite=args.overwrite)
                output({'project': str(result), 'placements': circuit.layout_report, 'connected_nets': sum(len(net) > 1 for net in circuit.nets())})
        elif args.command == 'route':
            from .design import route_file
            output({'project': str(route_file(args.project, args.output, args.net, overwrite=args.overwrite, replace=args.replace, install=args.install))})
        elif args.command == 'netcheck':
            from .inspection import netcheck
            from .design import parse_design
            expected = list(args.net)
            if args.design:
                expected += parse_design(args.design.read_text(encoding='utf-8-sig'))['nets']
            if not expected:
                raise ValueError('netcheck requires --design or --net')
            result = netcheck(args.project, expected)
            output(result)
            return 0 if result['passed'] else 1
        elif args.command == 'render':
            from .preview import render
            output({'preview': str(render(args.project, args.output))})
        elif args.command == 'wire-quality':
            from .quality import wire_quality
            result = wire_quality(args.project,min_gap_mm=args.min_gap,min_parallel_mm=args.min_parallel)
            output(result)
            return 0 if result['passed'] else 1
        elif args.command == 'wiringcheck':
            from .geometry import wiringcheck
            result = wiringcheck(args.project)
            output(result)
            return 0 if result['passed'] and not (args.strict and result['warnings']) else 1
        elif args.command == 'fit-sheet':
            circuit = Circuit.open(args.project, install=args.install)
            circuit.fit_sheet(center=not args.keep_coordinates)
            output({'project': str(circuit.save(args.output)), 'sheet': circuit.sheet_report})
        elif args.command == 'tidy-labels':
            circuit = Circuit.open(args.project, install=args.install)
            circuit.tidy_labels(max_shift_mm=args.max_shift)
            output({'project': str(circuit.save(args.output)), 'labels': circuit.label_report})
        elif args.command == 'firmware-info':
            from .firmware import firmware_info
            output(firmware_info(args.firmware))
        elif args.command in ('prepare-run','package','simulate','bind-firmware'):
            mapping={}
            for value in args.firmware:
                ref,separator,path=value.partition('=')
                if not separator or not ref or not path or ref in mapping:raise ValueError('Use distinct --firmware REF=PATH entries')
                mapping[ref]=str(Path(path).resolve())
            if args.command=='bind-firmware':
                circuit = Circuit.open(args.project, install=args.install)
                with circuit.batch():
                    for ref,path in mapping.items(): circuit.bind_firmware(ref,path)
                saved = circuit.save(args.output)
                output(dict(project=str(saved), resources=circuit.resource_report))
            elif args.command in ('prepare-run','package'):
                from .firmware import prepare_run
                output(prepare_run(args.project,args.output,firmware=mapping))
            else:
                from .simulation import simulate
                result=simulate(args.project,args.output,duration=args.seconds,timeout=args.timeout,firmware=mapping,install=args.install)
                output(result)
                return 0 if result['passed'] else 1
        elif args.command == 'convert-net':
            from .netlist import protel_to_design
            mapping=json.loads(args.device_map.read_text(encoding='utf-8-sig')) if args.device_map else None
            text=protel_to_design(args.netlist.read_text(encoding='utf-8-sig'),device_field=args.device_field,device_map=mapping)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x',encoding='utf-8') as stream:
                stream.write(text)
            output({'design':str(args.output.resolve())})
        elif args.command == 'pincheck':
            from .repair import check_pin_order
            result=check_pin_order(args.project)
            output(result)
            return 0 if result['passed'] else 1
        elif args.command == 'fix-pins':
            from .repair import fix_pin_order
            output(fix_pin_order(args.project,args.output))
        else:
            path = Path(__file__).parent / "examples" / (args.example + ".json") if args.command == "demo" else args.spec
            spec = json.loads(path.read_text(encoding="utf-8-sig"))
            circuit = from_spec(spec, install=args.install, template_project=args.template, resource_base=args.spec.parent if args.command != 'demo' else None)
            if args.command == "check":
                output(circuit.summary())
            else:
                path = circuit.save(args.output, title=spec.get("title"), overwrite=args.overwrite)
                output({"project": str(path), "components": len(circuit._parts), "connections": len(circuit._connections),
                        "backup": str(circuit.last_backup) if circuit.last_backup else None})
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, struct.error, BadZipFile, ET.ParseError) as error:
        print("错误: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
