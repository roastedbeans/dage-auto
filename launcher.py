#!/usr/bin/env python3
"""
Launcher for Dage Auto - dispatches to GUI or CLI based on argv.
Used by the standalone app: GUI by default, "ability ..." for subprocess.
"""

import sys
import os

# PyInstaller: add extracted data to path so aqw_auto can be imported
if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    # Fix SSL certificate verification — bundled libcrypto has a hardcoded CA path
    # that doesn't exist at runtime. Point to certifi's bundled cacert.pem instead.
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "ability":
        import aqw_auto
        sys.argv = ["aqw_auto"] + sys.argv[1:]
        aqw_auto.main()
    else:
        import aqw_gui
        aqw_gui.main()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            # Show dialog when bundled (no console)
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.critical(None, "Dage Auto Error", str(e))
            except Exception:
                pass
        raise
