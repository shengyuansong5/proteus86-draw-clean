"""Code-driven native schematic generation for the verified Proteus 8.6 format."""
from .api import Circuit, Library, Project, UnsupportedFormat, PropertyError, mm, from_spec
from .installation import Installation
from .design import from_design, route_file, parse_design
from .geometry import wiringcheck
from .quality import wire_quality
from .firmware import firmware_info,prepare_run
from .resources import package_project
from .diagnostics import diagnose_project
from .scenarios import Scenario,evaluate_samples

__version__ = "0.9.1"
__all__ = ["Circuit", "Library", "Project", "UnsupportedFormat", "Installation", "mm", "from_spec", "from_design", "route_file", "parse_design", "wiringcheck", "Session", "parse_sdf", "Simulation", "SimulationError", "simulate", "firmware_info", "prepare_run"]
__all__ += ['PropertyError','package_project','diagnose_project','Scenario','evaluate_samples']
__all__ += ['wire_quality']


def __getattr__(name):
    if name in ('Simulation','SimulationError','simulate'):
        from .simulation import Simulation,SimulationError,simulate
        return {'Simulation':Simulation,'SimulationError':SimulationError,'simulate':simulate}[name]
    if name in ('Session', 'parse_sdf'):
        from .session import Session, parse_sdf
        return {'Session': Session, 'parse_sdf': parse_sdf}[name]
    raise AttributeError(name)

from .digital import (prepare_control_batches, run_control_batches, decode_seven_segment,
                      read_display_frame, DisplaySamplingError)
__all__ += ["prepare_control_batches", "run_control_batches", "decode_seven_segment",
            "read_display_frame", "DisplaySamplingError"]
