"""Harness-neutral allowlisted operations over the existing public APIs."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import uuid
import subprocess
import sys
import os
import tempfile
from contextlib import contextmanager

from .api import Circuit, Library, from_spec

# Explicit public surface: adding a core method requires reviewing its path and
# process effects here. capabilities() exposes signatures to either harness.
CIRCUIT_METHODS = frozenset('''add add_component add_mm move move_mm rotate mirror
update set_properties set_property_visibility rename copy_component delete_component
connect connect_net connect_bus disconnect set_route label_wire
add_terminal update_terminal delete_terminal set_terminal_label_position
configure_power bind_controls bind_firmware import_device import_from_project
autoplace arrange_labels arrange_modules translate_mm tidy_labels arrange_terminals
fit_sheet autoroute'''.split())
READ_METHODS = frozenset('''components pins connections nets terminals
terminal_label_position power_rails summary'''.split())
SIM_METHODS = frozenset('''status start pause stop reset controls control_state
press release set_switch observe interact run_for log_entries diagnostics log errors
load_firmware'''.split())
EDITOR_METHODS = frozenset(('menu', 'netlist', 'set_properties'))


class Operations:
    def __init__(self, workspace, output_root, *, native_root=None, allow_native=False):
        from .bridge import checked_root
        self.workspace = checked_root(workspace)
        self.output_root = checked_root(output_root)
        if not self.output_root.is_relative_to(self.workspace):
            raise ValueError('Output root must be inside the configured workspace')
        self.native_root = checked_root(native_root) if native_root is not None else None
        if self.native_root is not None and not str(self.native_root).isascii():
            raise ValueError('Native run root must be ASCII')
        self.allow_native = bool(allow_native)
        self.simulations, self.editors, self.jobs = {}, {}, {}

    def path(self, value, *, write=False, native=False, exists=False):
        from .bridge import checked_root
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError('A nonempty local path is required')
        root = self.native_root if native else self.output_root if write else self.workspace
        if root is None:
            raise ValueError('No native output root configured')
        raw = Path(value)
        if not write and not native and raw.is_absolute() and self.native_root is not None:
            if raw.is_relative_to(self.native_root):
                root = self.native_root
        target = (raw if raw.is_absolute() else root / raw).absolute()
        # Check lexical containment AND every existing ancestor before resolving.
        # This rejects links, junctions, traversal and alternate external roots.
        if '..' in target.parts or not target.is_relative_to(root):
            raise ValueError('Path is outside its configured root')
        for ancestor in (target, *target.parents):
            if ancestor.exists() or ancestor.is_symlink():
                if ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_reparse_tag', 0):
                    raise ValueError('Links and reparse points are not allowed')
        resolved = target.resolve()
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError('A child path below the configured root is required')
        if exists and not resolved.is_file():
            raise ValueError('Input must be an existing regular file')
        return resolved

    def programs(self, data):
        """Resolve explicit firmware assignments before the core can read them."""
        if isinstance(data, dict):
            return {key: str(self.path(value, exists=True))
                    if key == 'PROGRAM' and isinstance(value, str) and value
                    else self.programs(value) for key, value in data.items()}
        if isinstance(data, list):
            return [self.programs(item) for item in data]
        return data

    def open_project(self, source):
        path = self.path(source, exists=True)
        # A foreign PROGRAM must not become an implicit arbitrary file read on
        # save/package. Opening the project itself only decodes its known data.
        circuit = Circuit.open(path)
        for part in circuit.components():
            program = part['properties'].get('PROGRAM')
            if program:
                candidate = Path(program)
                self.path(candidate if candidate.is_absolute() else path.parent / candidate)
        return circuit

    def firmware(self, mapping):
        if mapping is None:
            return None
        if not isinstance(mapping, dict):
            raise ValueError('Firmware must map component references to local files')
        return {ref: str(self.path(path, exists=True)) for ref, path in mapping.items()}

    def capabilities(self):
        from .simulation import Simulation
        from .bridge import tool_catalog
        def signatures(cls, names):
            return {name: str(inspect.signature(getattr(cls, name))) for name in sorted(names)}
        return dict(version='0.2.0', platforms=['Codex', 'DeepSeek Harness'],
                    shared_contract=True,
                    contract_sha256=hashlib.sha256(json.dumps(tool_catalog(self.allow_native), sort_keys=True).encode()).hexdigest(),
                    workspace=str(self.workspace), output_root=str(self.output_root),
                    native_enabled=self.allow_native, native_root=str(self.native_root) if self.native_root else None,
                    file_actions=list(FILE_ACTIONS),
                    file_action_parameters={name: str(inspect.signature(getattr(self, '_file_' + name))) for name in FILE_ACTIONS},
                    native_action_parameters={name: str(inspect.signature(getattr(self, '_native_' + name))) for name in NATIVE_ACTIONS},
                    circuit_methods=signatures(Circuit, CIRCUIT_METHODS | READ_METHODS),
                    simulation_methods=signatures(Simulation, SIM_METHODS),
                    editor_methods=sorted(EDITOR_METHODS | {'save', 'export_netlist', 'close'}),
                    native_actions=list(NATIVE_ACTIONS),
                    semantics={'coordinates': 'add_mm/move_mm use mm; routes/terminal captions use native integers',
                               'native': 'explicit opt-in, fresh ASCII run bundles, exact process ownership',
                               'scope': 'Supported Proteus 8.6 API only; no arbitrary Python or shell execution'})

    def finish(self, circuit, destination, *, expected_nets, overwrite=False, title=None):
        from .inspection import netcheck
        from .geometry import wiringcheck
        from .quality import wire_quality
        project = self.path(destination, write=True)
        saved = circuit.save(project, title=title, overwrite=overwrite)
        reopened = Circuit.open(saved)
        topology = netcheck(saved, expected_nets) if expected_nets else None
        wiring = wiringcheck(saved)
        return dict(passed=wiring['passed'] and (topology is None or topology['passed']),
                    scope='Saved-file checks; no native execution', project=str(saved),
                    components=reopened.components(), netcheck=topology, topology_verified=topology is not None,
                    wiringcheck=wiring, wire_quality=wire_quality(saved),
                    backup=str(circuit.last_backup) if circuit.last_backup else None)

    def circuit_edit(self, *, source=None, destination, operations, expected_nets, overwrite=False, title=None):
        if not isinstance(operations, list) or not 1 <= len(operations) <= 1024:
            raise ValueError('Use 1..1024 structured public API operations')
        circuit = self.open_project(source) if source is not None else Circuit()
        results = []
        with circuit.batch():
            for operation in operations:
                if not isinstance(operation, dict) or set(operation) - {'method', 'args', 'kwargs'}:
                    raise ValueError('Operation accepts only method, args and kwargs')
                method = operation.get('method')
                if method not in CIRCUIT_METHODS | READ_METHODS:
                    raise ValueError('Circuit method is not exposed: ' + str(method))
                args = copy.deepcopy(operation.get('args', []))
                kwargs = self.programs(copy.deepcopy(operation.get('kwargs', {})))
                if not isinstance(args, list) or not isinstance(kwargs, dict):
                    raise ValueError('args must be an array and kwargs an object')
                if method == 'bind_firmware':
                    if len(args) > 1:
                        args[1] = self.path(args[1], exists=True)
                    elif 'path' in kwargs:
                        kwargs['path'] = self.path(kwargs['path'], exists=True)
                if method == 'import_from_project':
                    if args:
                        args[0] = self.path(args[0], exists=True)
                    elif 'project' in kwargs:
                        kwargs['project'] = self.path(kwargs['project'], exists=True)
                if kwargs.get('donor_project') is not None:
                    kwargs['donor_project'] = self.path(kwargs['donor_project'], exists=True)
                if kwargs.get('library') is not None and any(c in str(kwargs['library']) for c in ('/', '\\', ':')):
                    raise ValueError('Library must be an identity, not a path')
                value = getattr(circuit, method)(*args, **kwargs)
                if value is not circuit:
                    results.append(dict(method=method, result=value))
        report = self.finish(circuit, destination, expected_nets=expected_nets,
                             overwrite=overwrite, title=title)
        report['operation_results'] = results
        return report

    def project_action(self, action, params):
        if action not in FILE_ACTIONS:
            raise ValueError('Unknown file action: ' + str(action))
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        return getattr(self, '_file_' + action)(**params)

    def _file_inspect(self, project, geometry=True):
        from .inspection import inspect_project
        circuit = self.open_project(project)
        return inspect_project(circuit.source) if geometry else circuit.components()

    def _file_query(self, project, method, args=None, kwargs=None):
        if method not in READ_METHODS:
            raise ValueError('Unknown read-only Circuit query')
        return getattr(self.open_project(project), method)(*(args or []), **(kwargs or {}))

    def _file_build(self, spec, destination, expected_nets=None, overwrite=False):
        circuit = from_spec(self.programs(spec), resource_base=self.workspace)
        return self.finish(circuit, destination, expected_nets=expected_nets, overwrite=overwrite)

    def _file_generate(self, design, destination, expected_nets=None, overwrite=False, place=True, route=True):
        from .design import from_design, parse_design
        parsed = parse_design(design)
        circuit = from_design(parsed, place=place, route=route, resource_base=self.workspace)
        return self.finish(circuit, destination, expected_nets=expected_nets or parsed['nets'], overwrite=overwrite)

    def _file_search(self, query, limit=20):
        return Library().search(query, limit)

    def _file_doctor(self):
        from . import __version__
        from .installation import Installation, DEFAULT_TEMPLATE
        from .diagnostics import diagnose_project
        install = Installation.discover()
        return dict(tool_version=__version__, installation=str(install.home),
                    executable=str(install.executable), template=str(DEFAULT_TEMPLATE),
                    diagnostic=diagnose_project(DEFAULT_TEMPLATE), file_codec_ready=True)

    def _file_check(self, spec):
        return from_spec(self.programs(spec), resource_base=self.workspace).summary()

    def _file_demo(self, example, destination):
        if example not in ('rc', 'led', 'mcu'):
            raise ValueError('Unknown bundled demo')
        spec = json.loads((Path(__file__).parent / 'examples' / (example + '.json')).read_text(encoding='utf-8'))
        return self._file_build(spec, destination)

    def _file_autoplace(self, design, destination):
        from .design import parse_design, from_design, format_layout
        parsed = parse_design(design)
        circuit = from_design(parsed, route=False, resource_base=self.workspace)
        target = self.path(destination, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(format_layout(circuit, parsed))
        return dict(layout=str(target), placements=circuit.layout_report)

    def _file_place(self, design, destination, overwrite=False):
        return self._file_generate(design, destination, overwrite=overwrite, route=False)

    def _file_route(self, project, destination, nets, replace=False, overwrite=False):
        from .design import route_file
        from .inspection import netcheck
        circuit = self.open_project(project)
        saved = route_file(circuit.source, self.path(destination, write=True), nets,
                           replace=replace, overwrite=overwrite)
        return dict(project=str(saved), netcheck=netcheck(saved, nets))

    def _file_device(self, name, library=None):
        if any(c in str(library or '') for c in ('/', '\\', ':')):
            raise ValueError('Library must be an identity, not a path')
        return Library().get(name, library)

    def _file_diagnose(self, project):
        from .diagnostics import diagnose_project
        return diagnose_project(self.path(project, exists=True))

    def _file_netcheck(self, project, expected_nets):
        from .inspection import netcheck
        return netcheck(self.path(project, exists=True), expected_nets)

    def _file_wiringcheck(self, project):
        from .geometry import wiringcheck
        return wiringcheck(self.path(project, exists=True))

    def _file_wire_quality(self, project, min_gap_mm=2.54, min_parallel_mm=2.54):
        from .quality import wire_quality
        return wire_quality(self.path(project, exists=True), min_gap_mm=min_gap_mm, min_parallel_mm=min_parallel_mm)

    def _file_render(self, project, destination):
        from .preview import render
        destination = self.path(destination, write=True)
        if destination.exists():
            raise FileExistsError('Preview output already exists')
        return {'preview': str(render(self.path(project, exists=True), destination))}

    def _file_firmware_info(self, firmware):
        from .firmware import firmware_info
        return firmware_info(self.path(firmware, exists=True))

    def _file_package(self, project, destination, firmware=None):
        from .firmware import prepare_run
        circuit = self.open_project(project)
        return prepare_run(circuit.source, self.path(destination, write=True), firmware=self.firmware(firmware))

    def _file_prepare_control_batches(self, project, destination, controls=None, batch_size=5):
        from .digital import prepare_control_batches
        circuit = self.open_project(project)
        return prepare_control_batches(circuit.source, self.path(destination, write=True),
                                       controls=controls, batch_size=batch_size)

    def _file_pincheck(self, project):
        from .repair import check_pin_order
        return check_pin_order(self.path(project, exists=True))

    def _file_fix_pins(self, project, destination):
        from .repair import fix_pin_order
        return {'project': str(fix_pin_order(self.path(project, exists=True), self.path(destination, write=True)))}

    def _file_convert_net(self, text, destination, device_field='PARTTYPE', device_map=None):
        from .netlist import protel_to_design
        target = self.path(destination, write=True)
        result = protel_to_design(text, device_field=device_field, device_map=device_map)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(result)
        return {'design': result, 'path': str(target)}

    def _file_matrix_example(self, destination, probes=False, firmware=None):
        from .support import helper
        generate = helper('examples.draw_matrix_display').generate
        return generate(self.path(destination, write=True), probes=probes,
                        firmware=self.path(firmware, exists=True) if firmware else None)

    def _file_matrix_prepare(self, destination):
        from .support import helper
        verify = helper('scripts.verify_matrix_display').verify
        return verify(self.path(destination, write=True))

    def native_action(self, action, params):
        if not self.allow_native or self.native_root is None:
            raise ValueError('Native operations require startup --allow-native and an ASCII --native-root')
        if not isinstance(params, dict):
            raise ValueError('params must be an object')
        function = getattr(self, '_native_' + str(action), None) if action in NATIVE_ACTIONS else None
        if function is None:
            raise ValueError('Unknown native action')
        with self.native_environment():
            return function(**params)

    @contextmanager
    def native_environment(self):
        """PDS must inherit ASCII TEMP/TMP, not merely an ASCII project path."""
        from .bridge import checked_root
        directory = self.native_root / 'runtime-tmp'
        directory.mkdir(exist_ok=True)
        checked_root(directory)
        previous = {key: os.environ.get(key) for key in ('TEMP', 'TMP')}
        cached = tempfile.tempdir
        try:
            os.environ.update(TEMP=str(directory), TMP=str(directory))
            tempfile.tempdir = None
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            tempfile.tempdir = cached

    def _native_open(self, project, name, firmware=None):
        from .simulation import Simulation
        circuit = self.open_project(project)
        destination = self.path(name, native=True)
        sim = Simulation.open(circuit.source, destination, firmware=self.firmware(firmware))
        handle = uuid.uuid4().hex
        self.simulations[handle] = sim
        return dict(handle=handle, owned_pid=sim.session.pid, bundle=sim.bundle, status=sim.status())

    def simulation(self, handle):
        if handle not in self.simulations:
            raise ValueError('Unknown owned simulation handle')
        return self.simulations[handle]

    def _native_call(self, handle, method, args=None, kwargs=None):
        if method not in SIM_METHODS:
            raise ValueError('Unknown simulation method')
        args, kwargs = copy.deepcopy(args or []), copy.deepcopy(kwargs or {})
        if method == 'load_firmware':
            if len(args) > 1:
                args[1] = self.path(args[1], exists=True)
            elif 'path' in kwargs:
                kwargs['path'] = self.path(kwargs['path'], exists=True)
        return getattr(self.simulation(handle), method)(*args, **kwargs)

    def _native_scenario(self, handle, actions, **options):
        from .scenarios import Scenario
        scenario = Scenario()
        for entry in actions:
            if not isinstance(entry, dict) or set(entry) - {'method', 'args', 'kwargs'}:
                raise ValueError('Scenario entry accepts method, args and kwargs')
            if entry.get('method') not in ('set', 'press', 'release', 'hold', 'bounce'):
                raise ValueError('Unknown scenario action')
            getattr(scenario, entry['method'])(*entry.get('args', []), **entry.get('kwargs', {}))
        if 'progress' in options:
            raise ValueError('Python callbacks cannot be supplied over JSON')
        return self.simulation(handle).run_scenario(scenario, **options)

    def _native_display(self, handle, **options):
        from .digital import read_display_frame
        return read_display_frame(self.simulation(handle), **options)

    def _native_capture(self, handle, destination, **options):
        return self.simulation(handle).capture(self.path(destination, write=True), **options)

    def _native_close(self, handle):
        sim = self.simulation(handle)
        sim.close()
        closed = sim.session.process.poll() is not None
        if closed:
            del self.simulations[handle]
        return dict(closed=closed, owned_pid=sim.session.pid)

    def _native_editor_open(self, project, name, firmware=None):
        from .firmware import prepare_run
        from .session import Session
        circuit = self.open_project(project)
        bundle = prepare_run(circuit.source, self.path(name, native=True), firmware=self.firmware(firmware))
        session = Session(bundle['project'])
        handle = uuid.uuid4().hex
        self.editors[handle] = session
        return dict(handle=handle, owned_pid=session.pid, bundle=bundle)

    def editor(self, handle):
        if handle not in self.editors:
            raise ValueError('Unknown owned editor handle')
        return self.editors[handle]

    def _native_editor_save(self, handle):
        return {'saved': str(self.editor(handle).save())}

    def _native_editor_export(self, handle, destination):
        return self.editor(handle).export_netlist(self.path(destination, write=True))

    def _native_editor_close(self, handle):
        session = self.editor(handle)
        session.close()
        closed = session.process.poll() is not None
        if closed:
            del self.editors[handle]
        return dict(closed=closed, owned_pid=session.pid)

    def _native_editor_call(self, handle, method, args=None, kwargs=None):
        if method not in EDITOR_METHODS:
            raise ValueError('Unknown owned editor method')
        return getattr(self.editor(handle), method)(*(args or []), **self.programs(kwargs or {}))

    def _native_matrix_verify(self, destination, name, capture=False):
        from .support import helper
        verify = helper('scripts.verify_matrix_display').verify
        return verify(self.path(destination, write=True), execute_native=True,
                      temp_dir=self.path(name, native=True), capture=capture)

    def _submit_job(self, output, data):
        identifier = uuid.uuid4().hex
        directory = self.native_root / ('job-' + identifier)
        directory.mkdir()
        request = dict(workspace=str(self.workspace), output_root=str(self.output_root),
                       native_root=str(self.native_root), destination=str(output),
                       parent_pid=__import__('os').getpid(), **data)
        request_path = directory / 'request.json'
        request_path.write_text(json.dumps(request), encoding='utf-8')
        with (directory / 'stdout.log').open('wb') as stdout, (directory / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen([sys.executable, '-m', 'proteus86.bridge_jobs', str(request_path)],
                                       cwd=Path(__file__).resolve().parents[1], stdout=stdout, stderr=stderr,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.jobs[identifier] = dict(process=process, directory=directory, result=output / 'result.json')
        return dict(job=identifier, state='submitted', passed=False, worker_pid=process.pid,
                    result=str(output / 'result.json'),
                    next='Use native_action job_wait with seconds <= 30 until the worker exits. Submitted is not passed.')

    def _native_matrix_submit(self, destination, name, capture=False):
        output = self.path(destination, write=True)
        temporary = self.path(name, native=True)
        if output.exists() or temporary.exists():
            raise FileExistsError('Use fresh file and native directories')
        return self._submit_job(output, dict(kind='matrix', name=str(temporary), capture=capture))

    def _native_recipe_submit(self, destination, steps):
        output = self.path(destination, write=True)
        if output.exists():
            raise FileExistsError('Use a fresh recipe output directory')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
            raise ValueError('Recipe requires 1..64 structured native steps')
        allowed = set(NATIVE_ACTIONS) - {'matrix_verify', 'matrix_submit', 'recipe_submit',
                                        'job_status', 'job_wait', 'job_cancel'}
        for step in steps:
            if not isinstance(step, dict) or set(step) - {'action', 'params', 'as'} or step.get('action') not in allowed:
                raise ValueError('Recipe contains an unknown or recursive action')
        return self._submit_job(output, dict(kind='recipe', steps=steps))

    def _native_job_status(self, job):
        if job not in self.jobs:
            raise ValueError('Unknown owned job')
        entry = self.jobs[job]
        code = entry['process'].poll()
        report = {}
        if entry['result'].is_file():
            report = json.loads(entry['result'].read_text(encoding='utf-8'))
        passed = code == 0 and report.get('passed') is True and report.get('native_run_completed') is True
        progress = report.get('case_progress', [])
        return dict(job=job, state='running' if code is None else 'completed' if passed else 'failed',
                    passed=passed, returncode=code, result=str(entry['result']),
                    status=report.get('status'), phase=(report.get('stages') or [{}])[-1].get('phase'),
                    progress=progress[-1].get('summary') if progress else None,
                    error=report.get('error'), simulation_executed=report.get('simulation_executed', False))

    def _native_job_wait(self, job, seconds=30):
        if type(seconds) not in (int, float) or not 0 <= seconds <= 30:
            raise ValueError('Wait duration must be between 0 and 30 seconds')
        if job not in self.jobs:
            raise ValueError('Unknown owned job')
        try:
            self.jobs[job]['process'].wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            pass
        return self._native_job_status(job)

    def _native_job_cancel(self, job):
        if job not in self.jobs:
            raise ValueError('Unknown owned job')
        (self.jobs[job]['directory'] / 'cancel').touch()
        return self._native_job_status(job)

    def close(self):
        failures = []
        for handle, job in list(self.jobs.items()):
            try:
                if job['process'].poll() is None:
                    (job['directory'] / 'cancel').touch()
                    job['process'].wait(timeout=45)
                del self.jobs[handle]
            except BaseException as error:
                failures.append({'job': handle, 'error': str(error)})
        for collection in (self.simulations, self.editors):
            for handle, owned in list(collection.items()):
                try:
                    owned.close()
                    session = owned.session if hasattr(owned, 'session') else owned
                    if session.process.poll() is None:
                        raise RuntimeError('Owned process did not close')
                    del collection[handle]
                except BaseException as error:
                    evidence = {'handle': handle, 'error': str(error)}
                    # Keep the operation failed. As a last resort terminate
                    # only the exact Popen retained by this owned context.
                    session = owned.session if hasattr(owned, 'session') else owned
                    process = getattr(session, 'process', None)
                    if process is not None:
                        try:
                            if process.poll() is None:
                                process.terminate()
                                process.wait(timeout=5)
                                evidence['forced_owned_termination'] = True
                            evidence['process_closed'] = process.poll() is not None
                        except BaseException as cleanup_error:
                            evidence['cleanup_error'] = str(cleanup_error)
                    failures.append(evidence)
        if failures:
            raise RuntimeError('Owned process cleanup failed: ' + json.dumps(failures))


FILE_ACTIONS = ('doctor', 'generate', 'build', 'check', 'demo', 'autoplace', 'place', 'route',
                'inspect', 'query', 'search', 'device', 'diagnose',
                'netcheck', 'wiringcheck', 'wire_quality', 'render', 'firmware_info', 'package',
                'prepare_control_batches', 'pincheck', 'fix_pins', 'convert_net', 'matrix_example', 'matrix_prepare')
NATIVE_ACTIONS = ('open', 'call', 'scenario', 'display', 'capture', 'close', 'editor_open',
                  'editor_save', 'editor_export', 'editor_close', 'editor_call', 'matrix_verify',
                  'matrix_submit', 'recipe_submit', 'job_status', 'job_wait', 'job_cancel')
