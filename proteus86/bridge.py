"""Shared Codex/DSH structured API and stdio MCP transport.

Only explicitly listed Proteus APIs are callable. Files are scoped to configured
roots; native operation is opt-in and owns only processes opened by this server.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import uuid

CHECKOUT = Path(__file__).resolve().parents[1]
if str(CHECKOUT) not in sys.path:
    sys.path.insert(0, str(CHECKOUT))

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
TOOL = {
    'name': 'draw_circuit',
    'description': ('Generate a fresh editable Proteus saved-file circuit from '
                    '[parts]/[terms]/[nets] text, reopen and netcheck it, audit '
                    'wiring and render SVG. File checks only; no simulation. '
                    'Outputs stay under the configured output root; no overwrite.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False,
                    'required': ['name', 'design'], 'properties': {
                        'name': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'},
                        'design': {'type': 'string', 'maxLength': 65536}}},
}


def checked_root(directory):
    """Reject existing links/junctions before resolving the fixed output root."""
    root = Path(directory).absolute()
    for item in [*reversed(root.parents), root]:
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if item.is_symlink() or getattr(info, 'st_reparse_tag', 0):
                raise ValueError('Output root must not traverse links or reparse points')
    if not root.is_dir():
        raise ValueError('Configure an existing dedicated output directory')
    return root.resolve()


def validate_arguments(arguments):
    from proteus86.design import parse_design
    if not isinstance(arguments, dict) or set(arguments) != {'name', 'design'}:
        raise ValueError('Only name and design arguments are accepted')
    name, text = arguments['name'], arguments['design']
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('Use a simple ASCII project name, without paths')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                     *(f'COM{i}' for i in range(1, 10)),
                                     *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('Reserved Windows project name')
    if not isinstance(text, str) or not 0 < len(text.encode('utf-8')) <= 65536:
        raise ValueError('Design must contain 1..65536 UTF-8 bytes')
    design = parse_design(text)
    if not 1 <= len(design['parts']) <= 64 or len(design['nets']) > 256:
        raise ValueError('Bridge supports 1..64 parts and at most 256 nets')
    # Text designs expose only placement/library options, never PROGRAM or
    # arbitrary properties. Library identities must not become filesystem paths.
    for part in design['parts']:
        for key in ('device', 'library'):
            value = part.get(key, '')
            if any(c in value for c in ('/', '\\', ':')) or '..' in value:
                raise ValueError('Device/library identity must not be a file path')
    return name, text, design


def draw_circuit(root, arguments):
    from proteus86 import Circuit
    from proteus86.design import from_design
    from proteus86.geometry import wiringcheck
    from proteus86.inspection import netcheck
    from proteus86.preview import render
    from proteus86.quality import wire_quality
    name, text, design = validate_arguments(arguments)
    root = checked_root(root)
    destination = root / name
    # An atomic fresh directory creation rejects collisions, including links.
    destination.mkdir()
    try:
        (destination / 'design.txt').write_text(text, encoding='utf-8')
        circuit = from_design(design, resource_base=destination)
        project = destination / 'circuit.pdsprj'
        circuit.save(project)
        reopened = Circuit.open(project)
        topology = netcheck(project, design['nets'])
        wiring = wiringcheck(project)
        quality = wire_quality(project)
        preview = render(project, destination / 'preview.svg')
        result = {
            'passed': topology['passed'] and wiring['passed'],
            'scope': 'Saved files and drawing only; no native editor or simulation',
            'project': str(project), 'preview': str(preview),
            'components': reopened.components(),
            'netcheck': topology, 'wiringcheck': wiring, 'wire_quality': quality,
        }
        (destination / 'checks.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    except BaseException as error:
        # Keep partial artifacts but do not mask cancellation with report I/O.
        try:
            (destination / 'failed.json').write_text(json.dumps({
                'passed': False, 'error': type(error).__name__, 'message': str(error)
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass
        raise


def dispatch(root, request):
    if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
        return {'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32600, 'message': 'Invalid JSON-RPC request'}}
    if 'id' not in request:
        return None
    from .bridge_operations import Operations
    operations = root if isinstance(root, Operations) else Operations(root, root)
    reply = {'jsonrpc': '2.0', 'id': request['id']}
    method, params = request.get('method'), request.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion': '2025-03-26',
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'proteus86-file-bridge', 'version': '0.2.0'},
                  'instructions': ('Shared Codex/DSH Proteus API. Call capabilities first for methods, '
                                   'signatures, workspace/output scope and native opt-in state. '
                                   'Use structured operations, never Python or shell code. '
                                   'File checks are not native simulation evidence.')}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': tool_catalog(operations.allow_native)}
    elif method == 'tools/call':
        try:
            if not isinstance(params, dict):
                raise ValueError('Unknown tool')
            tool, arguments = params.get('name'), params.get('arguments', {})
            if not isinstance(arguments, dict):
                raise ValueError('Tool arguments must be an object')
            if tool == TOOL['name']:
                value = draw_circuit(operations.output_root, arguments)
            elif tool == 'capabilities' and not arguments:
                value = operations.capabilities()
            elif tool == 'project_action':
                value = operations.project_action(**arguments)
            elif tool == 'circuit_edit':
                value = operations.circuit_edit(**arguments)
            elif tool == 'native_action':
                value = operations.native_action(**arguments)
            else:
                raise ValueError('Unknown tool')
            result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False, default=str)}],
                      'isError': isinstance(value, dict) and value.get('passed') is False}
        except Exception as error:
            evidence = {name: getattr(error, name) for name in
                        ('owned_pid', 'process_closed', 'owned_startup_cleanup', 'owned_cleanup_error',
                         'report', 'digital_report') if hasattr(error, name)}
            result = {'isError': True, 'content': [{'type': 'text',
                      'text': json.dumps(dict(passed=False, error=type(error).__name__, message=str(error),
                                              evidence=evidence), ensure_ascii=False, default=str)}]}
    else:
        reply['error'] = {'code': -32601, 'message': 'Method not found'}
        return reply
    reply['result'] = result
    return reply


def serve(root, source, sink):
    from .bridge_operations import Operations
    operations = root if isinstance(root, Operations) else Operations(root, root)
    for line in source:
        try:
            if len(line.encode('utf-8')) > 131072:
                raise ValueError('Request too large')
            request = json.loads(line)
        except (ValueError, UnicodeError):
            reply = {'jsonrpc': '2.0', 'id': None,
                     'error': {'code': -32700, 'message': 'Invalid or oversized JSON'}}
        else:
            reply = dispatch(operations, request)
        if reply is not None:
            sink.write(json.dumps(reply, ensure_ascii=False) + '\n')
            sink.flush()


def tool_catalog(allow_native=False):
    from .bridge_operations import FILE_ACTIONS, NATIVE_ACTIONS, CIRCUIT_METHODS, READ_METHODS
    def tool(name, description, properties, required):
        return dict(name=name, description=description,
                    inputSchema=dict(type='object', properties=properties,
                                     required=required, additionalProperties=False))
    arbitrary = {'type': 'object'}
    methods = sorted(CIRCUIT_METHODS | READ_METHODS)
    tools = [TOOL,
             tool('capabilities', 'Shared API, method signatures and configured boundaries for either platform.', {}, []),
             tool('project_action', 'Use existing core file/library/firmware/batching/example functions; no native launch.',
                  {'action': {'type': 'string', 'enum': list(FILE_ACTIONS)}, 'params': arbitrary}, ['action', 'params']),
             tool('circuit_edit', 'Batch public Circuit edits, save with checked backup if explicitly overwriting, reopen and check.',
                  {'source': {'type': 'string'}, 'destination': {'type': 'string'},
                   'expected_nets': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}},
                   'operations': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                       'required': ['method'], 'properties': {'method': {'type': 'string', 'enum': methods},
                                                           'args': {'type': 'array'}, 'kwargs': arbitrary}}},
                   'overwrite': {'type': 'boolean'}, 'title': {'type': 'string'}},
                  ['destination', 'operations', 'expected_nets'])]
    if allow_native:
        tools.append(tool('native_action',
                          'Opt-in owned native sessions: editor save/SDF, actual simulation time, controls, scenarios, '
                          'display reconstruction, running capture and sequential matrix acceptance. '
                          'Use matrix_submit/recipe_submit plus job_wait for long tasks. Close owned handles.',
                          {'action': {'type': 'string', 'enum': list(NATIVE_ACTIONS)}, 'params': arbitrary},
                          ['action', 'params']))
    return tools


def main():
    from .bridge_operations import Operations
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--native-root', type=Path)
    parser.add_argument('--allow-native', action='store_true')
    parser.add_argument('--request', type=Path, help='Execute one JSON-RPC request locally, using the same dispatcher as MCP')
    args = parser.parse_args()
    # MCP wire I/O is UTF-8 even under a legacy Windows console code page.
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    operations = Operations(args.workspace or args.output_root, args.output_root,
                            native_root=args.native_root, allow_native=args.allow_native)
    original = None
    try:
        if args.request:
            request_path = operations.path(args.request, exists=True)
            result = dispatch(operations, json.loads(request_path.read_text(encoding='utf-8-sig')))
            print(json.dumps(result, ensure_ascii=False, default=str))
        else:
            serve(operations, sys.stdin, sys.stdout)
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            operations.close()
        except BaseException as error:
            if original is None:
                raise
            original.bridge_cleanup_error = str(error)


if __name__ == '__main__':
    main()
