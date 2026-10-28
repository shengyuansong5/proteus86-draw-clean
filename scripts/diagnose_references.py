"""Opt-in native save/diagnosis of private copies; reference files are read-only."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from proteus86 import diagnose_project
from proteus86.resources import sha256


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    directory=ROOT/'artifacts'/('reference-diagnosis-'+uuid.uuid4().hex[:8]);directory.mkdir()
    results=[]
    for index,source in enumerate(sorted(args.reference_root.rglob('*.pdsprj')),1):
        row=dict(source=str(source),before=diagnose_project(source))
        print('Diagnosing',source.name,flush=True)
        if args.native:
            from proteus86 import Session
            from proteus86.native_simulation import StatusReader
            copy=directory/('reference'+str(index)+'.pdsprj')
            shutil.copyfile(source,copy)
            assert sha256(copy)==row['before']['sha256']
            session=None
            try:
                session=Session(copy)
                StatusReader(session)  # Exact local binary guard, even though no engine run is requested.
                row['pid']=session.pid
                try:
                    sdf=session.export_netlist(directory/('reference'+str(index)+'.sdf'))
                    row['native_parts']=len(sdf['parts']);row['native_nets']=len(sdf['nets'])
                except Exception as error: row['native_netlist_error']=str(error)
                session.save()
                row['native_saved']=True
                session.close()
            except Exception as error:
                row['native_error']=str(error)
                if getattr(error,'owned_pid',None):row['pid']=error.owned_pid;row['process_closed']=error.process_closed
            finally:
                if session is not None:
                    if session.process.poll() is None: session.process.terminate();session.process.wait(timeout=5)
                    row['process_closed']=session.process.poll() is not None
            row['after']=diagnose_project(copy)
        row['source_unchanged']=sha256(source)==row['before']['sha256']
        assert row['source_unchanged']
        results.append(row)
        (directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Record:',directory/'result.json',flush=True)


if __name__=='__main__':main()
