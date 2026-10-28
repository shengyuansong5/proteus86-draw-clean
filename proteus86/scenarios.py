"""Timed binary stimuli and explicit sampled-state assertions, independent of an ISA."""
import math


def microseconds(value, *, positive=False):
    if isinstance(value,bool): raise ValueError('Times must be numeric seconds, not booleans')
    number=float(value)
    if not math.isfinite(number) or number<0 or positive and number<=0 or abs(number*1e6-round(number*1e6))>1e-6:
        raise ValueError('Times must be nonnegative integer microseconds')
    return round(number*1e6)


class Scenario:
    """Times are seconds relative to the run's recorded paused baseline."""
    def __init__(self): self.actions=[]

    def set(self,ref,state,*,at):
        if not isinstance(ref,str) or not ref or type(state) is not int or state not in (0,1):
            raise ValueError('A reference and binary integer state 0/1 are required')
        self.actions.append(dict(at=microseconds(at)/1e6,ref=ref,state=state))
        return self

    def press(self,ref,*,at): return self.set(ref,1,at=at)
    def release(self,ref,*,at): return self.set(ref,0,at=at)

    def hold(self,ref,*,at,seconds):
        start=microseconds(at);length=microseconds(seconds,positive=True)
        return self.press(ref,at=start/1e6).release(ref,at=(start+length)/1e6)

    def bounce(self,ref,*,at,intervals,state=1):
        """Start in state; alternate after each interval, ending in that state (even intervals)."""
        ticks=[microseconds(value,positive=True) for value in intervals]
        if not ticks or len(ticks)%2: raise ValueError('Bounce requires a nonempty even number of intervals')
        start=microseconds(at);self.set(ref,state,at=start/1e6)
        for index,length in enumerate(ticks):
            start+=length;self.set(ref,1-state if index%2==0 else state,at=start/1e6)
        return self


def timeline(scenario,until,sample_every,*,tolerance):
    if not isinstance(scenario,Scenario):raise TypeError('Use a Scenario instance')
    end=microseconds(until,positive=True);step=microseconds(sample_every,positive=True)
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('Invalid timing tolerance')
    if end//step>10000:raise ValueError('Scenario exceeds 10000 sample intervals')
    frames={tick:dict(at=tick/1e6,actions=[],sample=True) for tick in range(0,end+1,step)}
    frames.setdefault(end,dict(at=end/1e6,actions=[],sample=True))
    assigned={}
    for action in scenario.actions:
        tick=microseconds(action['at'])
        if tick>end:raise ValueError('Scenario action occurs after until')
        key=tick,action['ref']
        if key in assigned and assigned[key]!=action['state']:raise ValueError('Conflicting simultaneous control actions')
        if key in assigned:continue
        assigned[key]=action['state']
        frames.setdefault(tick,dict(at=tick/1e6,actions=[],sample=False))['actions'].append(dict(action))
    ordered=[frames[tick] for tick in sorted(frames)]
    gaps=[b['at']-a['at'] for a,b in zip(ordered,ordered[1:])]
    if gaps and 2*tolerance>=min(gaps)-1e-9:
        raise ValueError('Timing tolerance must be less than half the smallest timeline interval; use wider spacing or a stricter tolerance')
    return ordered


def evaluate_samples(samples,probes,*,expected_sequences=None,expected_changes=None,expected_words=None):
    """Count observed transitions only. Pulses between sample times may be missed."""
    probes=list(probes)
    if not probes or len(set(probes))!=len(probes):raise ValueError('Provide distinct probe references')
    if set(expected_sequences or {})-set(probes) or set(expected_changes or {})-set(probes):
        raise ValueError('An assertion names a probe that is not observed')
    sequences={ref:[] for ref in probes};counts={ref:dict(transitions=0,rising=0,falling=0) for ref in probes}
    words=[]
    for sample in samples:
        values=sample['probes']
        if set(probes)-set(values):raise ValueError('Sample is missing an observed probe')
        word=''
        for ref in probes:
            value=values[ref]
            if type(value) is not int or value not in (0,1):raise ValueError('A probe has an unknown/nonbinary native state: '+ref)
            word+=str(value)
            if not sequences[ref] or value!=sequences[ref][-1]:
                if sequences[ref]:
                    counts[ref]['transitions']+=1;counts[ref]['rising' if value else 'falling']+=1
                sequences[ref].append(value)
        if not words or words[-1]!=word: words.append(word)
    checks=[]
    for ref,expected in (expected_sequences or {}).items():
        checks.append(dict(kind='sequence',ref=ref,expected=expected,actual=sequences[ref],passed=sequences[ref]==expected))
    for ref,expected in (expected_changes or {}).items():
        expected={'transitions':expected} if type(expected) is int else expected
        if not isinstance(expected,dict) or not expected or set(expected)-{'transitions','rising','falling'}:
            raise ValueError('Counts must specify transitions, rising or falling')
        for edge,count in expected.items():
            if type(count) is not int or count<0:raise ValueError('Counts must be nonnegative integers')
            checks.append(dict(kind=edge,ref=ref,expected=count,actual=counts[ref][edge],passed=counts[ref][edge]==count))
    if expected_words is not None:
        checks.append(dict(kind='words',probe_order=probes,expected=expected_words,actual=words,passed=words==expected_words))
    return dict(passed=bool(samples) and all(check['passed'] for check in checks),sequences=sequences,
                observed_counts=counts,words=words,checks=checks,coverage='sampled_states_only',
                limitation='Transitions between sample times are not counted; digital probes are not voltage or LED brightness measurements')
