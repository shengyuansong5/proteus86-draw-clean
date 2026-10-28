"""Locate the user's installed libraries. Never modify the installation."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = Path(os.environ.get("PROTEUS86_TEMPLATE", str(ROOT / "templates/base86.pdsprj"))).resolve()


@dataclass(frozen=True)
class Installation:
    home: Path

    @property
    def executable(self):
        return self.home / "BIN/PDS.EXE"

    @property
    def library(self):
        return self.home / "LIBRARY"

    @classmethod
    def discover(cls, directory=None):
        candidates = []
        if directory is not None:
            candidates = [Path(directory)]
        elif os.environ.get("PROTEUS86_HOME"):
            candidates = [Path(os.environ["PROTEUS86_HOME"])]
        else:
            if os.name == "nt":
                import winreg
                key_name = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                        try:
                            with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                                for index in range(winreg.QueryInfoKey(key)[0]):
                                    try:
                                        with winreg.OpenKey(key, winreg.EnumKey(key, index)) as child:
                                            name = winreg.QueryValueEx(child, "DisplayName")[0]
                                            if "Proteus" in name:
                                                candidates.append(Path(winreg.QueryValueEx(child, "InstallLocation")[0]))
                                    except OSError:
                                        continue
                        except OSError:
                            continue
            for drive in ("D:", "C:", "E:"):
                candidates.append(Path(drive + r"\Program Files (x86)\Labcenter Electronics\Proteus 8 Professional"))
        valid = {path.resolve() for path in candidates
                 if (path / "BIN/PDS.EXE").is_file() and (path / "LIBRARY").is_dir()}
        if len(valid) != 1:
            raise FileNotFoundError("请通过 --install 或 PROTEUS86_HOME 指定唯一的 Proteus 安装目录。找到: " + str(sorted(map(str, valid))))
        return cls(valid.pop())
