"""Read-only import diagnostics. Partial evidence never authorizes rewriting."""
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .resources import sha256


def diagnose_project(project, *, verify=True, parser_error=None):
    path = Path(project).resolve(strict=True)
    report = dict(path=str(path), sha256=sha256(path), readable=False,
                  supported_profile={'CDB':5, 'RELEASE':'806', 'FILEVER':'814'}, findings=[])
    def finding(code, category, detail, remedy, severity='error', **evidence):
        report['findings'].append(dict(code=code, category=category, severity=severity,
                                       detail=detail, remedy=remedy, **evidence))
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len({i.filename for i in infos}) != len(infos): raise ValueError('Duplicate ZIP members')
            if any(i.file_size > 64*1024*1024 for i in infos) or sum(i.file_size for i in infos)>128*1024*1024:
                raise ValueError('Oversized project archive')
            names = {i.filename for i in infos}
            required = {'ROOT.CDB','ROOT.DSN','PROJECT.XML'}
            if not required <= names: raise ValueError('Missing project members: '+str(sorted(required-names)))
            cdb, dsn = archive.read('ROOT.CDB'), archive.read('ROOT.DSN')
            metadata = ET.fromstring(archive.read('PROJECT.XML'))
            stamp = metadata.find('TIMESTAMP')
            report['format'] = dict(CDB=struct.unpack_from('<I',cdb)[0] if len(cdb)>=4 else None,
                                    root_layout_marker=struct.unpack_from('<I',cdb,4)[0] if len(cdb)>=8 else None,
                                    **({k:stamp.get(k) for k in ('RELEASE','FILEVER')} if stamp is not None else {}))
            report['embedded_build_members'] = sorted(name for name in names if name.upper().startswith('FIRMWARE'))
        fmt = report['format']
        if fmt['CDB'] != 5:
            finding('cdb_version', 'version', f"CDB v{fmt['CDB']}，本工具只支持经过验证的 v5",
                    '将副本用 Proteus 8.6 打开并另存，再重新诊断；不要修改 CDB 版本字节')
        elif fmt['root_layout_marker'] != 1:
            finding('root_layout', 'structure', 'ROOT 布局标记不符合已验证的单页结构',
                    '在原生软件中另存单页副本，或导出逻辑网表重建；不要删除未知对象字节')
        if fmt.get('RELEASE') != '806' or fmt.get('FILEVER') != '814':
            finding('metadata_version', 'version', f"保存版本 RELEASE={fmt.get('RELEASE')}, FILEVER={fmt.get('FILEVER')}",
                    '元数据不同不单独证明不兼容；以原生打开及重新解析结果为准', severity='info')
        if report['embedded_build_members']:
            finding('embedded_build', 'resources', '工程附带 VSM Studio 构建配置',
                    '只做另存和网表导出；仿真请重建外置固件工程，不执行参考工程中的构建脚本', severity='info')
        if fmt['CDB']==5 and fmt['root_layout_marker']==1:
            from ._codec.component_codec import _entities
            from ._codec.proteus_project import _cdb_entity_table_offset
            from ._codec.proteus_project import _dsn_component, UnsupportedFormat
            try:
                entities,_ = _entities(cdb)
                # This is the existing guarded v5 decoder, not a second permissive binary parser.
                report['recognized_entities'] = [dict(ref=ref, index=e['index'], property_index=e['property_index']) for ref,e in entities.items()]
                report['entity_record_count'] = struct.unpack_from('<I',cdb,_cdb_entity_table_offset(cdb))[0]
                report['partial_entity_evidence'] = True
                anonymous = [e['index'] for ref,e in entities.items() if not ref]
                if anonymous:
                    finding('anonymous_entity', 'structure', '存在没有元件编号的 CDB 实体',
                            '在兼容软件的副本中为元件分配唯一编号，再另存并检查网表', entity_indexes=anonymous)
                decoded = set();record_guards={}
                for match in re.finditer(rb'\xff[\x01-\x3f][A-Z][A-Z0-9_+?\-]*', dsn):
                    try: decoded.add(_dsn_component(dsn,match.start())['fields'][0]['text'])
                    except (UnsupportedFormat,struct.error) as error:
                        # The reference prefix is already bounded by this existing candidate pattern.
                        size=dsn[match.start()+1]
                        raw=dsn[match.start()+2:match.start()+2+size]
                        try:ref=raw.decode('ascii')
                        except UnicodeDecodeError:continue
                        if ref in entities and ref:record_guards.setdefault(ref,set()).add(str(error))
                missing = sorted(set(entities)-decoded-{''})
                if missing:
                    finding('component_record_layout', 'structure', '部分实体没有本工具支持的完整 DSN 四段文本记录',
                            '原生另存后重试；仍失败时保留工程，用原生 SDF 网表和明确器件映射重建新电路', refs=missing)
                    report['component_record_guards']={ref:sorted(record_guards.get(ref,())) for ref in missing}
                    non_ascii=[ref for ref in missing if 'Non-ASCII component properties' in record_guards.get(ref,())]
                    if non_ascii:
                        finding('non_ascii_component_properties','encoding','元件属性块含非 ASCII 数据，当前 ASCII 编码保护拒绝读取',
                                '在原生副本中检查 PROGRAM 等文件路径，绑定已复制的英文相对路径；匿名元件另行编号，再保存重检。不要改变二进制版本或删除对象字节',refs=non_ascii)
            except (UnsupportedFormat,struct.error,IndexError) as error:
                finding('entity_layout', 'structure', str(error), '保留原文件，通过原生软件另存或导出逻辑网表')
        if verify:
            from .api import Circuit
            from ._codec.component_codec import Circuit as NativeCircuit
            try:
                circuit = NativeCircuit.open.__func__(Circuit,path)
                report['readable'] = True
                report['components'] = len(circuit.components())
            except (ValueError,KeyError,struct.error) as error: parser_error = str(error)
        if parser_error:
            report['parser_error'] = parser_error
            if not any(item['severity']=='error' for item in report['findings']):
                finding('unsupported_structure', 'structure', parser_error,
                        '保存原生兼容副本后重试；若仍失败，导出 SDF 网表重建，保留格式保护')
        report['conversion_steps'] = [
            '复制工程到新的工作目录；原始资料保持只读。',
            '用兼容版本原生打开副本，再另存；如果 8.6 拒绝较新文件，需在创建它的版本中导出 SDF 或支持的旧格式。',
            '重新运行 diagnose；能完整读取后再比较原生 SDF、引脚和网络，另存不保证消除未知对象。',
            '无法读取时，以原生 SDF 和明确的器件映射重建外置固件工程；重新布线后核对网络，不复用未知二进制对象。']
    except (BadZipFile,KeyError,ValueError,struct.error) as error:
        finding('invalid_container', 'container', str(error), '提供完整的 .pdsprj 文件或在原生软件中恢复副本')
    report['source_unchanged'] = sha256(path)==report['sha256']
    return report


def import_message(report):
    details = '; '.join(item['detail'] for item in report['findings'] if item['severity']=='error')
    remedies = '; '.join(dict.fromkeys(item['remedy'] for item in report['findings'] if item['severity']=='error'))
    return f"{report['path']}: {report.get('parser_error','Unsupported project')}. {details}. 修复方法: {remedies}. 运行 diagnose 可查看完整报告"
