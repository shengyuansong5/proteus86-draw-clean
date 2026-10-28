"""Run from the project root: python -m examples.draw_rc"""
from pathlib import Path
from proteus86 import Circuit

circuit = Circuit()
circuit.add_mm("RESISTOR", "R1", "10k", 0, 0)
circuit.add_mm("CAPACITOR", "C1", "100n", 25.4, 0)
circuit.connect("R1.2", "C1.2")
circuit.add_terminal("ground", "", "C1.1")
print(circuit.save(Path("output/rc_from_python.pdsprj"), title="Drawn with Python"))
