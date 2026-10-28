"""Native control read-back and digital observations through Proteus's own SDF exporter.

No simulator structures are patched or scanned. Commands target only an owned PID.
Runtime STATE observations were verified using BUTTON, LOGICSTATE and LOGICPROBE.
"""
from contextlib import contextmanager
from collections.abc import Mapping
import re

CONTROLS=frozenset({'BUTTON','LOGICSTATE'})


@contextmanager
def paused(sim):
    state=sim.status()
    if state['state'] not in ('running','paused'):
        raise RuntimeError('Initialize/run the simulation before reading or operating controls')
    running=state['state']=='running'
    if running:sim.pause()
    try:yield
    finally:
        if running and sim.status()['state']=='paused':sim.start()


def snapshot(sim):
    before=sim.status()
    if before['state']!='paused' or before['simulation_seconds'] is None:
        raise RuntimeError('Native SDF observations require a verified paused time')
    netlist=sim.session.netlist()
    after=sim.status()
    if after['state']!='paused' or before['simulation_seconds']!=after['simulation_seconds']:
        raise RuntimeError('Native simulation time changed during SDF observation')
    return dict(backend='proteus_native_sdf',simulation_seconds=after['simulation_seconds'],
                time_resolution_seconds=after.get('time_resolution_seconds'),parts=netlist['parts'])


def control_row(data,ref):
    if ref not in data['parts']:raise KeyError('Native control reference not found: '+str(ref))
    part=data['parts'][ref]
    if part['device'] not in CONTROLS:raise NotImplementedError('Native binary control not verified for '+ref+': '+part['device'])
    state=part['properties'].get('STATE')
    if state not in ('0','1'):raise RuntimeError(f'{ref}.STATE: native control position is not binary: {state!r}')
    return part


def _bindings(sim,data):
    current={name:{key:p['properties'].get(key) for key in ('INC','DEC','KEY')} for name,p in data['parts'].items()}
    if current!=sim._initial_bindings:
        raise RuntimeError('Actuator bindings changed after opening; save and reopen the isolated run')
    return current


def _control_binding(data,ref,current):
    part=control_row(data,ref)
    properties=part['properties'];inc,dec=properties.get('INC'),properties.get('DEC')
    if not all(isinstance(v,str) and re.fullmatch('[0-9]',v) for v in (inc,dec)) or inc==dec:
        raise RuntimeError(ref+': call Circuit.bind_controls(), save and reopen before operating this control')
    for name,bindings in current.items():
        if name!=ref and any(value in (inc,dec) for value in bindings.values()):
            raise RuntimeError('Actuator key collision: '+ref+' and '+name)
    if properties.get('KEY') in (inc,dec):raise RuntimeError('KEY conflicts with INC/DEC: '+ref)
    return part,inc,dec


def _probe_rows(data,refs):
    for ref in refs:
        if ref not in data['parts']:raise KeyError('Native probe not found: '+ref)
        if data['parts'][ref]['device']!='LOGICPROBE':
            raise NotImplementedError('Output observation requires a LOGICPROBE: '+ref)


def interact(sim,*,controls=None,probes=None):
    """Set prepared controls and observe at one verified paused native time.

    Validate the whole request before dispatch. A fresh snapshot is always used;
    changed inputs share one final readback, also used for any probe readings.
    Commands are sequential while paused, not a transactional hardware write.
    """
    from .native_simulation import message
    if controls is not None and not isinstance(controls,Mapping):
        raise TypeError('controls must map component references to binary integer states')
    controls=dict(controls or {})
    for ref,state in controls.items():
        if not isinstance(ref,str) or not ref or type(state) is not int or state not in (0,1):
            raise ValueError('Use a component reference and binary integer state 0 or 1')
    refs=[] if probes is None else list(probes)
    if probes is not None and (not refs or any(not isinstance(ref,str) or not ref for ref in refs) or len(set(refs))!=len(refs)):
        raise ValueError('Provide distinct LOGICPROBE references')
    if not controls and not refs:raise ValueError('Provide controls or probes')
    attempts=[]
    with paused(sim):
        data=snapshot(sim);exports=1
        current=_bindings(sim,data) if controls else None
        _probe_rows(data,refs)
        actions=[];commands=[]
        for ref,state in controls.items():
            part,inc,dec=_control_binding(data,ref,current)
            changed=int(part['properties']['STATE'])!=state
            actions.append(dict(backend='proteus_native_sdf',ref=ref,state=state,changed=changed,
                                command_time_seconds=data['simulation_seconds'],meaning='actuator_position'))
            if changed:commands.append((ref,state,(int(inc if state else dec)<<12)|3))
        try:
            for ref,state,command in commands:
                before=sim.status()
                if before['state']!='paused' or before['simulation_seconds']!=data['simulation_seconds']:
                    raise RuntimeError('Native simulation time changed before control dispatch')
                window=sim.session._wait(sim.session._ready)
                attempts.append(dict(ref=ref,state=state,command_time_seconds=data['simulation_seconds'],readback_verified=False))
                message(sim.session.pid,window['hwnd'],0x111,command)
            observed=snapshot(sim) if commands else data
            exports+=bool(commands)
            if observed['simulation_seconds']!=data['simulation_seconds']:
                raise RuntimeError('Native simulation time changed during control dispatch')
            if controls:
                _bindings(sim,observed)
                for ref,state in controls.items():
                    actual=int(control_row(observed,ref)['properties']['STATE'])
                    if actual!=state:
                        raise RuntimeError(f'Native actuator state read-back mismatch: {ref}; expected {state}, observed {actual}')
                for attempt in attempts:attempt['readback_verified']=True
            observation=None
            if refs:
                _probe_rows(observed,refs);values={}
                for ref in refs:
                    raw=observed['parts'][ref]['properties'].get('STATE')
                    if raw not in ('0','1'):
                        raise RuntimeError(f'{ref}: native probe is unknown/nonbinary ({raw!r}); check the input drive and wiring')
                    values[ref]=int(raw)
                observation=dict(backend=observed['backend'],simulation_seconds=observed['simulation_seconds'],
                                 time_resolution_seconds=observed['time_resolution_seconds'],probes=values,
                                 meaning='sampled_native_digital_levels')
            return dict(backend='proteus_native_sdf',simulation_seconds=observed['simulation_seconds'],
                        actions=actions,observation=observation,native_exports=exports)
        except Exception as error:
            error.native_action_attempts=attempts
            raise


def set_control(sim,ref,state):
    return interact(sim,controls={ref:state})['actions'][0]


def observe(sim,probes):
    return interact(sim,probes=probes)['observation']
