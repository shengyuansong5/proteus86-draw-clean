"""Owned asynchronous native worker; never accepts Python or shell source."""
import ctypes
import json
import os
from pathlib import Path
import sys


def parent_watch(pid):
    """Hold the exact parent process identity, so PID reuse cannot adopt it."""
    if os.name != 'nt':
        return lambda: os.getppid() == pid, lambda: None
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    api.OpenProcess.restype = w.HANDLE
    api.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
    api.WaitForSingleObject.restype = w.DWORD
    api.CloseHandle.argtypes = (w.HANDLE,)
    handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE, no write/terminate permission.
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return lambda: api.WaitForSingleObject(handle, 0) == 258, lambda: api.CloseHandle(handle)


def run(request_file):
    from .bridge_operations import Operations
    from .support import helper
    verify = helper('scripts.verify_matrix_display').verify
    request_file = Path(request_file).resolve(strict=True)
    data = json.loads(request_file.read_text(encoding='utf-8'))
    operations = Operations(data['workspace'], data['output_root'], native_root=data['native_root'], allow_native=True)
    alive, close_watch = parent_watch(data['parent_pid'])
    try:
        output = operations.path(data['destination'], write=True)
        if not request_file.parent.is_relative_to(operations.native_root):
            raise ValueError('Job request is outside the configured native root')
        progress = lambda update: alive() and not (request_file.parent / 'cancel').exists()
        if data.get('kind') == 'recipe':
            report = run_recipe(operations, output, data['steps'], progress)
        elif data.get('kind') == 'matrix':
            native = operations.path(data['name'], native=True)
            report = verify(output, execute_native=True, temp_dir=native, capture=data['capture'], progress=progress)
        else:
            raise ValueError('Unknown job kind')
        return 0 if report.get('passed') and report.get('native_run_completed') else 1
    finally:
        close_watch()
        operations.close()


def run_recipe(operations, output, steps, progress):
    from .scenario_runner import _write_report
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, status='running', scope='Structured owned native recipe',
                  native_run_completed=False, simulation_executed=False, steps=[])
    handles, failure = {}, None
    try:
        for step in steps:
            if not progress({}):
                raise RuntimeError('Recipe cancelled or owning bridge exited')
            params = dict(step.get('params', {}))
            handle = params.get('handle')
            if isinstance(handle, str) and handle.startswith('$'):
                params['handle'] = handles[handle[1:]]
            value = operations.native_action(step['action'], params)
            report['steps'].append(dict(action=step['action'], result=value))
            if isinstance(value, dict):
                if step.get('as') and 'handle' in value:
                    handles[step['as']] = value['handle']
                if value.get('simulation_seconds', 0):
                    report['simulation_executed'] = True
                if value.get('passed') is False or value.get('closed') is False:
                    raise RuntimeError('Native recipe step did not pass')
            _write_report(output / 'result.json', report)
        report.update(passed=True, status='completed', native_run_completed=True)
    except BaseException as error:
        failure = error
        report.update(passed=False, status='failed', error=repr(error))
    finally:
        try:
            operations.close()
            report['owned_processes_closed'] = True
        except BaseException as error:
            report.update(passed=False, status='failed', cleanup_error=repr(error), owned_processes_closed=False)
        _write_report(output / 'result.json', report)
    if failure is not None and not isinstance(failure, Exception):
        raise failure
    return report


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
