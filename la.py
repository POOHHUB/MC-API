import sys
import os
import json
import shutil
import hashlib
import subprocess
import threading
import requests
import minecraft_launcher_lib

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QProgressBar, QStackedWidget, QListWidget,
    QListWidgetItem, QCheckBox, QScrollArea, QFrame
)
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

# ─── CONFIG ───────────────────────────────────────────────────────────────────
LAUNCHER_VERSION = "1.0.0"
LAUNCHER_DIR = os.path.join(os.path.expanduser("~"), ".barrie_launcher")
MINECRAFT_DIR = os.path.join(LAUNCHER_DIR, "minecraft")
MODS_DIR = os.path.join(MINECRAFT_DIR, "mods")
USERS_FILE = os.path.join(LAUNCHER_DIR, "users.json")
SETTINGS_FILE = os.path.join(LAUNCHER_DIR, "settings.json")
FORGE_VERSION = "1.16.5-36.2.39"  # Forge for 1.16.5
MODS_DISABLED_DIR = os.path.join(MODS_DIR, "disabled")

# ─── YOUR API ENDPOINTS ────────────────────────────────────────────────────────
API_MODS_LIST = "https://raw.githubusercontent.com/POOHHUB/MC-API/refs/heads/main/mods/list.json"
API_LAUNCHER_VERSION = "https://raw.githubusercontent.com/POOHHUB/MC-API/refs/heads/main/launcher/version.json"

os.makedirs(LAUNCHER_DIR, exist_ok=True)
os.makedirs(MINECRAFT_DIR, exist_ok=True)
os.makedirs(MODS_DIR, exist_ok=True)
os.makedirs(MODS_DISABLED_DIR, exist_ok=True)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─── MOD FILE HELPERS ─────────────────────────────────────────────────────────
def mod_active_path(filename):
    return os.path.join(MODS_DIR, filename)

def mod_disabled_path(filename):
    return os.path.join(MODS_DISABLED_DIR, filename)

def is_mod_enabled(filename):
    return os.path.exists(mod_active_path(filename))

def enable_mod(filename):
    src = mod_disabled_path(filename)
    dst = mod_active_path(filename)
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.move(src, dst)

def disable_mod(filename):
    src = mod_active_path(filename)
    dst = mod_disabled_path(filename)
    if os.path.exists(src):
        shutil.move(src, dst)

def get_installed_mod_versions():
    """อ่าน version ที่ติดตั้งไว้จาก settings"""
    s = load_settings()
    return s.get("installed_mod_versions", {})

def save_installed_mod_versions(versions):
    s = load_settings()
    s["installed_mod_versions"] = versions
    save_settings(s)

STYLE = """
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QLineEdit {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 8px 12px;
    color: white;
}
QLineEdit:focus { border: 1px solid #e94560; }
QPushButton {
    background-color: #e94560;
    color: white;
    padding: 10px;
    border-radius: 8px;
    font-weight: bold;
    border: none;
}
QPushButton:hover { background-color: #ff6b81; }
QPushButton:disabled { background-color: #555; color: #999; }
QPushButton#secondary {
    background-color: #0f3460;
}
QPushButton#secondary:hover { background-color: #1a4a80; }
QLabel#title {
    font-size: 22px;
    font-weight: bold;
    color: #e94560;
}
QLabel#subtitle {
    font-size: 12px;
    color: #888;
}
QProgressBar {
    border: 1px solid #0f3460;
    border-radius: 5px;
    background-color: #16213e;
    height: 18px;
    text-align: center;
    color: white;
}
QProgressBar::chunk { background-color: #e94560; border-radius: 4px; }
QListWidget {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 4px;
}
QListWidget::item { padding: 6px; border-radius: 4px; }
QListWidget::item:hover { background-color: #0f3460; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #0f3460;
    border-radius: 3px;
    background: #16213e;
}
QCheckBox::indicator:checked { background-color: #e94560; }
QFrame#card {
    background-color: #16213e;
    border-radius: 10px;
    border: 1px solid #0f3460;
}
"""

# ─── WORKER THREADS ───────────────────────────────────────────────────────────
class InstallForgeThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            self.progress.emit(5, "กำลังตรวจสอบ Forge...")
            callback = {
                "setStatus": lambda s: self.progress.emit(-1, s),
                "setProgress": lambda v: self.progress.emit(v, ""),
                "setMax": lambda m: None,
            }
            minecraft_launcher_lib.install.install_minecraft_version(
                FORGE_VERSION, MINECRAFT_DIR, callback=callback
            )
            self.finished.emit(True, "ติดตั้ง Forge สำเร็จ")
        except Exception as e:
            self.finished.emit(False, str(e))


class ModSyncThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    mods_ready = pyqtSignal(list)

    def run(self):
        try:
            self.progress.emit(0, "กำลังดึงรายการมอดจาก API...")
            resp = requests.get(API_MODS_LIST, timeout=10)
            resp.raise_for_status()
            mods = resp.json()  # [{id, name, version, url, hash, filename}]
            self.mods_ready.emit(mods)
            self.finished.emit(True, "โหลดรายการมอดสำเร็จ")
        except Exception as e:
            self.mods_ready.emit([])
            self.finished.emit(False, f"ไม่สามารถดึงมอดจาก API: {e}")


class DownloadModsThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    mod_updated = pyqtSignal(list)  # รายชื่อมอดที่ถูกปิดเพราะอัพเดทใหม่

    def __init__(self, mods_to_download):
        super().__init__()
        self.mods = mods_to_download

    def run(self):
        total = len(self.mods)
        installed_versions = get_installed_mod_versions()
        newly_updated = []

        for i, mod in enumerate(self.mods):
            try:
                filename = mod.get("filename", mod["name"] + ".jar")
                api_version = mod.get("version", "")
                old_version = installed_versions.get(mod["id"], "")
                is_update = old_version and old_version != api_version

                # ถ้าไฟล์มีอยู่แล้วและ version เดิม ข้ามได้เลย
                active = mod_active_path(filename)
                disabled = mod_disabled_path(filename)
                if not is_update and (os.path.exists(active) or os.path.exists(disabled)):
                    self.progress.emit(int(((i + 1) / total) * 90), f"✅ {mod['name']} ไม่มีการเปลี่ยนแปลง")
                    continue

                self.progress.emit(int((i / total) * 90), f"ดาวน์โหลด {mod['name']} v{api_version}...")

                # ลบไฟล์เก่าทั้ง active และ disabled ก่อน
                for old_f in [active, disabled]:
                    if os.path.exists(old_f):
                        os.remove(old_f)

                # ดาวน์โหลดใหม่ → วางใน disabled ก่อนถ้าเป็นการอัพเดท
                dest = mod_disabled_path(filename) if is_update else mod_active_path(filename)
                r = requests.get(mod["url"], stream=True, timeout=60)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)

                if is_update:
                    newly_updated.append(mod["name"])

                installed_versions[mod["id"]] = api_version

            except Exception as e:
                self.finished.emit(False, f"ดาวน์โหลด {mod['name']} ล้มเหลว: {e}")
                return

        save_installed_mod_versions(installed_versions)
        self.progress.emit(100, "ดาวน์โหลดมอดครบแล้ว")
        if newly_updated:
            self.mod_updated.emit(newly_updated)
        self.finished.emit(True, "")


class LaunchThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, mc_username):
        super().__init__()
        self.mc_username = mc_username

    def run(self):
        try:
            options = {
                "username": self.mc_username,
                "uuid": "00000000-0000-0000-0000-000000000000",
                "token": "0",
                "gameDirectory": MINECRAFT_DIR,
            }
            cmd = minecraft_launcher_lib.command.get_minecraft_command(
                FORGE_VERSION, MINECRAFT_DIR, options
            )
            proc = subprocess.Popen(cmd)
            proc.wait()
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class UpdateCheckThread(QThread):
    update_available = pyqtSignal(str, str)  # new_version, url
    no_update = pyqtSignal()

    def run(self):
        try:
            resp = requests.get(API_LAUNCHER_VERSION, timeout=5)
            data = resp.json()
            if data["version"] != LAUNCHER_VERSION:
                self.update_available.emit(data["version"], data.get("url", ""))
            else:
                self.no_update.emit()
        except Exception:
            self.no_update.emit()


# ─── LOGIN PAGE ───────────────────────────────────────────────────────────────
class LoginPage(QWidget):
    login_success = pyqtSignal(str)
    go_register = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(14)

        title = QLabel("🧱 Barrie Launcher")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("Minecraft Forge 1.16.5")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        layout.addSpacing(10)

        layout.addWidget(QLabel("ชื่อผู้ใช้"))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("username")
        layout.addWidget(self.user_input)

        layout.addWidget(QLabel("รหัสผ่าน"))
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("password")
        self.pass_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass_input)

        self.login_btn = QPushButton("เข้าสู่ระบบ")
        self.login_btn.clicked.connect(self.do_login)
        layout.addWidget(self.login_btn)

        reg_btn = QPushButton("สมัครสมาชิก")
        reg_btn.setObjectName("secondary")
        reg_btn.clicked.connect(self.go_register.emit)
        layout.addWidget(reg_btn)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #e94560; font-size: 12px;")
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        layout.addStretch()
        self.setLayout(layout)

    def do_login(self):
        username = self.user_input.text().strip()
        password = self.pass_input.text()
        if not username or not password:
            self.status.setText("กรุณากรอกข้อมูลให้ครบ")
            return
        users = load_users()
        if username not in users:
            self.status.setText("ไม่พบชื่อผู้ใช้")
            return
        if users[username]["password"] != hash_password(password):
            self.status.setText("รหัสผ่านไม่ถูกต้อง")
            return
        self.login_success.emit(username)


