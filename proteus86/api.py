"""Public file API. Runtime generation requires no desktop automation."""
import hashlib
import math
import shutil
import uuid
import copy
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .installation import DEFAULT_TEMPLATE, Installation
from ._codec.component_codec import Circuit as NativeCircuit
from ._codec.device_library import Library as NativeLibrary
from ._codec.proteus_project import Project, UnsupportedFormat


class PropertyError(ValueError):
    """A repairable property error with component/property context."""
    def __init__(self, ref, key, reason, hint):
        self.ref, self.property, self.reason, self.hint = ref, key, reason, hint
        super().__init__(f'{ref}.{key}: {reason}. 修复方法: {hint}')


def mm(value):
    """Convert millimetres to native integer coordinates; Y points upwards."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("坐标必须是有限数值")
    result = round(value * 100000)
    if not -2**31 <= result < 2**31:
        raise ValueError("坐标超出 Proteus 的范围")
    return result


class Library(NativeLibrary):
    def __init__(self, directory=None, *, install=None):
        super().__init__(directory if directory is not None else Installation.discover(install).library)


class Circuit(NativeCircuit):
    """Create native 8.6 schematics, importing devices from the local library."""
    def __init__(self, template_project=None, *, install=None, library_directory=None):
        template = Path(template_project) if template_project is not None else DEFAULT_TEMPLATE
        if not template.is_file():
            raise FileNotFoundError("缺少 8.6 模板，请按 README 的模板准备说明操作: " + str(template))
        library = Path(library_directory) if library_directory is not None else Installation.discover(install).library
        self.installation_library = library.resolve()
        self.last_backup = None
        self._batch_depth = 0
        self._resources = {}
        self._pending_visibility = {}
        self.routing_options = {'clearance': 127000, 'lead': 254000, 'avoid_labels': True}
        super().__init__(template, library_directory=library, fallback_project=DEFAULT_TEMPLATE)

    @classmethod
    def open(cls, path, **options):
        try:
            return super().open(path, **options)
        except UnsupportedFormat as error:
            from .diagnostics import diagnose_project, import_message
            report = diagnose_project(path, verify=False, parser_error=str(error))
            failure = UnsupportedFormat(import_message(report))
            failure.diagnostic = report
            raise failure from error

    def add(self, device, ref, value, x, y, *, library=None, **options):
        if device not in self.templates:
            self.import_device(device, library=library)
        properties = options.pop('properties', None)
        visibility = options.pop('property_visibility', None)
        if properties is not None or visibility is not None:
            with self.batch():
                result = super().add(device, ref, value, x, y, **options)
                changes = {}
                if properties is not None: changes['properties'] = properties
                if visibility is not None: changes['property_visibility'] = visibility
                self.update(ref, **changes)
            return result
        return super().add(device, ref, value, x, y, **options)

    add_component = add

    def add_mm(self, device, ref, value, x, y, **options):
        return self.add(device, ref, value, mm(x), mm(y), **options)

    def move_mm(self, ref, x, y):
        return self.move(ref, mm(x), mm(y))

    def _validate(self, parts, connections, terminals=None):
        if self._batch_depth:
            return
        return super()._validate(parts, connections, terminals)

    @contextmanager
    def batch(self):
        """Apply a group of edits atomically, routing once at the end."""
        outer = self._batch_depth == 0
        snapshot = {key: copy.deepcopy(value) for key, value in self.__dict__.items()
                    if key != '_library_catalogue'} if outer else None
        self._batch_depth += 1
        try:
            yield self
            self._batch_depth -= 1
            if outer:
                self._validate(self._parts, self._connections)
        except BaseException:
            if outer:
                self.__dict__.clear()
                self.__dict__.update(snapshot)
            else:
                self._batch_depth -= 1
            raise

    def connect_net(self, *pins, name=None):
        """Connect a multi-pin net, with actual native junctions as needed."""
        if len(pins) == 1 and isinstance(pins[0], list):
            pins = tuple(pins[0])
        endpoints = [self._endpoint(pin) for pin in pins]
        if len(endpoints) < 2 or len(set(endpoints)) != len(endpoints):
            raise ValueError('connect_net requires at least two different pins')
        with self.batch():
            groups = self.nets(physical=True)
            by_pin = {pin: group for group in groups for pin in group}
            connected = set(by_pin[endpoints[0]])
            for endpoint in endpoints[1:]:
                if endpoint not in connected:
                    self.connect(endpoints[0], endpoint)
                    connected.update(by_pin[endpoint])
            if name is not None:
                self.add_terminal('label', name, endpoints[0])
        return self

    def nets(self, *, physical=False):
        from .connectivity import nets
        return nets(self, physical=physical)

    def autoplace(self, nets=None, *, gap_mm=12.7, fixed=()):
        from .layout import autoplace
        groups = nets if nets is not None else [list(net) for net in self.nets(physical=True) if len(net) > 1]
        self.layout_report = autoplace(self, groups, gap=mm(gap_mm), fixed=fixed)
        return self

    def arrange_labels(self, *, gap_mm=2.54):
        """Put reference/value labels above each real pin envelope."""
        gap = mm(gap_mm)
        if gap < 0:
            raise ValueError('Label gap must be nonnegative')
        with self.batch():
            for ref in [part['ref'] for part in self._parts]:
                part = self._parts[self._index(ref)]
                points = list(self._template(part)['pin_offsets'].values())
                center = (min(p[0] for p in points) + max(p[0] for p in points)) // 2
                y = max(p[1] for p in points) + gap
                directions = self._template(part)['pin_directions'].values()
                if all(direction[0] == 0 for direction in directions):
                    x = max(p[0] for p in points) + gap
                    y = (min(p[1] for p in points) + max(p[1] for p in points)) // 2
                    offsets = {'reference': (x, y + 508000), 'value': (x, y), 'device': (x, y)}
                else:
                    offsets = {'reference': (center - len(ref) * 85000, y + 660400),
                               'value': (center - len(part['value']) * 70000, y + 254000),
                               'device': (center - len(part['value']) * 70000, y + 254000)}
                self.update(ref, label_offsets=offsets)
            self.routing_options = dict(self.routing_options, avoid_labels=True)
        return self

    def arrange_modules(self, modules):
        """Place named module grids and ordered LED/resistor rows; preserve connectivity."""
        from .layout import arrange_modules
        arrange_modules(self,modules)
        return self

    def translate_mm(self, dx, dy):
        """Translate every circuit object and retained path together."""
        from .geometry import translate
        translate(self, mm(dx), mm(dy))
        return self

    def set_property_visibility(self, ref, **visibility):
        """Show/hide native model properties without changing their values."""
        return self.update(ref, property_visibility=visibility)

    def _terminal_label_data(self, terminal_id, *, default=False):
        """Resolve existing terminal metadata through the supported formatter."""
        from ._codec.net_objects import TERMINALS, read_terminal, terminal_markers, terminal_record
        from ._codec.pin_geometry import transform
        if not isinstance(terminal_id, str):
            raise ValueError('Unknown or ambiguous terminal ID: ' + repr(terminal_id))
        matches = [terminal for terminal in self._terminals if terminal['id'] == terminal_id]
        if len(matches) != 1:
            raise ValueError('Unknown or ambiguous terminal ID: ' + repr(terminal_id))
        terminal = matches[0]
        if not default and terminal.get('label') is not None:
            return copy.deepcopy(terminal['label'])
        rotation = terminal.get('rotation')
        if rotation is None and terminal.get('pin') is not None:
            ref, name = terminal['pin']
            pin = next(pin for pin in self.pins(ref) if pin['name'] == name)
            node = terminal_markers(self._dsn, TERMINALS[terminal['kind']][0])['$MKRNODE']
            rotation = next((angle for angle in (0, 900, 1800, 2700)
                             if tuple((v > 0) - (v < 0) for v in transform(node, angle)) ==
                             tuple(-v for v in pin['direction'])), None)
            if rotation is None:
                raise ValueError('Cannot orient terminal toward its pin: ' + terminal_id)
        if rotation is None:
            rotation = 0
        record, _ = terminal_record(self._dsn, terminal['kind'], terminal['name'],
                                    self._terminal_contact(terminal), rotation)
        return read_terminal(record, 0)['label']

    def terminal_label_position(self, terminal_id):
        """Return a terminal caption's absolute native-integer (x, y) anchor.

        There are 100000 native units per millimetre. Uncustomized captions use
        the current glyph/pin orientation's default anchor; reading is pure.
        """
        return tuple(self._terminal_label_data(terminal_id)['position'])

    def set_terminal_label_position(self, terminal_id, position):
        """Move only a terminal caption; None restores its current default.

        ``position`` is a pair of signed int32 native coordinates, not mm.
        Stored font/style and terminal/connection identities are retained.
        Changes participate in batch rollback, including interruptions.
        """
        label = self._terminal_label_data(terminal_id)
        if position is None:
            position = self._terminal_label_data(terminal_id, default=True)['position']
        if (not isinstance(position, (tuple, list)) or len(position) != 2 or
                any(type(value) is not int or not -2**31 <= value < 2**31 for value in position)):
            raise ValueError('Terminal ' + terminal_id + ': label position must be two signed int32 native coordinates (100000 per mm), or None')
        label['position'] = tuple(position)
        with self.batch():
            terminal = next(item for item in self._terminals if item['id'] == terminal_id)
            terminal['label'] = label
        return self

    def _declared_properties(self, part):
        from ._codec.device_library import definition_groups, describe_definition
        symbol = self._template(part)['symbol']
        definitions = definition_groups(self._dsn)['devices']
        if symbol not in definitions: return set()
        metadata = describe_definition({}, definitions[symbol]['body'])
        return {line.strip().strip('{}').split('=', 1)[0]
                for line in metadata['sections'].get('PROPDEFS', []) if '=' in line}

    def _firmware_binding(self, ref, path):
        from .firmware import firmware_info
        from .resources import relative_firmware
        part = self._parts[self._index(ref)]
        if getattr(self,'_loaded',False) and any(name.upper().startswith('FIRMWARE') for name in self._members):
            raise PropertyError(ref,'PROGRAM','工程含嵌入式 VSM Studio 构建，可能覆盖外置固件',
                                '先在原生副本中明确转换为外置固件工程，再绑定；不执行或删除未知构建项')
        if 'PROGRAM' not in self._declared_properties(part):
            raise PropertyError(ref, 'PROGRAM', '该器件没有声明固件属性', '选择支持 PROGRAM 的 MCU 或使用正确的属性名')
        try:
            info = firmware_info(path)
        except (OSError, ValueError) as error:
            raise PropertyError(ref, 'PROGRAM', str(error), '提供存在且格式有效的 HEX/ELF/BIN/COF 文件路径') from error
        relative = str(relative_firmware(ref, info))
        return relative, info

    def bind_firmware(self, ref, path, *, visible=None):
        """Accept any local Unicode path; copy/hash-check at save, use ASCII relative PROGRAM."""
        if visible is not None and type(visible) is not bool:
            raise PropertyError(ref, 'PROGRAM', 'visible 必须是布尔值', '使用 visible=False 隐藏或 True 显示')
        relative, info = self._firmware_binding(ref, path)
        with self.batch():
            self._resources[relative] = info
            changes = dict(properties={'PROGRAM': relative})
            if visible is not None: changes['property_visibility'] = {'PROGRAM': visible}
            self.update(ref, **changes)
        return self

    def update(self, ref, **changes):
        """Validate property context immediately, even inside a deferred routing batch."""
        if not set(changes) & {'properties', 'property_visibility'}:
            return super().update(ref, **changes)
        part = self._parts[self._index(ref)]
        properties = changes.get('properties', {})
        visibility = changes.get('property_visibility', {})
        if not isinstance(properties, dict) or not isinstance(visibility, dict):
            raise PropertyError(ref, '*', '属性和显示设置必须是映射', '使用 properties={...} 或关键字属性')
        properties = dict(properties)
        resources = {}
        for key, value in properties.items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_.]*', key) or key in {'REF','DEVICE','VALUE'}:
                raise PropertyError(ref, key, '非法或保留属性名', '使用器件声明的属性名；元件值用 update(value=...)')
            if value is None: continue
            if key == 'PROGRAM' and not isinstance(value,(str,Path)):
                raise PropertyError(ref,key,'固件值必须是文件路径','提供字符串或 Path；用 None 移除属性')
            if key == 'PROGRAM' and key not in self._declared_properties(part):
                raise PropertyError(ref,key,'该器件没有声明固件属性','选择支持 PROGRAM 的 MCU 或使用正确的属性名')
            if key == 'PROGRAM' and value:
                candidate = Path(value) if isinstance(value, (str, Path)) else None
                base = getattr(self, '_resource_base', None) or (self.source.parent if getattr(self, '_loaded', False) else Path.cwd())
                resolved = candidate if candidate and candidate.is_absolute() else base / candidate if candidate else None
                # Existing ASCII literals remain accepted, including unresolved paths for later preflight.
                if candidate and str(value) not in self._resources and (isinstance(value, Path) or not str(value).isascii() or candidate.is_absolute() or ' ' in str(value) or resolved.is_file()):
                    relative, info = self._firmware_binding(ref, resolved)
                    properties[key] = relative; resources[relative] = info
            text = str(properties[key])
            if any(not 32 <= ord(char) < 127 or char in '{}' for char in text):
                raise PropertyError(ref, key, '值包含非 ASCII、控制字符或花括号', 'PROGRAM 请使用 bind_firmware(ref, path)；其他属性使用可打印 ASCII')
        current = {line.strip().strip('{}').split('=', 1)[0]
                   for line in self._template(part)['properties'].splitlines() if '=' in line}
        current.update(key for key,value in properties.items() if value is not None)
        current.difference_update(key for key,value in properties.items() if value is None)
        pending = dict(self._pending_visibility.get(ref, {}))
        actual = {}
        for key, visible in visibility.items():
            if type(visible) is not bool or not isinstance(key, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_.]*', key) or key in {'REF','DEVICE','VALUE'}:
                raise PropertyError(ref, key, '非法显示设置', '属性名必须合法，显示值必须是 True 或 False')
            if key not in current:
                # Only the declared firmware slot may be deferred. A typo never becomes a pending property.
                if key != 'PROGRAM' or key not in self._declared_properties(part):
                    raise PropertyError(ref, key, 'Unknown property for visibility: '+key, '先设置存在的属性值，或检查该器件的属性名称')
                pending[key] = visible
            else: actual[key] = visible
        for key in list(pending):
            if key in current:
                actual.setdefault(key, pending.pop(key))
        forwarded = dict(changes)
        if 'properties' in changes: forwarded['properties'] = properties
        if actual: forwarded['property_visibility'] = actual
        else: forwarded.pop('property_visibility', None)
        # batch() also rolls back pending visibility and bindings if encoding/routing fails.
        with self.batch():
            self._pending_visibility[ref] = pending
            self._resources.update(resources)
            if forwarded: super().update(ref, **forwarded)
        return self

    def rename(self, ref, new_ref):
        with self.batch():
            result = super().rename(ref, new_ref)
            if ref in self._pending_visibility:
                self._pending_visibility[new_ref] = self._pending_visibility.pop(ref)
        return result

    def copy_component(self, ref, new_ref, x, y):
        result=super().copy_component(ref,new_ref,x,y)
        if ref in self._pending_visibility:
            self._pending_visibility[new_ref]=dict(self._pending_visibility[ref])
        return result

    def delete_component(self, ref):
        result=super().delete_component(ref)
        self._pending_visibility.pop(ref,None)
        return result

    def tidy_labels(self, *, max_shift_mm=20.32):
        """Move colliding reference/value labels; keep devices and wires fixed."""
        from .geometry import tidy_labels
        self.label_report = tidy_labels(self, max_shift=mm(max_shift_mm))
        return self

    def arrange_terminals(self, *, reposition=False):
        from .geometry import arrange_terminals
        arrange_terminals(self, reposition=reposition)
        return self

    def fit_sheet(self, *, margin_mm=5.08, footer_mm=17.78, center=True):
        """Fit actual saved geometry onto the sheet, preserving relative layout."""
        from .geometry import fit_sheet
        self.sheet_report = fit_sheet(self, margin=mm(margin_mm), footer=mm(footer_mm), center=center)
        for item in getattr(self, 'layout_report', []):
            part = self._parts[self._index(item['ref'])]
            item['x'], item['y'] = part['x'], part['y']
        return self

    def connect_bus(self, first_ref, second_ref, pairs):
        """Connect corresponding logical pins or physical pin numbers in bulk."""
        with self.batch():
            for first, second in pairs:
                self.connect((first_ref, str(first)), (second_ref, str(second)))
        return self

    def label_wire(self, first, second, name, *, position=None):
        """Add a genuine WIRE LABEL to an existing branch, without a port symbol."""
        if not isinstance(name, str) or not name or not name.isascii() or any(ord(ch) < 32 for ch in name):
            raise ValueError('Wire label must be nonempty printable ASCII')
        endpoints = {self._endpoint(first), self._endpoint(second)}
        connections = copy.deepcopy(self._connections)
        matches = [item for item in connections if {item['first'], item['second']} == endpoints]
        if len(matches) != 1:
            raise ValueError('The labelled branch must exist exactly once')
        label = {'text': name, 'auto_position': position is None, 'position': (0, 0) if position is None else tuple(position)}
        matches[0].setdefault('labels', []).append(label)
        self._validate(self._parts, connections)
        self._connections = connections
        return self

    def autoroute(self, *, clearance_mm=1.27, lead_mm=2.54, obstacles_mm=()):
        """Recompute automatic routes, retaining explicit manual paths."""
        from ._codec.net_edit import invalidate_routes
        options = dict(self.routing_options, **{'clearance': mm(clearance_mm), 'lead': mm(lead_mm),
                   'obstacles': [[mm(v) for v in bounds] for bounds in obstacles_mm]})
        connections = copy.deepcopy(self._connections)
        terminals = copy.deepcopy(self._terminals)
        touched = [tuple(connection['first']) for connection in connections if connection.get('preserve_geometry')]
        touched += [tuple(terminal['pin']) for terminal in terminals if terminal.get('pin') is not None]
        manual = {index: copy.deepcopy(connection['points']) for index, connection in enumerate(connections)
                  if connection.get('points') is not None and not connection.get('preserve_geometry')}
        connections, terminals = invalidate_routes(connections, terminals, touched)
        for index, points in manual.items():
            connections[index]['points'] = points
        old = self.routing_options
        self.routing_options = options
        try:
            self._validate(self._parts, connections, terminals)
        except BaseException:
            self.routing_options = old
            raise
        self._connections, self._terminals = connections, terminals
        return self

    def summary(self):
        return {
            "components": [{"ref": item["ref"], "device": item["device"], "value": item["value"],
                            "x": item["x"], "y": item["y"], "pins": self.pins(item["ref"])} for item in self._parts],
            "connections": self.connections(), "terminals": self._terminals,
            "format": {"CDB": 5, "FILEVER": "814", "verified_application": "8.6 SP2 build 23525"},
        }

    def save(self, destination, title=None, *, overwrite=False, portable=True):
        """Save with verified adjacent firmware resources; move the whole folder to relocate."""
        from .resources import copy_verified
        if self._batch_depth: raise RuntimeError('Finish the batch before saving')
        if type(portable) is not bool: raise ValueError('portable must be a boolean')
        if type(overwrite) is not bool: raise ValueError('overwrite 必须是布尔值')
        destination = Path(destination).resolve()
        if destination==DEFAULT_TEMPLATE.resolve():raise ValueError('基础模板不能覆盖，请保存到 output 目录')
        if destination.suffix.lower()!='.pdsprj':raise UnsupportedFormat('Destination must be a .pdsprj file')
        if destination.exists() and not overwrite: raise UnsupportedFormat('Destination exists; pass overwrite=True to replace it: '+str(destination))
        if destination==self.source and hashlib.sha256(destination.read_bytes()).digest()!=self._source_digest:
            raise ValueError('工程已被其他程序修改，请重新打开')
        snapshot = {key: copy.deepcopy(value) for key,value in self.__dict__.items() if key != '_library_catalogue'}
        try:
            report = []
            if portable:
                with self.batch():
                    for part in self.components():
                        raw = part['properties'].get('PROGRAM')
                        if not raw: continue
                        if raw not in self._resources:
                            path = Path(raw)
                            path = path if path.is_absolute() else (self.source.parent if getattr(self, '_loaded', False) else Path.cwd()) / path
                            if path.is_file(): self.bind_firmware(part['ref'], path)
                for part in self.components():
                    raw = part['properties'].get('PROGRAM')
                    if raw in self._resources:
                        info = self._resources[raw]
                        target = copy_verified(info, destination.parent / raw)
                        report.append(dict(ref=part['ref'], relative=raw, sha256=info['sha256'], path=str(target)))
            result = self._save_file(destination, title, overwrite=overwrite)
            self.resource_report = report
            return result
        except BaseException:
            catalogue = self.__dict__.get('_library_catalogue')
            self.__dict__.clear(); self.__dict__.update(snapshot)
            if catalogue is not None: self._library_catalogue = catalogue
            raise

    def _save_file(self, destination, title=None, *, overwrite=False):
        if self._batch_depth:
            raise RuntimeError('Finish the batch before saving')
        destination = Path(destination).resolve()
        if type(overwrite) is not bool:
            raise ValueError("overwrite 必须是布尔值")
        if destination == DEFAULT_TEMPLATE.resolve():
            raise ValueError("基础模板不能覆盖，请保存到 output 目录")
        self.last_backup = None
        if destination.exists() and overwrite:
            if destination == self.source and hashlib.sha256(destination.read_bytes()).digest() != self._source_digest:
                raise ValueError("工程已被其他程序修改，请重新打开")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = destination.with_name(destination.name + ".backup-" + stamp + "-" + uuid.uuid4().hex[:8])
            with destination.open("rb") as source, backup.open("xb") as target:
                shutil.copyfileobj(source, target)
            if hashlib.sha256(backup.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
                raise IOError("备份校验失败，工程未覆盖")
            self.last_backup = backup
        return super().save(destination, title, overwrite=overwrite)


def _keys(item, allowed, label):
    if not isinstance(item, dict) or set(item) - set(allowed):
        raise ValueError(label + " 包含不支持的字段或不是对象")


def from_spec(spec, *, install=None, template_project=None, resource_base=None):
    """Compile a declarative JSON-compatible circuit into an editable Circuit."""
    _keys(spec, ("title", "units", "components", "connections", "terminals", "nets", "layout", "routing", "power_rails", "power_bindings"), "电路")
    unit = spec.get("units", "mm")
    if unit not in ("mm", "native"):
        raise ValueError("units 只能是 mm 或 native")
    def coord(value):
        if unit == "mm":
            return mm(value)
        if type(value) is not int:
            raise ValueError("native 坐标必须是整数")
        return value
    circuit = Circuit(template_project, install=install)
    if resource_base is not None: circuit._resource_base = Path(resource_base).resolve()
    circuit._title = spec.get("title", "Python schematic")
    with circuit.batch():
        routing = spec.get('routing', {})
        _keys(routing, ('clearance', 'lead', 'obstacles', 'avoid_labels'), '布线设置')
        if 'avoid_labels' in routing:
            if type(routing['avoid_labels']) is not bool:
                raise ValueError('avoid_labels 必须是布尔值')
            circuit.routing_options['avoid_labels'] = routing['avoid_labels']
        for key in ('clearance', 'lead'):
            if key in routing:
                circuit.routing_options[key] = coord(routing[key])
        if 'obstacles' in routing:
            circuit.routing_options['obstacles'] = [[coord(v) for v in bounds] for bounds in routing['obstacles']]
        for part in spec.get("components", []):
            _keys(part, ("device", "ref", "value", "x", "y", "rotation", "mirror_x", "mirror_y", "properties", "property_visibility", "library", "label_offsets"), "元件")
            options = {k: v for k, v in part.items() if k not in ("device", "ref", "value", "x", "y")}
            labels = options.pop("label_offsets", None)
            circuit.add(part["device"], part["ref"], part["value"], coord(part.get("x", 0)), coord(part.get("y", 0)), **options)
            if labels is not None:
                if not isinstance(labels, dict):
                    raise ValueError("label_offsets 必须是文字角色到坐标的映射")
                circuit.update(part["ref"], label_offsets={key: tuple(coord(v) for v in pair) for key, pair in labels.items()})
        groups = []
        for connection in spec.get("connections", []):
            groups.append(connection if isinstance(connection, list) else [connection['first'], connection['second']])
        groups += [net if isinstance(net, list) else net['pins'] for net in spec.get('nets', [])]
        layout = spec.get('layout', {})
        _keys(layout, ('auto', 'gap', 'fixed', 'fit_sheet', 'modules'), '布局设置')
        missing = [part['ref'] for part in spec.get('components', []) if 'x' not in part or 'y' not in part]
        fixed = []
        if layout.get('auto', bool(missing)):
            fixed = layout.get('fixed', [part['ref'] for part in spec['components'] if part['ref'] not in missing])
            from .layout import autoplace
            circuit.layout_report = autoplace(circuit, groups, gap=coord(layout.get('gap', 12.7 if unit == 'mm' else 1270000)), fixed=fixed)
        for connection in spec.get("connections", []):
            if isinstance(connection, list) and len(connection) == 2:
                circuit.connect(*connection)
            else:
                _keys(connection, ("first", "second", "points"), "连线")
                points = connection.get("points")
                if points is not None:
                    points = [(coord(x), coord(y)) for x, y in points]
                circuit.connect(connection["first"], connection["second"], points=points)
        for net in spec.get('nets', []):
            if isinstance(net, list):
                circuit.connect_net(*net)
            else:
                _keys(net, ('pins', 'name'), '网络')
                circuit.connect_net(*net['pins'], name=net.get('name'))
        for terminal in spec.get("terminals", []):
            _keys(terminal, ("kind", "name", "pin", "position", "rotation"), "端子")
            terminal = dict(terminal)
            if terminal.get("position") is not None:
                terminal["position"] = tuple(coord(v) for v in terminal["position"])
            circuit.add_terminal(**terminal)
        circuit.arrange_terminals()
        if 'power_rails' in spec:
            circuit.configure_power(spec['power_rails'], spec.get('power_bindings'))
        if 'modules' in layout:circuit.arrange_modules(layout['modules'])
    if layout.get('fit_sheet', bool(missing)):
        circuit.fit_sheet(center=not fixed)
    return circuit
