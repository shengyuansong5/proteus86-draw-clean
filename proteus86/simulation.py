"""Actual Proteus 8.6 simulation control, isolated to one owned Session."""
import json
import math
from pathlib import Path
import re
import time
import hashlib
from datetime import datetime,timezone

from .firmware import prepare_run


class SimulationError(RuntimeError):
    pass


def seconds(clock):
    if not re.fullmatch(r'\d+:\d{2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?s?',clock):raise ValueError('Invalid native simulation clock')
    if ':' in clock:
        h,m,s=map(float,clock.split(':'))
        if m>=60 or s>=60:raise ValueError('Invalid native simulation clock')
        value=h*3600+m*60+s
    else:value=float(clock.removesuffix('s'))
    if not math.isfinite(value):raise ValueError('Invalid native simulation clock')
    return value


def clock_resolution(clock):
    """Resolution of the displayed native clock; do not invent hidden precision."""
    seconds(clock)
    match=re.search(r'\.(\d+)',clock)
    return 10**-len(match[1]) if match else 1.0


def reached_target(state,target,tolerance):
    value=state.get('simulation_seconds')
    uncertainty=state.get('time_resolution_seconds',0)/2
    return value is not None and target-uncertainty-1e-9<=value<=target+tolerance+uncertainty+1e-9


def validate_duration(duration,timeout=30,tolerance=.003):
    duration=float(duration)
    if not math.isfinite(duration) or duration<1e-6 or abs(duration*1e6-round(duration*1e6))>1e-6:
        raise ValueError('Duration must be a positive integer number of microseconds')
    if not math.isfinite(timeout) or not 0<timeout<=300:raise ValueError('Timeout must be between 0 and 300 seconds')
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('Invalid timer tolerance')
    return duration


def classify_diagnostics(entries):
    def error(item):
        text=item['text']
        # This 8.6 log uses custom drawing: native image indexes are opaque,
        # not reliable severity codes. Known informational headers can contain
        # arbitrary project names such as "Error monitor".
        if re.match(r'^(?:PROSPICE |Loaded netlist |MCS8051 model version |Loading (?:HEX|ELF|BIN) file |Read total of \d+ bytes)',text):return False
        if re.search(r'\b(?:no|0) errors?\b',text,re.I):return False
        return bool(re.search(r'\b(error|fatal|failed|failure|exception|unable)\b|could not|cannot',text,re.I))
    errors=[item for item in entries if error(item)]
    warnings=[item for item in entries if re.search(r'\bwarning\b',item['text'],re.I)]
    return dict(entries=entries,errors=errors,warnings=warnings,passed=not errors)