# ─── REGISTER PAGE ────────────────────────────────────────────────────────────
class RegisterPage(QWidget):
    register_success = pyqtSignal()
    go_login = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(14)

        title = QLabel("📝 สมัครสมาชิก")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(10)

        layout.addWidget(QLabel("ชื่อผู้ใช้"))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("username")
        layout.addWidget(self.user_input)

        layout.addWidget(QLabel("รหัสผ่าน"))
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("password")
        self.pass_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass_input)

        layout.addWidget(QLabel("ยืนยันรหัสผ่าน"))
        self.pass2_input = QLineEdit()
        self.pass2_input.setPlaceholderText("confirm password")
        self.pass2_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass2_input)

        reg_btn = QPushButton("สมัครสมาชิก")
        reg_btn.clicked.connect(self.do_register)
        layout.addWidget(reg_btn)

        back_btn = QPushButton("กลับไปหน้า Login")
        back_btn.setObjectName("secondary")
        back_btn.clicked.connect(self.go_login.emit)
        layout.addWidget(back_btn)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #e94560; font-size: 12px;")
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        layout.addStretch()
        self.setLayout(layout)

    def do_register(self):
        username = self.user_input.text().strip()
        password = self.pass_input.text()
        password2 = self.pass2_input.text()
        if not username or not password:
            self.status.setText("กรุณากรอกข้อมูลให้ครบ")
            return
        if password != password2:
            self.status.setText("รหัสผ่านไม่ตรงกัน")
            return
        if len(password) < 6:
            self.status.setText("รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร")
            return
        users = load_users()
        if username in users:
            self.status.setText("ชื่อผู้ใช้นี้มีอยู่แล้ว")
            return
        users[username] = {"password": hash_password(password)}
        save_users(users)
        self.status.setStyleSheet("color: #00e676; font-size: 12px;")
        self.status.setText("สมัครสมาชิกสำเร็จ!")
        QTimer.singleShot(1000, self.register_success.emit)


