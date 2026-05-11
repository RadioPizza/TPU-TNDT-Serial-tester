#!/usr/bin/env python3
"""
Protocol2 Test Tool - GUI для тестирования связи с контроллером дефектоскопа.
Использует PySide6 и QtSerialPort.
"""

import sys
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QIODevice, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QPushButton, QLabel, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QLineEdit, QTextEdit, QSplitter,
    QMessageBox, QGridLayout, QFrame, QListWidget
)
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor

# ----------------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------------
STYLE_SHEET = """
QTextEdit#log {
    background-color: #1e1e1e;
    color: #dcdcdc;
    font-family: 'Consolas', monospace;
    font-size: 10pt;
    border: 1px solid #3c3c3c;
}
QPushButton {
    min-height: 28px;
    padding: 4px 12px;
}
"""

COLOR_SENT  = "#569cd6"   # команды отправленные
COLOR_OK    = "#6a9955"   # OK
COLOR_ERR   = "#f44747"   # ERR
COLOR_DATA  = "#ce9178"   # DATA (ответ на запрос)
COLOR_ASYNC = "#d7ba7d"   # DATA (асинхронное событие)
COLOR_INFO  = "#9cdcfe"   # информационные


class LogTextEdit(QTextEdit):
    """Терминал с цветным логом и моноширинным шрифтом."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setStyleSheet(STYLE_SHEET)
        self.setMinimumHeight(100)
        # Явно задаём моноширинный шрифт
        self.setFontFamily("Consolas, monospace")
        self.setFontPointSize(10)

    def append_log(self, text: str, color: str = None):
        """Добавить строку с меткой времени и (опционально) цветом."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]   # миллисекунды

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        # Создаём формат с нужным цветом
        fmt = QTextCharFormat()
        if color:
            fmt.setForeground(QColor(color))

        # Вставляем текст с переводом строки
        cursor.insertText(f"[{ts}] {text}\n", fmt)

        # Прокручиваем к последней строке
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class SerialComm(QObject):
    """Обёртка над QSerialPort."""
    line_received = Signal(str)           # пришедшая полезная строка
    connection_changed = Signal(bool)     # True - подключено

    def __init__(self, parent=None):
        super().__init__(parent)
        self.port = QSerialPort(self)
        self.port.readyRead.connect(self.on_ready_read)
        self.port.errorOccurred.connect(self.on_error)
        self.buffer = ""

    def list_ports(self):
        return [port.portName() for port in QSerialPortInfo.availablePorts()]

    def connect_port(self, port_name: str, baud_rate: int = 115200):
        if self.port.isOpen():
            self.port.close()
        self.port.setPortName(port_name)
        self.port.setBaudRate(baud_rate)
        self.port.setDataBits(QSerialPort.Data8)
        self.port.setParity(QSerialPort.NoParity)
        self.port.setStopBits(QSerialPort.OneStop)
        self.port.setFlowControl(QSerialPort.NoFlowControl)
        if self.port.open(QIODevice.ReadWrite):
            self.connection_changed.emit(True)
            return True
        else:
            self.connection_changed.emit(False)
            return False

    def disconnect_port(self):
        if self.port.isOpen():
            self.port.close()
            self.connection_changed.emit(False)

    def send(self, data: str):
        if not self.port.isOpen():
            return
        raw = (data.strip() + "\r\n").encode("utf-8")
        self.port.write(raw)

    @Slot()
    def on_ready_read(self):
        data = self.port.readAll().data().decode("utf-8", errors="replace")
        self.buffer += data
        while True:
            idx = self.buffer.find("\n")
            if idx == -1:
                break
            line = self.buffer[:idx].strip()
            self.buffer = self.buffer[idx + 1:]
            if line:                           # игнорируем пустые строки
                self.line_received.emit(line)

    @Slot(QSerialPort.SerialPortError)
    def on_error(self, error):
        if error != QSerialPort.NoError:
            self.connection_changed.emit(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Protocol2 Test Tool — Дефектоскоп TPU-TNDT")
        self.resize(1000, 700)

        # Serial
        self.serial = SerialComm(self)
        self.serial.line_received.connect(self.process_incoming)
        self.serial.connection_changed.connect(self.on_connection_changed)
        self.connected = False

        # Таймер авто-ping
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self.send_ping)
        self.ping_timer.setInterval(2500)

        # Строим интерфейс
        self._setup_ui()

        # Заполняем список портов
        self.refresh_ports()

    # --------------------------------------------------------------------
    #  Построение GUI
    # --------------------------------------------------------------------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Верхняя панель соединения ---
        top = QHBoxLayout()
        top.addWidget(QLabel("COM порт:"))
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(120)
        top.addWidget(self.cmb_port)

        top.addWidget(QLabel("Скорость:"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["115200", "57600", "38400", "19200", "9600"])
        self.cmb_baud.setCurrentText("115200")
        top.addWidget(self.cmb_baud)

        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.clicked.connect(self.toggle_connection)
        top.addWidget(self.btn_connect)

        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_status = QLabel("● Нет соединения")
        self.lbl_status.setStyleSheet("color: red; font-weight: bold;")
        top.addWidget(self.lbl_status)

        top.addStretch()

        self.chk_auto_ping = QCheckBox("Авто-ping (2.5с)")
        self.chk_auto_ping.toggled.connect(self.on_auto_ping_toggled)
        top.addWidget(self.chk_auto_ping)
        main_layout.addLayout(top)

        # --- Разделитель: вкладки + лог ---
        splitter = QSplitter(Qt.Vertical)
        self.tab_widget = QTabWidget()
        self._build_heat_tab()
        self._build_light_tab()
        self._build_led_tab()
        self._build_sys_tab()
        self._build_info_tab()
        self._build_btn_events_tab()
        self._build_raw_tab()
        splitter.addWidget(self.tab_widget)

        self.log = LogTextEdit()
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    # --- Вкладки (код без изменений, сокращён для краткости) ---
    def _build_heat_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)
        grp = QGroupBox("Канал нагрева")
        hly = QHBoxLayout()
        self.heat_channel = QComboBox()
        self.heat_channel.addItems(["LEFT", "RIGHT", "BOTH", "ALL (выкл)"])
        hly.addWidget(QLabel("Цель:"))
        hly.addWidget(self.heat_channel)
        grp.setLayout(hly)
        ly.addWidget(grp)

        bly = QHBoxLayout()
        for text, slot in [("ON", self.cmd_heat_on), ("OFF", self.cmd_heat_off),
                           ("STATUS", self.cmd_heat_status)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bly.addWidget(btn)
        ly.addLayout(bly)

        self.lbl_heat_status = QLabel("Последний статус: —")
        ly.addWidget(self.lbl_heat_status)
        ly.addStretch()
        self.tab_widget.addTab(tab, "🔥 Нагрев")

    def _build_light_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)
        grp = QGroupBox("Канал подсветки")
        hly = QHBoxLayout()
        self.light_channel = QComboBox()
        self.light_channel.addItems(["1", "2", "BOTH", "ALL (выкл)"])
        hly.addWidget(QLabel("Канал:"))
        hly.addWidget(self.light_channel)
        grp.setLayout(hly)
        ly.addWidget(grp)

        bly = QHBoxLayout()
        for text, slot in [("ON", self.cmd_light_on), ("OFF", self.cmd_light_off)]:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bly.addWidget(btn)
        ly.addLayout(bly)

        brly = QHBoxLayout()
        brly.addWidget(QLabel("Яркость (0-255):"))
        self.spin_brightness = QSpinBox()
        self.spin_brightness.setRange(0, 255)
        self.spin_brightness.setValue(128)
        brly.addWidget(self.spin_brightness)
        btn_set = QPushButton("SET")
        btn_set.clicked.connect(self.cmd_light_set)
        brly.addWidget(btn_set)
        brly.addStretch()
        ly.addLayout(brly)

        btn_status = QPushButton("STATUS")
        btn_status.clicked.connect(self.cmd_light_status)
        ly.addWidget(btn_status)
        ly.addStretch()
        self.tab_widget.addTab(tab, "💡 Подсветка")

    def _build_led_tab(self):
        tab = QWidget()
        ly = QGridLayout(tab)

        # CONST
        ly.addWidget(QLabel("Постоянная яркость:"), 0, 0)
        self.spin_const_bright = QSpinBox()
        self.spin_const_bright.setRange(0, 255)
        self.spin_const_bright.setValue(128)
        ly.addWidget(self.spin_const_bright, 0, 1)
        btn = QPushButton("CONST")
        btn.clicked.connect(self.cmd_led_const)
        ly.addWidget(btn, 0, 2)

        # BLINK
        ly.addWidget(QLabel("Период(мс):"), 1, 0)
        self.spin_blink_period = QSpinBox()
        self.spin_blink_period.setRange(10, 10000)
        self.spin_blink_period.setValue(500)
        ly.addWidget(self.spin_blink_period, 1, 1)
        ly.addWidget(QLabel("Ярк:"), 1, 2)
        self.spin_blink_bright = QSpinBox()
        self.spin_blink_bright.setRange(0, 255)
        self.spin_blink_bright.setValue(255)
        ly.addWidget(self.spin_blink_bright, 1, 3)
        ly.addWidget(QLabel("Скважн:"), 1, 4)
        self.spin_blink_duty = QDoubleSpinBox()
        self.spin_blink_duty.setRange(0.0, 1.0)
        self.spin_blink_duty.setSingleStep(0.1)
        self.spin_blink_duty.setValue(0.5)
        ly.addWidget(self.spin_blink_duty, 1, 5)
        btn = QPushButton("BLINK")
        btn.clicked.connect(self.cmd_led_blink)
        ly.addWidget(btn, 1, 6)

        # PULSE
        ly.addWidget(QLabel("Период(мс):"), 2, 0)
        self.spin_pulse_period = QSpinBox()
        self.spin_pulse_period.setRange(10, 10000)
        self.spin_pulse_period.setValue(2000)
        ly.addWidget(self.spin_pulse_period, 2, 1)
        ly.addWidget(QLabel("Макс:"), 2, 2)
        self.spin_pulse_bright = QSpinBox()
        self.spin_pulse_bright.setRange(0, 255)
        self.spin_pulse_bright.setValue(255)
        ly.addWidget(self.spin_pulse_bright, 2, 3)
        btn = QPushButton("PULSE")
        btn.clicked.connect(self.cmd_led_pulse)
        ly.addWidget(btn, 2, 4)

        # FLASH
        ly.addWidget(QLabel("Кол-во:"), 3, 0)
        self.spin_flash_count = QSpinBox()
        self.spin_flash_count.setRange(1, 100)
        self.spin_flash_count.setValue(5)
        ly.addWidget(self.spin_flash_count, 3, 1)
        ly.addWidget(QLabel("вкл(мс):"), 3, 2)
        self.spin_flash_on = QSpinBox()
        self.spin_flash_on.setRange(10, 5000)
        self.spin_flash_on.setValue(200)
        ly.addWidget(self.spin_flash_on, 3, 3)
        ly.addWidget(QLabel("выкл(мс):"), 3, 4)
        self.spin_flash_off = QSpinBox()
        self.spin_flash_off.setRange(10, 5000)
        self.spin_flash_off.setValue(200)
        ly.addWidget(self.spin_flash_off, 3, 5)
        ly.addWidget(QLabel("ярк:"), 3, 6)
        self.spin_flash_bright = QSpinBox()
        self.spin_flash_bright.setRange(0, 255)
        self.spin_flash_bright.setValue(255)
        ly.addWidget(self.spin_flash_bright, 3, 7)
        btn = QPushButton("FLASH")
        btn.clicked.connect(self.cmd_led_flash)
        ly.addWidget(btn, 3, 8)

        btn_stop = QPushButton("STOP")
        btn_stop.clicked.connect(self.cmd_led_stop)
        ly.addWidget(btn_stop, 4, 0)
        btn_status = QPushButton("STATUS")
        btn_status.clicked.connect(self.cmd_led_status)
        ly.addWidget(btn_status, 4, 1)

        ly.setColumnStretch(9, 1)
        self.tab_widget.addTab(tab, "🔆 LED")

    def _build_sys_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)

        btn = QPushButton("SYS PING")
        btn.clicked.connect(self.cmd_sys_ping)
        ly.addWidget(btn)

        mly = QHBoxLayout()
        mly.addWidget(QLabel("Режим:"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["TABLET", "MANUAL"])
        mly.addWidget(self.cmb_mode)
        btn_set = QPushButton("Установить")
        btn_set.clicked.connect(self.cmd_sys_set_mode)
        mly.addWidget(btn_set)
        btn_get = QPushButton("Запросить")
        btn_get.clicked.connect(self.cmd_sys_get_mode)
        mly.addWidget(btn_get)
        ly.addLayout(mly)

        self.lbl_current_mode = QLabel("Текущий режим: ?")
        ly.addWidget(self.lbl_current_mode)
        ly.addStretch()
        self.tab_widget.addTab(tab, "⚙️ Система")

    def _build_info_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)
        btn = QPushButton("INFO FW (версия прошивки)")
        btn.clicked.connect(self.cmd_info_fw)
        ly.addWidget(btn)
        btn = QPushButton("INFO HW (ревизия)")
        btn.clicked.connect(self.cmd_info_hw)
        ly.addWidget(btn)
        ly.addStretch()
        self.tab_widget.addTab(tab, "ℹ️ Инфо")

    def _build_btn_events_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)
        self.list_btn_events = QListWidget()
        ly.addWidget(QLabel("События кнопки Старт:"))
        ly.addWidget(self.list_btn_events)
        btn = QPushButton("Очистить")
        btn.clicked.connect(self.list_btn_events.clear)
        ly.addWidget(btn)
        self.tab_widget.addTab(tab, "🔘 Кнопка")

    def _build_raw_tab(self):
        tab = QWidget()
        ly = QVBoxLayout(tab)
        ly.addWidget(QLabel("Произвольная команда:"))
        hly = QHBoxLayout()
        self.raw_cmd = QLineEdit()
        self.raw_cmd.setPlaceholderText("например HEAT ON LEFT")
        hly.addWidget(self.raw_cmd)
        btn = QPushButton("Отправить")
        btn.clicked.connect(self.cmd_raw_send)
        hly.addWidget(btn)
        ly.addLayout(hly)
        ly.addStretch()
        self.tab_widget.addTab(tab, "📝 Raw")

    # --------------------------------------------------------------------
    #  Отправка команд
    # --------------------------------------------------------------------
    def send_command(self, cmd: str, color: str = COLOR_SENT):
        if not self.connected:
            QMessageBox.warning(self, "Нет соединения", "Сначала подключитесь к порту.")
            return
        self.log.append_log(f">>> {cmd}", color)
        self.serial.send(cmd)

    # --- HEAT ---
    def cmd_heat_on(self):
        target = self.heat_channel.currentText().split()[0]
        if target == "ALL":
            self.log.append_log("Ошибка: ALL не поддерживается для ON", COLOR_ERR)
            return
        self.send_command(f"HEAT ON {target}")

    def cmd_heat_off(self):
        target = self.heat_channel.currentText().split()[0]
        if target == "ALL (выкл)":
            target = "ALL"
        self.send_command(f"HEAT OFF {target}")

    def cmd_heat_status(self):
        self.send_command("HEAT STATUS")

    # --- LIGHT ---
    def cmd_light_on(self):
        ch = self.light_channel.currentText().split()[0]
        if ch == "ALL":
            self.log.append_log("Ошибка: ALL не поддерживается для ON", COLOR_ERR)
            return
        self.send_command(f"LIGHT ON {ch}")

    def cmd_light_off(self):
        ch = self.light_channel.currentText().split()[0]
        if ch == "ALL (выкл)":
            ch = "ALL"
        self.send_command(f"LIGHT OFF {ch}")

    def cmd_light_set(self):
        ch = self.light_channel.currentText().split()[0]
        if ch in ("BOTH", "ALL"):
            self.log.append_log("Ошибка: SET принимает только 1 или 2", COLOR_ERR)
            return
        val = self.spin_brightness.value()
        self.send_command(f"LIGHT SET {ch} {val}")

    def cmd_light_status(self):
        self.send_command("LIGHT STATUS")

    # --- LED ---
    def cmd_led_const(self):
        b = self.spin_const_bright.value()
        self.send_command(f"LED CONST {b}")

    def cmd_led_blink(self):
        per = self.spin_blink_period.value()
        b = self.spin_blink_bright.value()
        d = self.spin_blink_duty.value()
        self.send_command(f"LED BLINK {per} {b} {d:.2f}")

    def cmd_led_pulse(self):
        per = self.spin_pulse_period.value()
        b = self.spin_pulse_bright.value()
        self.send_command(f"LED PULSE {per} {b}")

    def cmd_led_flash(self):
        cnt = self.spin_flash_count.value()
        on = self.spin_flash_on.value()
        off = self.spin_flash_off.value()
        b = self.spin_flash_bright.value()
        self.send_command(f"LED FLASH {cnt} {on} {off} {b}")

    def cmd_led_stop(self):
        self.send_command("LED STOP")

    def cmd_led_status(self):
        self.send_command("LED STATUS")

    # --- SYS ---
    def cmd_sys_ping(self):
        self.send_command("SYS PING", COLOR_INFO)

    def cmd_sys_set_mode(self):
        mode = self.cmb_mode.currentText()
        self.send_command(f"SYS MODE {mode}")

    def cmd_sys_get_mode(self):
        self.send_command("SYS MODE")

    # --- INFO ---
    def cmd_info_fw(self):
        self.send_command("INFO FW")

    def cmd_info_hw(self):
        self.send_command("INFO HW")

    # --- RAW ---
    def cmd_raw_send(self):
        cmd = self.raw_cmd.text().strip()
        if cmd:
            self.send_command(cmd)
            self.raw_cmd.clear()

    # --------------------------------------------------------------------
    #  Обработка входящих строк
    # --------------------------------------------------------------------
    @Slot(str)
    def process_incoming(self, line: str):
        parts = line.split(maxsplit=2)
        if not parts:
            return

        if parts[0] == "OK":
            color = COLOR_OK
        elif parts[0] == "ERR":
            color = COLOR_ERR
        elif parts[0] == "DATA":
            if len(parts) >= 3 and parts[1] == "BTN":
                self.list_btn_events.addItem(
                    f"{datetime.now().strftime('%H:%M:%S')}  {line}")
                color = COLOR_ASYNC
            elif len(parts) >= 3 and parts[1] == "SYS" and "MODE=" in line:
                if "MODE=MANUAL" in line:
                    self.lbl_current_mode.setText("Текущий режим: MANUAL")
                elif "MODE=TABLET" in line:
                    self.lbl_current_mode.setText("Текущий режим: TABLET")
                color = COLOR_ASYNC
            else:
                color = COLOR_DATA
        else:
            color = None

        self.log.append_log(f"<<< {line}", color)

        # Дополнительная обработка DATA HEAT
        if parts[0] == "DATA" and len(parts) >= 3 and parts[1] == "HEAT":
            self.lbl_heat_status.setText(f"Последний статус: {line}")

    # --------------------------------------------------------------------
    #  Управление портом
    # --------------------------------------------------------------------
    def refresh_ports(self):
        self.cmb_port.clear()
        ports = self.serial.list_ports()
        self.cmb_port.addItems(ports)
        if ports:
            self.cmb_port.setCurrentIndex(0)

    def toggle_connection(self):
        if self.connected:
            self.serial.disconnect_port()
        else:
            port = self.cmb_port.currentText()
            baud = int(self.cmb_baud.currentText())
            if not port:
                QMessageBox.critical(self, "Ошибка", "Выберите COM порт.")
                return
            if self.serial.connect_port(port, baud):
                self.btn_connect.setText("Отключить")
                self.lbl_status.setText(f"● Подключено к {port}")
                self.lbl_status.setStyleSheet("color: green; font-weight: bold;")
                self.log.append_log(f"Подключено к {port} на {baud} бод", COLOR_INFO)
                self.connected = True
            else:
                QMessageBox.critical(self, "Ошибка", f"Не удалось открыть порт {port}")

    def on_connection_changed(self, connected: bool):
        if not connected and self.connected:
            self.connected = False
            self.btn_connect.setText("Подключить")
            self.lbl_status.setText("● Нет соединения")
            self.lbl_status.setStyleSheet("color: red; font-weight: bold;")
            self.log.append_log("Соединение потеряно", COLOR_ERR)
            self.chk_auto_ping.setChecked(False)

    def on_auto_ping_toggled(self, checked):
        if checked:
            self.ping_timer.start()
        else:
            self.ping_timer.stop()

    def send_ping(self):
        if self.connected:
            self.send_command("SYS PING", COLOR_INFO)

    def closeEvent(self, event):
        self.serial.disconnect_port()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()