class Simulation:
    def __init__(self,session):
        from .session import Session
        from .native_simulation import StatusReader
        if not isinstance(session,Session):raise TypeError('Simulation requires an owned proteus86 Session')
        self.session=session
        self.reader=StatusReader(session)
        self.bundle=None
        from .api import Project
        self._initial_bindings={p['ref']:{key:p['properties'].get(key) for key in ('INC','DEC','KEY')}
                                for p in Project(session.project).components()}

    @classmethod
    def open(cls,project,destination,*,firmware=None,install=None):
        from .session import Session, _cleanup_owned_startup
        bundle=prepare_run(project,destination,firmware=firmware)
        session=None
        try:
            session=Session(bundle['project'],install=install)
            result=cls(session);result.bundle=bundle
            return result
        except BaseException as error:
            _cleanup_owned_startup(session, error)
            raise

    def status(self):
        from ._codec import proteus_native as native
        code=self.session.process.poll()
        if code is not None:return dict(state='exited',returncode=code,simulation_seconds=None)
        window=self.session._ready()
        if not window:return dict(state='blocked',simulation_seconds=None,windows=native.windows(self.session.pid))
        text,reason=self.reader.text(window)
        match=re.fullmatch(r'(ANIMATING|PAUSED): ([\d.:]+s?)(?: \(CPU load \d+%\))?',text)
        if match:return dict(state='running' if match[1]=='ANIMATING' else 'paused',simulation_seconds=seconds(match[2]),time_resolution_seconds=clock_resolution(match[2]),status_text=text,reason=reason)
        menus={item['path']:item['enabled'] for item in native.menus(native.u.GetMenu(window['hwnd']))}
        stopped=text.startswith('Root sheet ') or ('VSM debugging session has ended' in text)
        if text and menus.get('Debug/Stop VSM Debugging') is False:stopped=True
        return dict(state='stopped' if stopped else 'initializing',simulation_seconds=None,status_text=text,reason=reason)

    def _wait(self,predicate,timeout=20):
        if not math.isfinite(timeout) or not 0<timeout<=300:raise ValueError('Timeout must be between 0 and 300 seconds')
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=self.status()
            if state['state'] in ('exited','blocked'):raise SimulationError(json.dumps(state))
            matched=predicate(state)
            if matched:return matched if isinstance(matched,dict) else state
            time.sleep(.05)
        raise TimeoutError('Proteus did not reach the expected simulation state: '+json.dumps(self.status()))

    def _command(self,path):
        from ._codec import proteus_native as native
        from .native_simulation import message
        window=self.session._wait(self.session._ready)
        items=[item for item in native.menus(native.u.GetMenu(window['hwnd'])) if item['path']==path]
        if len(items)!=1:raise SimulationError('Native simulation command missing: '+path)
        # The verified 8.6 status read is authoritative; menu enable bits may
        # lag at launch and after a timed breakpoint. Commands never use IDs
        # from another build, process, or old window snapshot.
        message(self.session.pid,window['hwnd'],0x111,items[0]['command_id'])

    def start(self,*,timeout=20):
        state=self._wait(lambda s:s['state'] in ('running','paused','stopped'),timeout)
        if state['state']=='running':return state
        self._command('Debug/Run Simulation')
        return self._wait(lambda s:s['state']=='running',timeout)

    def pause(self,*,timeout=20):
        validate_duration(1,timeout)
        state=self.status()
        if state['state']!='running':return state
        self._command('Debug/Pause VSM Debugging')
        return self._wait(lambda s:s['state'] in ('paused','stopped'),timeout)

    def stop(self,*,timeout=20):
        validate_duration(1,timeout)
        state=self.status()
        if state['state'] in ('stopped','exited'):return state
        self._command('Debug/Stop VSM Debugging')
        return self._wait(lambda s:s['state']=='stopped',timeout)

    def reset(self):
        """Stop; next start resets volatile state. Persistent device data remains."""
        return self.stop()

    def controls(self):
        from .interactions import paused,snapshot,control_row,CONTROLS
        with paused(self):
            data=snapshot(self)
            return [dict(ref=ref,device=part['device'],state=int(control_row(data,ref)['properties']['STATE']),
                         bound=all(part['properties'].get(key) is not None for key in ('INC','DEC')))
                    for ref,part in data['parts'].items() if part['device'] in CONTROLS]

    def control_state(self,ref):
        """Native actuator position, not downstream voltage."""
        from .interactions import paused,snapshot,control_row
        with paused(self):return int(control_row(snapshot(self),ref)['properties']['STATE'])

    def press(self,ref):
        from .interactions import set_control
        return set_control(self,ref,1)

    def release(self,ref):
        from .interactions import set_control
        return set_control(self,ref,0)

    def set_switch(self,ref,closed):
        if type(closed) is not bool:raise ValueError('closed must be True or False')
        from .interactions import set_control
        return set_control(self,ref,int(closed))

    def observe(self,probes):
        """Read connected LOGICPROBE states at a native paused simulation time."""
        from .interactions import observe
        return observe(self,probes)

    def interact(self,*,controls=None,probes=None):
        """Batch inputs and optional probe observations at one paused native time."""
        from .interactions import interact
        return interact(self,controls=controls,probes=probes)

    def run_scenario(self,scenario,**options):
        from .scenario_runner import run_scenario
        return run_scenario(self,scenario,**options)

    def _begin_timed(self,duration,*,timeout=30,tolerance=0.003):
        """Start the verified native timer without assuming animation advances."""
        from .native_simulation import message
        duration=validate_duration(duration,timeout,tolerance)
        before=self._wait(lambda s:s['state'] in ('running','paused','stopped'))
        if before['state']=='running':before=self.pause()
        start=before['simulation_seconds'] if before['state']=='paused' else 0
        self._command('Debug/Run Simulation (timed breakpoint)')
        dialog=self.session._dialog('Execute for specified time')
        edits=[row for row in dialog['children'] if row['cls']=='Edit' and row['control_id']==257]
        if len(edits)!=1:raise SimulationError('Unrecognized native timer control')
        text=format(duration,'.6f').rstrip('0').rstrip('.')
        message(self.session.pid,edits[0]['hwnd'],0xb1,0,-1)
        for char in text:message(self.session.pid,edits[0]['hwnd'],0x102,ord(char))
        import ctypes as c
        buffer=c.create_unicode_buffer(128)
        message(self.session.pid,edits[0]['hwnd'],0xd,128,c.addressof(buffer))
        if buffer.value!=text:raise SimulationError('Native timer value read-back mismatch')
        message(self.session.pid,dialog['hwnd'],0x111,1)
        self.session._wait(self.session._ready,timeout=15)
        return dict(before=before,start_seconds=start,requested_seconds=duration)

    def capture(self,destination,**options):
        """Capture an owned running window only after native time advances."""
        from .capture import capture_simulation
        return capture_simulation(self,destination,**options)

    def run_for(self,duration,*,timeout=30,tolerance=0.003):
        duration=validate_duration(duration,timeout,tolerance)
        begun=self._begin_timed(duration,timeout=timeout,tolerance=tolerance)
        start=begun["start_seconds"]
        target=start+duration
        last=None;repeated=0
        def reached(state):
            nonlocal last,repeated
            value=state['simulation_seconds']
            if value is None:return None
            if state['state']=='paused' and reached_target(state,target,tolerance):
                return dict(state,completion='timer_breakpoint' if state.get('reason','').startswith('Execution timer breakpoint:') else 'paused_at_target')
            if state['state']=='paused' and value>target+tolerance+state.get('time_resolution_seconds',0)/2+1e-9:
                raise SimulationError('Native timer exceeded the permitted simulation-time tolerance')
            if state['state']=='running' and reached_target(state,target,tolerance):
                repeated=repeated+1 if last==value else 1
                last=value
                if repeated>=4:
                    # The old engine can leave a tiny positive timer remainder
                    # at the reached target. Pause, then verify its actual native
                    # time again; UI lag or overshoot never counts as success.
                    paused=self.pause()
                    if paused['state']=='paused' and reached_target(paused,target,tolerance):
                        return dict(paused,completion='target_reached_pause')
            else:last=None;repeated=0
        result=self._wait(reached,timeout)
        if not reached_target(result,start+duration,tolerance):
            raise SimulationError('Native timer exceeded the permitted simulation-time tolerance')
        return dict(result,requested_seconds=duration,start_seconds=start,elapsed_seconds=result['simulation_seconds']-start,
                    timing_error_seconds=result['simulation_seconds']-target,tolerance_seconds=tolerance)

    def log_entries(self):
        from ._codec import proteus_native as native
        from .native_simulation import find_log_control,list_rows
        window=self.session._wait(self.session._ready)
        main=window['hwnd']
        def find():
            current=self.session._wait(self.session._ready)
            if current['hwnd']!=main:
                raise SimulationError('Owned Proteus main window changed during log read; reopen the session')
            return find_log_control(self.session,current)
        control=find_log_control(self.session,window)
        if control is None:
            menus=native.menus(native.u.GetMenu(window['hwnd']))
            path=None
            for candidate in ('Debug/1. Simulation Log','Graph/View Simulation Log'):
                matches=[item for item in menus if item['path']==candidate and item['enabled']]
                if len(matches)>1:raise SimulationError('Ambiguous native simulation log menu: '+candidate)
                if matches:path=candidate;break
            if path is None:raise SimulationError('Native simulation log is unavailable: no verified existing log control or enabled log menu')
            self._command(path)
            control=self.session._wait(find)
        def check_identity():
            current=find()
            if current is None or (current['hwnd'],current['log_profile'])!=(control['hwnd'],control['log_profile']):
                raise SimulationError('Native simulation log control changed during read; retry on the owned session')
        check_identity()
        entries=list_rows(self.session.pid,control['hwnd'])
        check_identity()
        return entries

    def diagnostics(self):
        return classify_diagnostics(self.log_entries())

    def log(self):
        """Read native log text without using or replacing the clipboard."""
        return '\n'.join(item['text']+('\t'+item['source'] if item['source'] else '') for item in self.log_entries())

    def errors(self):
        return self.diagnostics()['errors']

    def load_firmware(self,ref,path):
        """Stop and reload a checked image into this isolated run bundle."""
        from .api import Circuit
        if self.bundle is None:raise ValueError('Reload requires Simulation.open() and an isolated bundle')
        circuit=Circuit.open(self.session.project)
        if ref not in {part['ref'] for part in circuit.components()}:raise KeyError(ref)
        _,info=circuit._firmware_binding(ref,path)
        relative=Path('firmware')/(ref+'-'+info['sha256'][:12]+'.'+info['format'])
        target=self.session.project.parent/relative
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=info['sha256']:raise RuntimeError('Run image name collision')
        else:
            with target.open('xb') as out:out.write(Path(info['path']).read_bytes())
        if hashlib.sha256(target.read_bytes()).hexdigest()!=info['sha256']:raise RuntimeError('Firmware changed while loading')
        self.stop()
        self.session.set_properties(ref,PROGRAM=str(relative))
        self.session.save()
        result=dict(info,ref=ref,run_path=str(target),state='stopped')
        # bundle.json is the immutable initial input manifest. Record subsequent
        # image changes separately so an experiment can be reproduced/audited.
        history=self.session.project.parent/'firmware-history.jsonl'
        with history.open('a',encoding='utf-8') as out:out.write(json.dumps(result,ensure_ascii=False)+'\n')
        return result

    def close(self):
        if self.session.process.poll() is not None:return
        try:
            self.stop();self.session.close()
        finally:
            if self.session.process.poll() is None:
                self.session.process.terminate();self.session.process.wait(timeout=5)

    def __enter__(self):return self
    def __exit__(self,kind,error,traceback):
        try:self.close()
        except Exception:
            if kind is None:raise