# ─── MAIN LAUNCHER PAGE ───────────────────────────────────────────────────────
class LauncherPage(QWidget):
    logout = pyqtSignal()

    def __init__(self, username):
        super().__init__()
        self.account_username = username
        self.available_mods = []
        self.mod_checkboxes = {}
        self._build_ui()
        self._check_update()
        self._load_mods()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(10)

        # Header
        header = QHBoxLayout()
        title = QLabel("🧱 Barrie Launcher  |  Forge 1.16.5")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #e94560;")
        header.addWidget(title)
        header.addStretch()

        self.user_label = QLabel(f"👤 {self.account_username}")
        self.user_label.setStyleSheet("color: #aaa; font-size: 12px;")
        header.addWidget(self.user_label)

        logout_btn = QPushButton("ออกจากระบบ")
        logout_btn.setObjectName("secondary")
        logout_btn.setFixedWidth(110)
        logout_btn.clicked.connect(self.logout.emit)
        header.addWidget(logout_btn)
        layout.addLayout(header)

        # Minecraft username (offline)
        mc_row = QHBoxLayout()
        mc_row.addWidget(QLabel("ชื่อใน Minecraft (Offline):"))
        self.mc_name_input = QLineEdit()
        settings = load_settings()
        self.mc_name_input.setText(settings.get("mc_username", self.account_username))
        self.mc_name_input.setPlaceholderText("ชื่อที่จะแสดงในเกม")
        mc_row.addWidget(self.mc_name_input)
        layout.addLayout(mc_row)

        # Mods section
        mods_label = QLabel("📦 มอดที่ใช้งาน (จาก API)")
        mods_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        layout.addWidget(mods_label)

        self.mods_list = QListWidget()
        self.mods_list.setFixedHeight(160)
        layout.addWidget(self.mods_list)

        mods_btn_row = QHBoxLayout()
        self.sync_btn = QPushButton("🔄 ซิงค์มอดจาก API")
        self.sync_btn.setObjectName("secondary")
        self.sync_btn.clicked.connect(self._load_mods)
        mods_btn_row.addWidget(self.sync_btn)

        open_mods_btn = QPushButton("📂 เปิดโฟลเดอร์ Mods")
        open_mods_btn.setObjectName("secondary")
        open_mods_btn.clicked.connect(lambda: os.startfile(MODS_DIR))
        mods_btn_row.addWidget(open_mods_btn)
        layout.addLayout(mods_btn_row)

        # Status / Progress
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Launch button
        self.launch_btn = QPushButton("🚀 เล่น Minecraft Forge 1.16.5")
        self.launch_btn.setStyleSheet(
            "background-color: #e94560; font-size: 15px; padding: 14px; border-radius: 10px;"
        )
        self.launch_btn.clicked.connect(self._start_launch)
        layout.addWidget(self.launch_btn)

        # Footer
        footer = QLabel(f"v{LAUNCHER_VERSION}  |  Mods: {MODS_DIR}")
        footer.setObjectName("subtitle")
        footer.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer)

        self.setLayout(layout)

    # ── Update check ──────────────────────────────────────────────────────────
    def _check_update(self):
        self.update_thread = UpdateCheckThread()
        self.update_thread.update_available.connect(self._on_update_available)
        self.update_thread.start()

    def _on_update_available(self, new_ver, url):
        reply = QMessageBox.question(
            self, "มีอัพเดทใหม่",
            f"พบเวอร์ชันใหม่ {new_ver}\nต้องการดาวน์โหลดและอัพเดทตอนนี้เลยไหม?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes and url:
            self._do_self_update(url)

    def _do_self_update(self, url):
        try:
            self.status_label.setText("กำลังดาวน์โหลดอัพเดท...")
            r = requests.get(url, stream=True, timeout=30)
            r.raise_for_status()
            new_file = os.path.abspath("la_new.py")
            with open(new_file, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            # Replace current file and restart
            current = os.path.abspath("la.py")
            shutil.move(new_file, current)
            QMessageBox.information(self, "อัพเดทสำเร็จ", "อัพเดทเสร็จแล้ว กรุณารีสตาร์ท Launcher")
            QApplication.quit()
        except Exception as e:
            QMessageBox.warning(self, "อัพเดทล้มเหลว", str(e))

    # ── Mods ──────────────────────────────────────────────────────────────────
    def _load_mods(self):
        self.sync_btn.setEnabled(False)
        self.status_label.setText("กำลังโหลดรายการมอด...")
        self.mod_thread = ModSyncThread()
        self.mod_thread.mods_ready.connect(self._populate_mods)
        self.mod_thread.finished.connect(self._on_mods_loaded)
        self.mod_thread.start()

    def _populate_mods(self, mods):
        self.available_mods = mods
        self.mods_list.clear()
        self.mod_checkboxes.clear()

        for mod in mods:
            filename = mod.get("filename", mod["name"] + ".jar")
            # สถานะจริงจากไฟล์ในเครื่อง
            enabled = is_mod_enabled(filename)
            # ถ้ายังไม่มีไฟล์เลย ใช้ค่า default จาก API
            if not os.path.exists(mod_active_path(filename)) and not os.path.exists(mod_disabled_path(filename)):
                enabled = mod.get("enabled_by_default", True)

            item = QListWidgetItem()
            status_icon = "🟢" if enabled else "🔴"
            cb = QCheckBox(f"  {status_icon} {mod['name']}  v{mod.get('version', '?')}")
            cb.setChecked(enabled)
            cb.stateChanged.connect(lambda state, m=mod: self._toggle_mod(m, state == 2))
            self.mod_checkboxes[mod["id"]] = cb
            self.mods_list.addItem(item)
            self.mods_list.setItemWidget(item, cb)
            item.setSizeHint(cb.sizeHint())

    def _toggle_mod(self, mod, checked):
        filename = mod.get("filename", mod["name"] + ".jar")
        if checked:
            enable_mod(filename)
        else:
            disable_mod(filename)
        # อัพเดท icon
        cb = self.mod_checkboxes.get(mod["id"])
        if cb:
            icon = "🟢" if checked else "🔴"
            cb.setText(f"  {icon} {mod['name']}  v{mod.get('version', '?')}")

    def _on_mods_loaded(self, ok, msg):
        self.sync_btn.setEnabled(True)
        if not ok:
            self.status_label.setText(msg)
        else:
            self.status_label.setText(f"พบมอดทั้งหมด {len(self.available_mods)} รายการ")

    def _get_selected_mods(self):
        return [m for m in self.available_mods if self.mod_checkboxes.get(m["id"], QCheckBox()).isChecked()]

    # ── Launch ────────────────────────────────────────────────────────────────
    def _start_launch(self):
        mc_name = self.mc_name_input.text().strip()
        if not mc_name:
            QMessageBox.warning(self, "ชื่อว่าง", "กรุณาใส่ชื่อ Minecraft")
            return

        settings = load_settings()
        settings["mc_username"] = mc_name
        save_settings(settings)

        self.launch_btn.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)

        # ดาวน์โหลด/อัพเดทมอดทุกตัวที่ checked
        selected_mods = self._get_selected_mods()
        self.status_label.setText("กำลังตรวจสอบและดาวน์โหลดมอด...")
        self.dl_thread = DownloadModsThread(selected_mods)
        self.dl_thread.progress.connect(self._on_progress)
        self.dl_thread.mod_updated.connect(self._on_mods_updated)
        self.dl_thread.finished.connect(lambda ok, msg: self._after_mods(ok, msg, mc_name))
        self.dl_thread.start()

    def _on_mods_updated(self, updated_names):
        names = "\n".join(f"• {n}" for n in updated_names)
        QMessageBox.warning(
            self, "⚠️ มอดถูกปิดอัตโนมัติ",
            f"มอดต่อไปนี้มีเวอร์ชันใหม่และถูกปิดไว้ก่อนเพื่อความปลอดภัย:\n\n{names}\n\n"
            "กรุณาเปิดใช้งานด้วยตัวเองหลังจากตรวจสอบแล้ว"
        )
        # รีโหลด UI มอดให้แสดงสถานะใหม่
        self._populate_mods(self.available_mods)

    def _after_mods(self, ok, msg, mc_name):
        if not ok:
            QMessageBox.critical(self, "ดาวน์โหลดมอดล้มเหลว", msg)
            self.launch_btn.setEnabled(True)
            self.progress_bar.hide()
            return
        self._install_forge(mc_name)

    def _install_forge(self, mc_name):
        self.status_label.setText("กำลังติดตั้ง Forge 1.16.5...")
        self.forge_thread = InstallForgeThread()
        self.forge_thread.progress.connect(self._on_progress)
        self.forge_thread.finished.connect(lambda ok, msg: self._launch_game(ok, msg, mc_name))
        self.forge_thread.start()

    def _launch_game(self, ok, msg, mc_name):
        if not ok:
            QMessageBox.critical(self, "ติดตั้ง Forge ล้มเหลว", msg)
            self.launch_btn.setEnabled(True)
            self.progress_bar.hide()
            return
        self.status_label.setText("กำลังเปิด Minecraft...")
        self.launch_thread = LaunchThread(mc_name)
        self.launch_thread.finished.connect(self._on_game_closed)
        self.launch_thread.start()

    def _on_game_closed(self, ok, msg):
        self.launch_btn.setEnabled(True)
        self.progress_bar.hide()
        if not ok:
            QMessageBox.critical(self, "เปิดเกมล้มเหลว", msg)
        self.status_label.setText("ปิดเกมแล้ว")

    def _on_progress(self, value, text):
        if value >= 0:
            self.progress_bar.setValue(value)
        if text:
            self.status_label.setText(text)


# ─── MAIN WINDOW ──────────────────────────────────────────────────────────────
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Barrie Launcher")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setFixedSize(520, 560)
        self.setStyleSheet(STYLE)

        self.stack = QStackedWidget()
        self.login_page = LoginPage()
        self.register_page = RegisterPage()

        self.login_page.login_success.connect(self._on_login)
        self.login_page.go_register.connect(lambda: self.stack.setCurrentWidget(self.register_page))
        self.register_page.register_success.connect(lambda: self.stack.setCurrentWidget(self.login_page))
        self.register_page.go_login.connect(lambda: self.stack.setCurrentWidget(self.login_page))

        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.register_page)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.stack)
        self.setLayout(root)

    def _on_login(self, username):
        # Remove old launcher page if exists
        if hasattr(self, "launcher_page"):
            self.stack.removeWidget(self.launcher_page)
            self.launcher_page.deleteLater()

        self.launcher_page = LauncherPage(username)
        self.launcher_page.logout.connect(self._on_logout)
        self.stack.addWidget(self.launcher_page)
        self.stack.setCurrentWidget(self.launcher_page)

    def _on_logout(self):
        self.stack.setCurrentWidget(self.login_page)
        self.login_page.pass_input.clear()


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
