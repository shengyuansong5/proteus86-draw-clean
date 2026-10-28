"""Read-only spacing/straightness audit of supported saved schematic geometry.

These are drawing-quality checks, not topology, simulation or PCB clearance.
"""
from .routing import clean, collinear_overlap
from itertools import islice


def _analyze(decoded, gap, run):
    wires = decoded['wires']
    paths = [clean(wire['points']) for wire in wires]
    segments = [(i, j, a, b) for i, path in enumerate(paths)
                for j, (a, b) in enumerate(zip(path, path[1:]))]
    # Bounds and orientation stay fixed for this read-only snapshot. Computing
    # them once avoids repeating min/max and temporary pairs for every check.
    projected = []
    for i, part, a, b in segments:
        horizontal = a[1] == b[1]
        axis = 0 if horizontal else 1
        projected.append((i, part, a, b, horizontal, min(a[axis], b[axis]),
                          max(a[axis], b[axis]), a[1-axis]))
    joints = {}
    for node in decoded['junctions']:
        joints.setdefault(tuple(node['position']), set()).update(node['wires'])
    def attached(i,k,point):
        shared=joints.get(point,set())
        return (wires[i]['offset'] in shared and wires[k]['offset'] in shared and
                point in (paths[i][0],paths[i][-1]) and point in (paths[k][0],paths[k][-1]))
    overlaps, crossings, nearby = [], {}, []
    minimum = None
    for index, (i, part, a, b, horizontal, low, high, constant) in enumerate(projected):
        for k, other_part, c, d, other_horizontal, other_low, other_high, other_constant in islice(projected, index):
            if i == k and abs(part-other_part) <= 1:
                continue
            if horizontal == other_horizontal:
                length = min(high, other_high) - max(low, other_low)
                if length < 0:
                    continue
                distance = abs(constant-other_constant)
                if length <= 0:
                    if length == 0 and distance == 0:
                        coordinate=max(low, other_low)
                        point=(coordinate,a[1]) if horizontal else (a[0],coordinate)
                        if not attached(i,k,point):
                            pair = sorted((i, k))
                            crossings[(tuple(pair),point)] = dict(wires=pair,position_mm=[v/100000 for v in point])
                    continue
                if distance == 0 and collinear_overlap(a, b, c, d):
                    overlaps.append(dict(wires=sorted((i,k)),overlap_mm=length/100000))
                elif length >= run:
                    minimum = distance if minimum is None else min(minimum, distance)
                    if distance < gap:
                        nearby.append(dict(wires=sorted((i,k)),gap_mm=distance/100000,parallel_run_mm=length/100000))
                continue
            point = (c[0], a[1]) if horizontal else (a[0], c[1])
            h_low, h_high, v_low, v_high = ((low, high, other_low, other_high)
                                           if horizontal else (other_low, other_high, low, high))
            if h_low <= point[0] <= h_high and v_low <= point[1] <= v_high:
                if not attached(i,k,point):
                    pair = sorted((i, k))
                    crossings[(tuple(pair),point)] = dict(wires=pair,position_mm=[v/100000 for v in point])
    bends = sum(max(0,len(path)-2) for path in paths)
    straight = sum(len(path)==2 for path in paths)
    return dict(passed=not (overlaps or crossings or nearby),
        scope='Saved drawing geometry only; not electrical, simulation or PCB clearance verification',
        minimum_gap_mm=gap/100000,minimum_parallel_run_mm=run/100000,
        overlaps=overlaps,crossings=list(crossings.values()),near_parallel=nearby,
        minimum_measured_parallel_gap_mm=None if minimum is None else minimum/100000,
        wires=len(wires),straight_wires=straight,bends=bends,
        wire_length_mm=sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for _,_,a,b in segments)/100000)


def wire_quality(project, *, min_gap_mm=2.54, min_parallel_mm=2.54):
    """Report overlaps, non-junction crossings and nearby parallel wire runs.

    Exact native junction contacts are excluded only for their attached wires.
    Near-parallel runs must overlap in projection for at least min_parallel_mm;
    equality at the requested gap is allowed. This is an audit, not a rerouter.
    """
    from .api import Circuit, mm
    from ._codec.net_objects import decode_net_objects
    gap, run = mm(min_gap_mm), mm(min_parallel_mm)
    if gap <= 0 or run <= 0:
        raise ValueError('Wire gap and parallel-run length must be positive finite millimetres')
    Circuit.open(project)  # Preserve all supported-format/object guards.
    return _analyze(decode_net_objects(project),gap,run)
