"""Firmware preflight and isolated, portable simulation project bundles."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def firmware_info(path):
    path=Path(path).resolve(strict=True)
    if not path.is_file() or not 0<path.stat().st_size<=64*1024*1024:
        raise ValueError('Firmware must be a nonempty file of at most 64 MiB')
    data=path.read_bytes()
    result=dict(path=str(path),format=path.suffix.lower().lstrip('.'),size=len(data),sha256=hashlib.sha256(data).hexdigest())
    if path.suffix.lower()=='.hex':
        ended=False;base=0;ranges=[];program_bytes=0
        for number,line in enumerate(data.decode('ascii').splitlines(),1):
            if not line.strip():continue
            if ended or not line.startswith(':'):raise ValueError(f'Invalid HEX record at line {number}')
            record=bytes.fromhex(line[1:])
            if len(record)<5 or len(record)!=record[0]+5 or sum(record)%256:
                raise ValueError(f'Invalid HEX length/checksum at line {number}')
            size,address,kind=record[0],int.from_bytes(record[1:3],'big'),record[3]
            payload=record[4:-1]
            if kind==0:
                if base+address+size>2**32:raise ValueError('HEX address overflow')
                if size:
                    ranges.append((base+address,base+address+size))
                    program_bytes+=size
            elif kind==1:
                if size or address:raise ValueError('Invalid HEX EOF')
                ended=True
            elif kind in (2,4):
                if size!=2 or address:raise ValueError('Invalid HEX address record')
                base=int.from_bytes(payload,'big')<<(4 if kind==2 else 16)
            elif kind in (3,5):
                if size!=4 or address:raise ValueError('Invalid HEX entry record')
            else:raise ValueError('Unsupported HEX record type')
        if not ended or not ranges:raise ValueError('HEX must contain data and EOF')
        ranges.sort()
        if any(a[1]>b[0] for a,b in zip(ranges,ranges[1:])):raise ValueError('Overlapping HEX data')
        result.update(program_bytes=program_bytes,address_min=ranges[0][0],address_max=ranges[-1][1]-1)
    elif path.suffix.lower()=='.elf':
        if len(data)<52 or data[:4]!=b'\x7fELF' or data[4] not in (1,2) or data[5] not in (1,2) or data[6]!=1:
            raise ValueError('Invalid ELF header')
        if data[4]==2 and len(data)<64:raise ValueError('Truncated ELF64 header')
        result['machine']=int.from_bytes(data[18:20],'little' if data[5]==1 else 'big')
    elif path.suffix.lower() not in ('.bin','.cof','.coff'):
        raise ValueError('Unsupported firmware format; use HEX, ELF, BIN or COF/COFF')
    return result


def prepare_run(project,destination,*,firmware=None):
    """Copy project and external firmware into a new directory; preserve source."""
    from .api import Circuit
    from .resources import copy_verified
    source=Path(project).resolve(strict=True)
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError(destination)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    circuit=Circuit.open(source)
    if circuit._source_digest.hex()!=source_hash:raise RuntimeError('Source changed while opening the run')
    if any(name.upper().startswith('FIRMWARE') for name in circuit._members):
        raise NotImplementedError('Embedded VSM Studio builds are unsupported; use an external-firmware project')
    overrides=dict(firmware or {})
    if any(not isinstance(value,(str,Path)) or not str(value) for value in overrides.values()):
        raise ValueError('Firmware overrides must be nonempty local file paths')
    parts={part['ref']:part for part in circuit.components()}
    if set(overrides)-set(parts):raise KeyError('Firmware target not found: '+str(set(overrides)-set(parts)))
    images={}
    for ref,part in parts.items():
        raw=overrides.get(ref,part['properties'].get('PROGRAM'))
        if raw:
            if 'PROGRAM' not in circuit._declared_properties(circuit._parts[circuit._index(ref)]):
                from .api import PropertyError
                raise PropertyError(ref,'PROGRAM','该器件没有声明固件属性','选择支持 PROGRAM 的 MCU')
            path=Path(raw)
            if not path.is_absolute():path=(Path.cwd() if ref in overrides else source.parent)/path
            images[ref]=firmware_info(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.proteus86-run-',dir=destination.parent))
    try:
        with circuit.batch():
            for ref,info in images.items():
                relative=Path('firmware')/(ref+'.'+info['format'])
                target=copy_verified(info,staging/relative)
                circuit._resources[str(relative)] = info
                circuit.set_properties(ref,PROGRAM=str(relative))
                circuit.set_property_visibility(ref,PROGRAM=False)
        saved=circuit.save(staging/'circuit.pdsprj',portable=False)
        if Circuit.open(saved).nets()!=circuit.nets():raise RuntimeError('Run preparation changed circuit topology')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:
            raise RuntimeError('Source project changed while preparing the run')
        for ref,info in images.items():
            info['relative'] = str(Path('firmware')/(ref+'.'+info['format']))
        report=dict(source=str(source),source_sha256=source_hash,project=str(destination/'circuit.pdsprj'),project_relative='circuit.pdsprj',firmware=images)
        (staging/'bundle.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if staging.resolve().parent!=destination.parent or not staging.name.startswith('.proteus86-run-'):
            raise RuntimeError('Run staging directory moved outside its intended parent')
        os.rename(staging,destination)
        return report
    finally:
        if staging.exists():
            if staging.resolve().parent!=destination.parent or not staging.name.startswith('.proteus86-run-'):
                raise RuntimeError('Refusing cleanup outside the private run staging directory')
            shutil.rmtree(staging)
