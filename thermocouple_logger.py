import sys
import csv
from datetime import datetime
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QCheckBox, QGroupBox, QScrollArea,
                              QPushButton, QGridLayout)
from PyQt6.QtCore import QTimer

import nidaqmx
from nidaqmx.system import System
from nidaqmx.constants import ThermocoupleType, TemperatureUnits, AcquisitionType, CJCSource

# ============== CONFIGURATION ==============
TC_TYPE = ThermocoupleType.K
SAMPLE_RATE = 0.2              # Hz (thermocouple modules are slow, 4-10 Hz is typical max)
UI_UPDATE_MS = 5000            # How often to update the UI (milliseconds)
PLOT_HISTORY = 9000            # Number of points to show
LOG_FILE = "temperature_log.csv"
# ===========================================


def detect_thermocouple_channels():
    """Auto-detect all available thermocouple channels from connected NI devices."""
    channels = []
    system = System.local()
    
    for device in system.devices:
        # Check if device has analog input channels (potential thermocouple channels)
        try:
            ai_physical_chans = device.ai_physical_chans
            for chan in ai_physical_chans:
                # Thermocouple modules typically have names like cDAQ1Mod1/ai0
                # We'll add all AI channels and let the user select which are thermocouples
                channels.append(chan.name)
        except Exception:
            # Device might not support AI channels
            pass
    
    return sorted(channels)


