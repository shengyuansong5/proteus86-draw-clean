"""Opt-in native shared-I/O/progress acceptance, optionally comparing saved 0.7 code.

All cases own their PDS process. Fixtures and read-only course copies are written
to a fresh D-drive workspace folder. Intentional cancellation/process exit are
checked as failed/incomplete scenarios, never as completed simulation passes.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load_baseline(directory, name):
    path = directory/'proteus86'/(name+'.py')
    manifest = read(directory.parent/'baseline_manifest.json')
    expected = next(item['sha256'] for item in manifest['files'] if item['path']=='proteus86/'+name+'.py')
    assert sha(path)==expected, 'Baseline source changed'
    spec = importlib.util.spec_from_file_location('proteus86._baseline_'+name, path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def logic_fixture(directory):
    from proteus86 import Circuit
    from proteus86.inspection import netcheck
    c = Circuit();expected = []
    with c.batch():
        for i in range(2):
            s,p='S'+str(i+1),'P'+str(i+1)
            c.add_mm('LOGICSTATE',s,'INPUT'+str(i+1),0,-i*25.4)
            c.add_mm('LOGICPROBE',p,'OUTPUT'+str(i+1),25.4,-i*25.4,rotation=180)
            c.connect_net((s,c.pins(s)[0]['name']),(p,c.pins(p)[0]['name']))
            expected.append([s+'.'+c.pins(s)[0]['name'],p+'.'+c.pins(p)[0]['name']])
        c.bind_controls('S1','S2');c.arrange_labels()
    c.fit_sheet();source=c.save(directory/'logic.pdsprj')
    assert netcheck(source,expected)['passed']
    return source


def dense_scene():
    from proteus86 import Scenario
    scene=Scenario()
    for at,a,b in ((.04,1,1),(.08,0,1),(.12,1,0),(.16,0,0),(.20,1,1),(.24,0,0)):
        scene.set('S1',a,at=at).set('S2',b,at=at)
    return scene


def close(sim,row):
    if sim is None:return
    try:sim.close()
    except Exception as error:row.update(passed=False,cleanup_error=str(error))
    row['process_closed']=sim.session.process.poll() is not None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--temp-dir',type=Path,required=True)
    parser.add_argument('--baseline-dir',type=Path)
    parser.add_argument('--course-root',type=Path)
    args=parser.parse_args()
    directory=args.output_dir.resolve();temporary=args.temp_dir.resolve()
    directory.relative_to(ROOT)
    if directory.drive.upper()!='D:' or temporary.drive.upper()!='D:' or not str(temporary).isascii():
        raise ValueError('Use a fresh D workspace directory and an ASCII D TEMP directory')
    temporary.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True;tempfile.tempdir=str(temporary)
    directory.mkdir()
    from proteus86 import Circuit,Scenario,Simulation,__version__
    from scripts.verify_course_dynamic import audit_native,instrument,make_scene,evaluate,timing_checks
    from scripts.verify_dynamic import fixture
    report=dict(version=__version__,passed=False,backend='proteus_native_sdf',
                offline_isa_executor_used=False,temp_directory=str(temporary),results=[],
                script_sha256=sha(__file__))

    def publish():
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    legacy_interactions=legacy_runner=None
    if args.baseline_dir:
        legacy_interactions=load_baseline(args.baseline_dir.resolve(),'interactions')
        legacy_runner=load_baseline(args.baseline_dir.resolve(),'scenario_runner')
        report['baseline']=dict(directory=str(args.baseline_dir.resolve()),
                                scope='Saved 0.7 interaction/scenario functions; same native timing and file APIs')

    class LegacyFacade:
        def __init__(self,sim):self.sim=sim
        def __getattr__(self,name):return getattr(self.sim,name)
        def press(self,ref):return legacy_interactions.set_control(self.sim,ref,1)
        def release(self,ref):return legacy_interactions.set_control(self.sim,ref,0)
        def observe(self,probes):return legacy_interactions.observe(self.sim,probes)

    logic=logic_fixture(directory);logic_hash=sha(logic)
    modes=(['baseline'] if legacy_runner else [])+['optimized','owned_process_exit']
    for mode in modes:
        row=dict(name='dense_'+mode,passed=False);report['results'].append(row);sim=None
        print('Native:',row['name'],flush=True)
        try:
            sim=Simulation.open(logic,directory/row['name']);row['pid']=sim.session.pid;publish()
            c=Circuit.open(sim.session.project)
            row['native_netlist_before']=audit_native(c,sim.session.export_netlist(directory/(row['name']+'-before.sdf')))
            sim.run_for(.02)
            exports=[0];original=sim.session.netlist
            def counted():exports[0]+=1;return original()
            sim.session.netlist=counted
            if mode=='owned_process_exit':
                def exit_owned(progress):
                    if progress['frames_completed']==3:
                        sim.session.process.terminate();sim.session.process.wait(timeout=5)
                result=sim.run_scenario(dense_scene(),probes=['P1','P2'],until=.28,sample_every=.02,progress=exit_owned)
                saved=read(result['record'])
                assert result['status']=='failed' and not result['passed'] and not result['native_run_completed']
                assert len(saved['samples'])==3 and saved['last_native_status']['state']=='exited'
                row.update(scenario=result,expected_failure='only the owned native process was intentionally terminated',passed=True)
            else:
                runner=(lambda scene,**options:legacy_runner.run_scenario(LegacyFacade(sim),scene,**options)) if mode=='baseline' else sim.run_scenario
                updates=[]
                def progress(summary):
                    updates.append(dict(summary))
                    assert read(summary['record'])['passed'] is False
                    if summary['frames_completed']%5==0:
                        print(mode,'frames',summary['frames_completed'],'/',summary['frames_total'],flush=True)
                options={} if mode=='baseline' else dict(progress=progress,checkpoint_every=5)
                started=time.perf_counter()
                result=runner(dense_scene(),probes=['P1','P2'],until=.28,sample_every=.02,
                              expected_words=['00','11','01','10','00','11','00'],**options)
                row.update(scenario=result,scenario_wall_seconds=time.perf_counter()-started,native_sdf_exports=exports[0])
                assert result['passed'] and result['native_run_completed'], result.get('error',result.get('evaluation'))
                if mode=='optimized':
                    assert exports[0]==result['native_sdf_exports']==21
                    assert len(updates)==15
                    row['progress_updates']=updates
                    row['checkpoint_readable_during_run']=True
                    cancelled=sim.run_scenario(Scenario().hold('S1',at=.02,seconds=.06),probes=['P1','P2'],
                        until=.12,sample_every=.02,progress=lambda summary:summary['frames_completed']<3)
                    assert cancelled['status']=='cancelled' and not cancelled['passed'] and not cancelled['native_run_completed']
                    assert len(read(cancelled['record'])['samples'])==3 and sim.status()['state']=='paused'
                    row['native_cancellation']=cancelled
                    def failing_callback(summary):raise RuntimeError('Intentional consumer failure')
                    failed=sim.run_scenario(Scenario().release('S1',at=0),probes=['P1','P2'],
                        until=.04,sample_every=.02,progress=failing_callback)
                    assert failed['status']=='failed' and len(read(failed['record'])['samples'])==1
                    assert not failed['passed'] and not failed['native_run_completed']
                    row['callback_failure']=failed
                else:assert exports[0]==37
                sim.session.netlist=original
                row['native_netlist_after']=audit_native(c,sim.session.export_netlist(directory/(row['name']+'-after.sdf')))
                sim.stop();sim.session.save()
                assert Circuit.open(sim.session.project).nets()==c.nets()
                row.update(native_save_python_reopen=True,passed=True)
        except Exception as error:row.update(error=type(error).__name__+': '+str(error))
        finally:
            close(sim,row);row['source_unchanged']=sha(logic)==logic_hash;publish()
        print('Completed:',row['name'],row['passed'],row.get('error',''),flush=True)

    counter_dir=directory/'counter-fixture';counter_dir.mkdir()
    counter,expected=fixture(counter_dir);counter_hash=sha(counter)
    row=dict(name='counter_debounce',passed=False);report['results'].append(row);sim=None
    print('Native: counter_debounce',flush=True)
    try:
        sim=Simulation.open(counter,directory/'counter-run');row['pid']=sim.session.pid;publish()
        c=Circuit.open(sim.session.project)
        row['native_netlist_before']=audit_native(c,sim.session.export_netlist(directory/'counter-before.sdf'))
        sim.run_for(.075)
        scene=Scenario().bounce('B1',at=.04,intervals=[.01]*4).bounce('B1',at=.22,intervals=[.01]*4,state=0).hold('B1',at=.36,seconds=.36)
        def counter_progress(summary):
            if summary['frames_completed']%20==0:print('counter frames',summary['frames_completed'],'/',summary['frames_total'],flush=True)
        result=sim.run_scenario(scene,probes=['P'+str(i) for i in range(8)],until=.8,sample_every=.01,
            expected_words=['11111111','01111111','10111111'],expected_changes={'P0':2,'P1':{'falling':1}},progress=counter_progress)
        row['scenario']=result
        assert result['passed'] and result['native_run_completed'],result.get('error',result.get('evaluation'))
        row['native_netlist_after']=audit_native(c,sim.session.export_netlist(directory/'counter-after.sdf'))
        sim.stop();sim.session.save()
        assert Circuit.open(sim.session.project).nets()==c.nets()
        row.update(native_save_python_reopen=True,passed=True)
    except Exception as error:row['error']=type(error).__name__+': '+str(error)
    finally:
        close(sim,row);row['source_unchanged']=sha(counter)==counter_hash;publish()
    print('Completed: counter',row['passed'],row.get('error',''),flush=True)

    if args.course_root:
        row=dict(name='course_direction_speed',passed=False);report['results'].append(row);sim=None
        folder=directory/'course-copy';folder.mkdir()
        source=args.course_root.resolve()/'作业2/Proteus/05_Interactive.pdsprj'
        project=folder/'instrumented.pdsprj'
        row['preparation']=instrument(source,project,False)
        print('Native: course_direction_speed',flush=True)
        try:
            sim=Simulation.open(project,directory/'course-run');row['pid']=sim.session.pid;publish()
            c=Circuit.open(sim.session.project)
            row['native_netlist_before']=audit_native(c,sim.session.export_netlist(directory/'course-before.sdf'))
            sim.run_for(.2);scene,until,step=make_scene('05_Interactive')
            def course_progress(summary):
                if summary['frames_completed']%25==0:print('course frames',summary['frames_completed'],'/',summary['frames_total'],flush=True)
            result=sim.run_scenario(scene,probes=['Q'+str(i) for i in range(8)],until=until,sample_every=step,progress=course_progress)
            row.update(scenario=result,evaluation=evaluate('05_Interactive',result['samples'],False),
                       native_timing=timing_checks(scene,result,until,step))
            assert result['passed'] and result['native_run_completed'] and row['evaluation']['passed'] and row['native_timing']['passed']
            row['native_netlist_after']=audit_native(c,sim.session.export_netlist(directory/'course-after.sdf'))
            sim.stop();sim.session.save()
            assert Circuit.open(sim.session.project).nets()==c.nets()
            row.update(native_save_python_reopen=True,passed=True)
        except Exception as error:row['error']=type(error).__name__+': '+str(error)
        finally:
            close(sim,row);row['source_unchanged']=sha(source)==row['preparation']['source_sha256'];publish()
        print('Completed: course',row['passed'],row.get('error',''),flush=True)
    if legacy_runner:
        before=next(row for row in report['results'] if row['name']=='dense_baseline')
        after=next(row for row in report['results'] if row['name']=='dense_optimized')
        if before['passed'] and after['passed']:
            normalized=lambda row:[(round(s['requested_at'],6),s['probes']) for s in row['scenario']['samples']]
            assert normalized(before)==normalized(after), 'Native sampled results differ'
            report['comparison']=dict(native_samples_identical=True,before_exports=before['native_sdf_exports'],
                after_exports=after['native_sdf_exports'],before_wall_seconds=before['scenario_wall_seconds'],
                after_wall_seconds=after['scenario_wall_seconds'],
                wall_speedup=before['scenario_wall_seconds']/after['scenario_wall_seconds'],
                scope='One same-circuit native run each; export counts deterministic, wall time varies with load')
    report['passed']=all(row['passed'] and row.get('process_closed') and row['source_unchanged'] for row in report['results'])
    publish();print('RECORD',directory/'result.json','passed',report['passed'],flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