def simulate(project,destination,*,duration=1,firmware=None,timeout=30,install=None):
    """Run one native timed experiment, always preserving its report and source.

    Preflight errors raise before launch. Native failures return passed=False
    with available diagnostics, and this experiment's process is cleaned up.
    """
    duration=validate_duration(duration,timeout)
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    report=dict(passed=False,requested_seconds=duration,recorded_utc=datetime.now(timezone.utc).isoformat())
    sim=None
    try:
        sim=Simulation.open(project,destination,firmware=firmware,install=install)
        report.update(pid=sim.session.pid,bundle=sim.bundle)
        report['completion']=sim.run_for(duration,timeout=timeout)
        report['diagnostics']=sim.diagnostics()
        report['passed']=report['diagnostics']['passed']
    except Exception as error:
        if not destination.exists():raise
        report['error']=str(error)
        if sim is not None:
            try:report['diagnostics']=sim.diagnostics()
            except Exception as log_error:report['log_error']=str(log_error)
    finally:
        if sim is not None:
            try:sim.close()
            except Exception as error:report.update(passed=False,cleanup_error=str(error))
            report['process_closed']=sim.session.process.poll() is not None
    if not report.get('process_closed',True):report['passed']=False
    bundle=json.loads((destination/'bundle.json').read_text(encoding='utf-8'))
    report['source_unchanged']=hashlib.sha256(Path(bundle['source']).read_bytes()).hexdigest()==bundle['source_sha256']
    if not report['source_unchanged']:report['passed']=False
    if 'diagnostics' in report:
        with (destination/'simulation.log').open('x',encoding='utf-8') as out:
            out.write('\n'.join(row['text']+('\t'+row['source'] if row['source'] else '') for row in report['diagnostics']['entries'])+'\n')
    with (destination/'result.json').open('x',encoding='utf-8') as out:json.dump(report,out,ensure_ascii=False,indent=2)
    return report
