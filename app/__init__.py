# app/__init__.py
import os
from pathlib import Path
from PyQt6.QtCore import QLibraryInfo

try:
    qt_bin = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath))
    os.add_dll_directory(str(qt_bin))
    print("[INFO] Qt bin added to DLL search path:", qt_bin)
except Exception as e:
    print("[WARN] Qt BinariesPath not added:", e)
