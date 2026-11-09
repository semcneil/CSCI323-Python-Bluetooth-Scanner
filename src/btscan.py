"""
btscan.py
====================================
This is simple Bluetooth scanner

| Author: Seth McNeill
| Date: 2026 November 09
"""

import sys
import asyncio
from PyQt6 import QtWidgets, QtCore
from qasync import QEventLoop, asyncSlot
from bleak import BleakScanner, BleakClient

class BLEExplorerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BLE Device Explorer & Scanner")
        self.resize(950, 650)

        self.client: BleakClient = None
        self.discovered_devices = {}
        self.selected_device_address = None
        
        # Connection Task tracking for cancellation
        self.connect_task: asyncio.Task = None

        # 2-second scan refresh timer
        self.scan_timer = QtCore.QTimer()
        self.scan_timer.setInterval(2000)
        self.scan_timer.timeout.connect(self.trigger_scan)

        self.init_ui()

    def init_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QHBoxLayout(main_widget)

        # ---------------- Left Panel: Device Scanning ----------------
        left_layout = QtWidgets.QVBoxLayout()
        
        scan_controls = QtWidgets.QHBoxLayout()
        self.toggle_scan_btn = QtWidgets.QPushButton("Start Scanning")
        self.toggle_scan_btn.clicked.connect(self.toggle_scanning)
        scan_controls.addWidget(self.toggle_scan_btn)

        self.status_label = QtWidgets.QLabel("Status: Idle")
        left_layout.addLayout(scan_controls)
        left_layout.addWidget(self.status_label)

        self.device_table = QtWidgets.QTableWidget()
        self.device_table.setColumnCount(3)
        self.device_table.setHorizontalHeaderLabels(["Name", "Address / MAC", "RSSI (dBm)"])
        self.device_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.device_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.device_table.itemSelectionChanged.connect(self.on_device_selected)
        left_layout.addWidget(self.device_table)

        # Connection Buttons (Connect & Cancel)
        conn_btn_layout = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self.handle_connect_click)
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel Connection")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_connection_attempt)

        conn_btn_layout.addWidget(self.connect_btn)
        conn_btn_layout.addWidget(self.cancel_btn)
        left_layout.addLayout(conn_btn_layout)

        main_layout.addLayout(left_layout, stretch=1)

        # ---------------- Right Panel: GATT Explorer ----------------
        right_layout = QtWidgets.QVBoxLayout()
        
        right_layout.addWidget(QtWidgets.QLabel("Device Services & Characteristics:"))
        self.tree_widget = QtWidgets.QTreeWidget()
        self.tree_widget.setHeaderLabels(["UUID / Description", "Handle / Details", "Properties"])
        self.tree_widget.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.tree_widget.itemSelectionChanged.connect(self.on_tree_item_selected)
        right_layout.addWidget(self.tree_widget)

        # Action Panel: Read, Write, Notify
        action_group = QtWidgets.QGroupBox("Characteristic Actions")
        action_layout = QtWidgets.QVBoxLayout(action_group)

        # Read Section
        read_layout = QtWidgets.QHBoxLayout()
        self.read_btn = QtWidgets.QPushButton("Read")
        self.read_btn.setEnabled(False)
        self.read_btn.clicked.connect(self.read_characteristic)
        self.read_val_label = QtWidgets.QLabel("Value: N/A")
        read_layout.addWidget(self.read_btn)
        read_layout.addWidget(self.read_val_label, stretch=1)
        action_layout.addLayout(read_layout)

        # Write Section
        write_layout = QtWidgets.QHBoxLayout()
        self.write_input = QtWidgets.QLineEdit()
        self.write_input.setPlaceholderText("Enter text or hex (e.g. 0x0102)")
        self.write_btn = QtWidgets.QPushButton("Write")
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self.write_characteristic)
        write_layout.addWidget(self.write_input)
        write_layout.addWidget(self.write_btn)
        action_layout.addLayout(write_layout)

        # Notify Section
        notify_layout = QtWidgets.QHBoxLayout()
        self.notify_btn = QtWidgets.QPushButton("Start Notify")
        self.notify_btn.setEnabled(False)
        self.notify_btn.clicked.connect(self.toggle_notify)
        self.notify_output = QtWidgets.QLabel("Notification output: N/A")
        notify_layout.addWidget(self.notify_btn)
        notify_layout.addWidget(self.notify_output, stretch=1)
        action_layout.addLayout(notify_layout)

        right_layout.addWidget(action_group)
        main_layout.addLayout(right_layout, stretch=1)

    # ---------------- Scanning Logic ----------------

    def toggle_scanning(self):
        if self.scan_timer.isActive():
            self.scan_timer.stop()
            self.toggle_scan_btn.setText("Start Scanning")
            self.status_label.setText("Status: Scanning Stopped")
        else:
            self.scan_timer.start()
            self.toggle_scan_btn.setText("Stop Scanning")
            self.status_label.setText("Status: Scanning...")
            self.trigger_scan()

    def trigger_scan(self):
        asyncio.create_task(self.perform_scan())

    async def perform_scan(self):
        devices = await BleakScanner.discover(timeout=1.5, return_adv=True)

        device_list = []
        for key, (device, adv_data) in devices.items():
            name = device.name or adv_data.local_name or "Unknown Device"
            rssi = adv_data.rssi
            device_list.append({
                "device": device,
                "name": name,
                "address": device.address,
                "rssi": rssi
            })
            self.discovered_devices[device.address] = device

        # Sort from strongest to weakest signal
        device_list.sort(key=lambda x: x["rssi"], reverse=True)

        # Update table while maintaining selection
        self.update_table_preserving_selection(device_list)

    def update_table_preserving_selection(self, device_list):
        # Temporarily block signals so itemSelectionChanged doesn't clear selected state
        self.device_table.blockSignals(True)
        
        # Save currently selected MAC address
        previously_selected_address = self.selected_device_address

        self.device_table.setRowCount(len(device_list))
        row_to_reselect = -1

        for row, dev_info in enumerate(device_list):
            addr = dev_info["address"]
            self.device_table.setItem(row, 0, QtWidgets.QTableWidgetItem(dev_info["name"]))
            self.device_table.setItem(row, 1, QtWidgets.QTableWidgetItem(addr))
            self.device_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(dev_info["rssi"])))

            if previously_selected_address and addr == previously_selected_address:
                row_to_reselect = row

        # Restore selection to the same device if it was re-discovered
        if row_to_reselect != -1:
            self.device_table.selectRow(row_to_reselect)

        self.device_table.blockSignals(False)

    # ---------------- Connection Logic ----------------

    def on_device_selected(self):
        selected_rows = self.device_table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            self.selected_device_address = self.device_table.item(row, 1).text()
            if not self.client or not self.client.is_connected:
                self.connect_btn.setEnabled(True)
        else:
            self.selected_device_address = None
            if not self.client or not self.client.is_connected:
                self.connect_btn.setEnabled(False)

    def handle_connect_click(self):
        if self.client and self.client.is_connected:
            asyncio.create_task(self.disconnect_device())
        else:
            self.connect_task = asyncio.create_task(self.connect_device_with_timeout())

    async def connect_device_with_timeout(self):
        if not self.selected_device_address:
            return

        device = self.discovered_devices.get(self.selected_device_address)
        if not device:
            return

        self.status_label.setText(f"Status: Connecting to {self.selected_device_address}...")
        self.connect_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        try:
            self.client = BleakClient(device)
            # Wrap connection attempt in an asyncio timeout (10 seconds)
            await asyncio.wait_for(self.client.connect(), timeout=10.0)
            
            self.status_label.setText(f"Status: Connected to {self.selected_device_address}")
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)

            await self.populate_services()

        except asyncio.CancelledError:
            self.status_label.setText("Status: Connection cancelled by user.")
            await self.cleanup_failed_connection()
        except asyncio.TimeoutError:
            self.status_label.setText("Status: Connection timed out.")
            await self.cleanup_failed_connection()
        except Exception as e:
            self.status_label.setText(f"Status: Connection failed ({str(e)})")
            await self.cleanup_failed_connection()

    def cancel_connection_attempt(self):
        if self.connect_task and not self.connect_task.done():
            self.connect_task.cancel()

    async def cleanup_failed_connection(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    async def disconnect_device(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.status_label.setText("Status: Disconnected")
        self.connect_btn.setText("Connect")
        self.cancel_btn.setEnabled(False)
        self.tree_widget.clear()
        self.reset_action_panel()

    # ---------------- Services & Characteristics Tree ----------------

    async def populate_services(self):
        self.tree_widget.clear()
        if not self.client or not self.client.is_connected:
            return

        services = self.client.services
        for service in services:
            service_item = QtWidgets.QTreeWidgetItem(self.tree_widget)
            service_item.setText(0, f"Service: {service.description or 'Unknown'}")
            service_item.setText(1, service.uuid)
            
            for char in service.characteristics:
                char_item = QtWidgets.QTreeWidgetItem(service_item)
                char_item.setText(0, f"Char: {char.description or 'Unknown'}")
                char_item.setText(1, char.uuid)
                char_item.setText(2, ", ".join(char.properties))
                char_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, char)

        self.tree_widget.expandAll()

    # ---------------- Characteristic Interaction ----------------

    def on_tree_item_selected(self):
        self.reset_action_panel()
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        char = item.data(0, QtCore.Qt.ItemDataRole.UserRole)

        if char:
            props = char.properties
            self.read_btn.setEnabled("read" in props)
            self.write_btn.setEnabled("write" in props or "write-without-response" in props)
            self.notify_btn.setEnabled("notify" in props or "indicate" in props)

    def reset_action_panel(self):
        self.read_btn.setEnabled(False)
        self.write_btn.setEnabled(False)
        self.notify_btn.setEnabled(False)
        self.notify_btn.setText("Start Notify")
        self.read_val_label.setText("Value: N/A")
        self.notify_output.setText("Notification output: N/A")

    @asyncSlot()
    async def read_characteristic(self):
        item = self.tree_widget.selectedItems()[0]
        char = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        try:
            val = await self.client.read_gatt_char(char.uuid)
            self.read_val_label.setText(f"Value: {val.hex()} ({val})")
        except Exception as e:
            self.read_val_label.setText(f"Read error: {str(e)}")

    @asyncSlot()
    async def write_characteristic(self):
        item = self.tree_widget.selectedItems()[0]
        char = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        raw_text = self.write_input.text().strip()

        try:
            if raw_text.startswith("0x"):
                payload = bytes.fromhex(raw_text[2:])
            else:
                payload = raw_text.encode('utf-8')

            await self.client.write_gatt_char(char.uuid, payload)
            self.status_label.setText(f"Status: Written to {char.uuid}")
        except Exception as e:
            self.status_label.setText(f"Status: Write failed ({str(e)})")

    @asyncSlot()
    async def toggle_notify(self):
        item = self.tree_widget.selectedItems()[0]
        char = item.data(0, QtCore.Qt.ItemDataRole.UserRole)

        if self.notify_btn.text() == "Start Notify":
            try:
                await self.client.start_notify(char.uuid, self.notification_handler)
                self.notify_btn.setText("Stop Notify")
            except Exception as e:
                self.notify_output.setText(f"Notify error: {str(e)}")
        else:
            try:
                await self.client.stop_notify(char.uuid)
                self.notify_btn.setText("Start Notify")
            except Exception as e:
                self.notify_output.setText(f"Stop notify error: {str(e)}")

    def notification_handler(self, sender: int, data: bytearray):
        self.notify_output.setText(f"Notify [{sender}]: {data.hex()} ({bytes(data)})")

    def closeEvent(self, event):
        if self.connect_task and not self.connect_task.done():
            self.connect_task.cancel()
        if self.client and self.client.is_connected:
            asyncio.create_task(self.client.disconnect())
        event.accept()

def main():
    app = QtWidgets.QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = BLEExplorerApp()
    window.show()

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()