class ThermocouplePlotter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thermocouple Logger")
        self.setGeometry(100, 100, 1200, 700)
        
        # Detect available channels
        self.available_channels = detect_thermocouple_channels()
        self.active_channels = set()  # Channels currently being read
        
        # Data storage
        self.times = deque(maxlen=PLOT_HISTORY)
        self.temps = {}
        self.start_time = datetime.now()
        self.logging = False
        self.csv_file = None
        self.csv_writer = None
        
        # DAQ task
        self.task = None
        
        self.setup_ui()
        
        # Timer for UI updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(UI_UPDATE_MS)
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        
        # Left panel for channel selection
        left_panel = QVBoxLayout()
        
        # Channel selection group
        channel_group = QGroupBox("Channels")
        channel_layout = QVBoxLayout(channel_group)
        
        # Scroll area for many channels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.channel_checkboxes = {}
        self.temp_labels = {}
        
        colors = ['#FF0000', '#0000FF', '#00AA00', '#FF00FF', '#00AAAA', 
                  '#FFAA00', '#AA00FF', '#FF5555', '#5555FF', '#55AA55']
        
        for i, ch in enumerate(self.available_channels):
            row = QHBoxLayout()
            
            # Checkbox for channel
            cb = QCheckBox()
            cb.setChecked(False)
            cb.toggled.connect(self.on_channel_toggled)
            self.channel_checkboxes[ch] = cb
            row.addWidget(cb)
            
            # Color indicator
            color = colors[i % len(colors)]
            color_label = QLabel("●")
            color_label.setStyleSheet(f"color: {color}; font-size: 16px;")
            row.addWidget(color_label)
            
            # Channel name and temp
            name_label = QLabel(f"{ch}:")
            name_label.setStyleSheet("font-weight: bold;")
            row.addWidget(name_label)
            
            temp_label = QLabel("--.- °C")
            temp_label.setMinimumWidth(80)
            self.temp_labels[ch] = temp_label
            row.addWidget(temp_label)
            
            row.addStretch()
            scroll_layout.addLayout(row)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        channel_layout.addWidget(scroll)
        
        # Select all / none buttons
        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_channels)
        btn_layout.addWidget(select_all_btn)
        
        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self.select_no_channels)
        btn_layout.addWidget(select_none_btn)
        channel_layout.addLayout(btn_layout)
        
        # Refresh channels button
        refresh_btn = QPushButton("Refresh Channels")
        refresh_btn.clicked.connect(self.refresh_channels)
        channel_layout.addWidget(refresh_btn)
        
        left_panel.addWidget(channel_group)
        
        # Logging checkbox
        self.log_checkbox = QCheckBox("Log to CSV")
        self.log_checkbox.toggled.connect(self.toggle_logging)
        left_panel.addWidget(self.log_checkbox)
        
        left_panel.addStretch()
        main_layout.addLayout(left_panel, 1)
        
        # Right panel for plot
        right_panel = QVBoxLayout()
        
        # Plot with optimizations
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Temperature', '°C')
        self.plot_widget.setLabel('bottom', 'Time', 's')
        self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True)
        
        self.plot_widget.enableAutoRange(axis='x', enable=False)
        self.plot_widget.enableAutoRange(axis='y', enable=True)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        
        right_panel.addWidget(self.plot_widget)
        main_layout.addLayout(right_panel, 3)
        
        # Create plot curves for all potential channels
        self.curves = {}
        for i, ch in enumerate(self.available_channels):
            color = colors[i % len(colors)]
            pen = pg.mkPen(color=color, width=2)
            self.curves[ch] = self.plot_widget.plot([], [], pen=pen, name=ch)
            self.curves[ch].setVisible(False)
    
    def on_channel_toggled(self):
        """Handle channel checkbox changes - restart DAQ with new channel selection."""
        new_active = {ch for ch, cb in self.channel_checkboxes.items() if cb.isChecked()}
        
        if new_active != self.active_channels:
            self.active_channels = new_active
            self.restart_daq()
    
    def select_all_channels(self):
        for cb in self.channel_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
        self.active_channels = set(self.available_channels)
        self.restart_daq()
    
    def select_no_channels(self):
        for cb in self.channel_checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.active_channels = set()
        self.restart_daq()
    
    def refresh_channels(self):
        """Re-detect available channels."""
        # Stop current acquisition
        self.stop_daq()
        
        # Re-detect
        new_channels = detect_thermocouple_channels()
        
        # Find new and removed channels
        added = set(new_channels) - set(self.available_channels)
        removed = set(self.available_channels) - set(new_channels)
        
        if added or removed:
            print(f"Channels added: {added}, removed: {removed}")
            # For simplicity, just notify user - full dynamic UI update would require more code
            self.available_channels = new_channels
            # Would need to rebuild UI here for full dynamic support
        
        # Restart with current selection
        self.restart_daq()
    
    def restart_daq(self):
        """Stop and restart DAQ with currently selected channels."""
        self.stop_daq()
        
        # Clear data for channels no longer active
        self.times.clear()
        self.temps = {ch: deque(maxlen=PLOT_HISTORY) for ch in self.active_channels}
        self.start_time = datetime.now()
        
        # Update curve visibility
        for ch in self.available_channels:
            if ch in self.curves:
                self.curves[ch].setVisible(ch in self.active_channels)
                self.curves[ch].setData([], [])
        
        # Reset temp labels
        for ch, label in self.temp_labels.items():
            if ch not in self.active_channels:
                label.setText("--.- °C")
        
        # Start new task if channels selected
        if self.active_channels:
            self.setup_daq()
    
    def setup_daq(self):
        """Set up DAQ task for active channels."""
        if not self.active_channels:
            return
        
        try:
            self.task = nidaqmx.Task()
            for ch in sorted(self.active_channels):
                self.task.ai_channels.add_ai_thrmcpl_chan(
                    ch,
                    units=TemperatureUnits.DEG_C,
                    thermocouple_type=TC_TYPE,
                    cjc_source=CJCSource.BUILT_IN
                )
            
            self.task.timing.cfg_samp_clk_timing(
                rate=SAMPLE_RATE,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=1000
            )
            self.task.start()
            print(f"DAQ started with channels: {sorted(self.active_channels)}")
        except Exception as e:
            print(f"Error starting DAQ: {e}")
            self.task = None
    
    def stop_daq(self):
        """Stop current DAQ task."""
        if self.task:
            try:
                self.task.stop()
                self.task.close()
            except Exception:
                pass
            self.task = None
    
    def toggle_logging(self, checked):
        if checked:
            self.csv_file = open(LOG_FILE, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            # Write header with current active channels
            self.csv_writer.writerow(["Timestamp", "Elapsed_s"] + sorted(self.active_channels))
            self.logging = True
            print(f"Logging to {LOG_FILE}")
        else:
            self.logging = False
            if self.csv_file:
                self.csv_file.close()
                self.csv_file = None
            print("Logging stopped")
    
    def update_plot(self):
        if not self.task or not self.active_channels:
            return
        
        try:
            available = self.task.in_stream.avail_samp_per_chan
            if available == 0:
                return
            
            data = self.task.read(number_of_samples_per_channel=available)
            
            # Handle single vs multi-channel
            channels_list = sorted(self.active_channels)
            if len(channels_list) == 1:
                data = [data]
            
            now = datetime.now()
            base_elapsed = (now - self.start_time).total_seconds()
            
            num_samples = len(data[0]) if isinstance(data[0], list) else 1
            
            for i in range(num_samples):
                elapsed = base_elapsed - (num_samples - 1 - i) / SAMPLE_RATE
                self.times.append(elapsed)
                
                for ch_idx, ch in enumerate(channels_list):
                    if isinstance(data[ch_idx], list):
                        temp = data[ch_idx][i]
                    else:
                        temp = data[ch_idx]
                    self.temps[ch].append(temp)
            
            # Update labels with latest values
            for ch in channels_list:
                if len(self.temps[ch]) > 0:
                    latest = self.temps[ch][-1]
                    self.temp_labels[ch].setText(f"{latest:.1f} °C")
            
            # Update plots
            times_array = np.array(self.times)
            for ch in channels_list:
                self.curves[ch].setData(times_array, np.array(self.temps[ch]))
            
            # Auto-scroll x-axis
            if len(times_array) > 0:
                x_max = times_array[-1]
                x_min = max(0, x_max - PLOT_HISTORY / SAMPLE_RATE)
                self.plot_widget.setXRange(x_min, x_max, padding=0.02)
            
            # Log to CSV (only active channels)
            if self.logging and self.csv_writer:
                latest_temps = [self.temps[ch][-1] for ch in channels_list]
                row = [now.isoformat(), f"{base_elapsed:.2f}"] + [f"{t:.2f}" for t in latest_temps]
                self.csv_writer.writerow(row)
                self.csv_file.flush()
                
        except Exception as e:
            print(f"Error: {e}")
    
    def closeEvent(self, event):
        self.timer.stop()
        self.stop_daq()
        if self.csv_file:
            self.csv_file.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ThermocouplePlotter()
    window.show()
    sys.exit(app.exec())