# main.py
import os, sys

from PyQt6.QtCore import QCoreApplication, Qt
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from app.ui.main_window import MainWindow
os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", "9222")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--remote-allow-origins=*")

def _add_qt_bin_to_path():
    try:
        from PyQt6.QtCore import QLibraryInfo
        bin_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath)
        if bin_path:
            os.add_dll_directory(bin_path)
            print(f"[INFO] Qt bin added to DLL search path: {bin_path}")
    except Exception as e:
        print("[WARN] add_dll_directory failed:", e)

def main():
    _add_qt_bin_to_path()

    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # Crée et montre la fenêtre
    from app.ui.main_window import MainWindow
    win = MainWindow()
    win.show()

    # Arrêt propre si l’appli quitte (fermeture, Ctrl+C, etc.)
    def _on_quit():
        try:
            win.stop_feed()
        except Exception:
            pass
    app.aboutToQuit.connect(_on_quit)

    # Catch global exceptions pour voir un éventuel plantage silencieux
    def _excepthook(t, v, tb):
        import traceback
        traceback.print_exception(t, v, tb)
        try:
            win.stop_feed()
        finally:
            sys.exit(1)
    sys.excepthook = _excepthook

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        # Double sécurité: on s'assure que le thread est bien mort avant de quitter le process
        try:
            win.stop_feed()
        except Exception:
            pass

        # Forçage ultime si nécessaire
        th = getattr(win, "thread", None)
        if th is not None and th.isRunning():
            print("⚠️ Thread encore vivant à la sortie. Tentative de quit() + wait()…")
            th.quit()
            if not th.wait(5000):
                print("⚠️ Forcing thread terminate() …")
                th.terminate()
                th.wait(1000)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
