import sys
from PyQt5.QtWidgets import QApplication
from ui.dashboard import DashboardWindow
from ui.camera_view import CameraWindow
from ui.mode_selection_dialog import ModeSelectionDialog


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    db = DashboardWindow()
    mode_dialog = ModeSelectionDialog(db.settings_window.MODE_NAMES, db.current_mode)
    if not mode_dialog.exec_():
        sys.exit(0)

    db.set_operation_mode(mode_dialog.selected_mode)
    cam = CameraWindow(db, embedded=True)
    db.attach_camera_panel(cam)

    def on_change_mode():
        if getattr(db, "is_running", False):
            db.stop_signal.emit()
        dialog = ModeSelectionDialog(db.settings_window.MODE_NAMES, db.current_mode, db)
        if dialog.exec_():
            db.set_operation_mode(dialog.selected_mode)

    db.change_mode_signal.connect(on_change_mode)

    db.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

