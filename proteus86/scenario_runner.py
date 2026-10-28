"""Run native scenarios with shared I/O readback and durable partial reports."""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from .scenarios import timeline, evaluate_samples


def _write_report(path, report, *, first=False):
    """Publish complete JSON snapshots; readers never see a half-written file."""
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if first:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class _Cancelled(RuntimeError):
    pass


def run_scenario(sim,scenario,*,probes,until,sample_every=.02,max_timing_error=.003,
                 expected_sequences=None,expected_changes=None,expected_words=None,timeout=30,
                 progress=None,checkpoint_every=25):
    """Observe actual native time, without caching across frames.

    progress receives a fresh summary dict after each completed frame; returning
    False cancels and leaves the owned simulation paused. Other callback errors
    fail the run. KeyboardInterrupt persists partial evidence and is re-raised.
    Reports are checkpointed after input frames, the first frame, and every
    checkpoint_every frames. An unfinished/cancelled report can never pass.
    """
    from .api import Project
    from .interactions import CONTROLS
    from .simulation import reached_target,validate_duration
    if sim.bundle is None:raise ValueError('Scenarios require Simulation.open() and an isolated run bundle')
    if progress is not None and not callable(progress):raise TypeError('progress must be callable')
    if type(checkpoint_every) is not int or not 1<=checkpoint_every<=10000:
        raise ValueError('checkpoint_every must be an integer between 1 and 10000')
    validate_duration(sample_every,timeout,max_timing_error)
    frames=timeline(scenario,until,sample_every,tolerance=max_timing_error)
    refs=list(probes)
    evaluate_samples([],refs,expected_sequences=expected_sequences,expected_changes=expected_changes,expected_words=expected_words)
    parts={p['ref']:p for p in Project(sim.session.project).components()}
    for ref in refs:
        if ref not in parts or parts[ref]['device']!='LOGICPROBE':
            raise ValueError('Add/connect a LOGICPROBE before running: '+str(ref))
    for action in scenario.actions:
        ref=action['ref']
        if ref not in parts or parts[ref]['device'] not in CONTROLS:
            raise NotImplementedError('Native scenario control not verified: '+str(ref))
        if not all(parts[ref]['properties'].get(key) in tuple(map(str,range(10))) for key in ('INC','DEC')):
            raise ValueError('Call Circuit.bind_controls(), save and reopen: '+ref)
    destination=Path(sim.bundle['project']).parent/('scenario-'+uuid.uuid4().hex[:8]+'.json')
    started=time.monotonic()
    report=dict(backend='proteus_native_sdf',pid=sim.session.pid,passed=False,native_run_completed=False,
                actions=[],samples=[],runs=[],requested_actions=list(scenario.actions),
                sample_every=sample_every,max_timing_error=max_timing_error,
                coverage='sampled_states_only',offline_isa_executor_used=False,
                record=str(destination),status='running',frames_total=len(frames),frames_completed=0,
                native_sdf_exports=0,checkpoint_every=checkpoint_every,wall_seconds=0)
    _write_report(destination,report,first=True)

    def checkpoint():
        report['wall_seconds']=time.monotonic()-started
        _write_report(destination,report)

    try:
        state=sim.status()
        if state['state']=='running':state=sim.pause()
        if state['state']!='paused':state=sim.run_for(1e-6,timeout=timeout,tolerance=max_timing_error)
        base=state['simulation_seconds'];report['base_seconds']=base
        for frame in frames:
            target=base+frame['at'];current=sim.status()
            if current['state']!='paused' or current['simulation_seconds'] is None:
                raise RuntimeError('Scenario lost its paused native simulation state')
            gap=target-current['simulation_seconds']
            if gap>max(current.get('time_resolution_seconds',0)/2,1e-9):
                duration=round(gap*1e6)/1e6
                if duration>0:report['runs'].append(sim.run_for(duration,timeout=timeout,tolerance=max_timing_error))
            current=sim.status()
            if current['state']!='paused' or not reached_target(current,target,max_timing_error):
                raise RuntimeError('Scenario could not meet a native simulation-time target: '+str(frame['at']))
            # A fresh preflight and one shared final readback if inputs change.
            io=sim.interact(controls={action['ref']:action['state'] for action in frame['actions']},
                            probes=refs if frame['sample'] else None)
            if abs(io['simulation_seconds']-current['simulation_seconds'])>1e-9:
                raise RuntimeError('Native simulation time changed during a scenario frame')
            report['native_sdf_exports']+=io['native_exports']
            for result in io['actions']:
                report['actions'].append(dict(result,requested_at=frame['at'],actual_at=result['command_time_seconds']-base))
            if frame['sample']:
                sample=io['observation']
                report['samples'].append(dict(sample,requested_at=frame['at'],actual_at=sample['simulation_seconds']-base))
            report['frames_completed']+=1
            report['last_native_seconds']=io['simulation_seconds']
            completed=report['frames_completed']
            if completed==1 or frame['actions'] or completed%checkpoint_every==0:
                checkpoint()
            if progress is not None:
                summary=dict(record=str(destination),status='running',frames_completed=completed,
                             frames_total=len(frames),samples_collected=len(report['samples']),
                             actions_completed=len(report['actions']),requested_at=frame['at'],
                             simulation_seconds=io['simulation_seconds'],actual_at=io['simulation_seconds']-base,
                             native_sdf_exports=report['native_sdf_exports'],wall_seconds=time.monotonic()-started)
                if progress(summary) is False:raise _Cancelled('Scenario cancelled by progress callback')
        report['native_run_completed']=True
        report['evaluation']=evaluate_samples(report['samples'],refs,expected_sequences=expected_sequences,
                                             expected_changes=expected_changes,expected_words=expected_words)
        report['diagnostics']=sim.diagnostics()
        report['passed']=report['evaluation']['passed'] and report['diagnostics']['passed']
        report['status']='completed' if report['passed'] else 'failed'
    except _Cancelled as error:
        report.update(status='cancelled',error=str(error))
    except (KeyboardInterrupt,SystemExit) as error:
        report.update(status='cancelled',error=type(error).__name__)
        raise
    except Exception as error:
        report.update(status='failed',error=type(error).__name__+': '+str(error))
        if hasattr(error,'native_action_attempts'):
            report['failed_frame_action_attempts']=error.native_action_attempts
        try:report['last_native_status']=sim.status()
        except Exception:pass
        try:report['diagnostics']=sim.diagnostics()
        except Exception as diagnostic_error:report['diagnostic_error']=str(diagnostic_error)
    finally:
        checkpoint()
    return report
