from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
import sys
import threading
import time
from client import Client
import math

class ReceiveDataThread(QThread):
    finished = Signal()

    def __init__(self, client, event):
        super(ReceiveDataThread, self).__init__()

        self.client = client
        self.event = event

    def run(self):
        self.client.receive_data(self.event)

        # self.finished.emit()

class PlayAudioThread(QThread):
    finished = Signal()

    def __init__(self, client, event, next_packet, ratio):
        super(PlayAudioThread, self).__init__()

        self.client = client
        self.event = event
        self.next_packet = next_packet
        self.ratio = ratio

    def run(self):
        self.event.clear()

        self.client.play_audio_v2(self.next_packet, self.ratio, self.event)

        # self.finished.emit()

class AudioPlayer(QMainWindow):

    def __init__(self, client):

        super().__init__()
        self.client = client

        self.receive_event = threading.Event()
        self.player_event = threading.Event()
        self.receiver_thread = ReceiveDataThread(self.client, self.receive_event)
        self.receiver_thread.start()
        # self.receiver_thread = QThread()
        # self.receiver = ReceiveDataThread(self.client, self.receive_event)
        # self.receiver.moveToThread(self.receiver_thread)
        # self.receiver_thread.started.connect(self.receiver.run)
        # self.receiver.finished.connect(self.receiver_thread.quit)
        # self.receiver.finished.connect(self.receiver.deleteLater)
        # self.receiver_thread.finished.connect(self.receiver_thread.deleteLater)
        # self.receiver_thread.start()

        self.setWindowTitle(self.client.metadata["filename"])

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.client.metadata["audio_length"])
        self.cur_val = -1

        self.current_time = QLabel('0')
        self.total_time = QLabel(str(client.metadata["audio_length"]))
        self.slider.valueChanged.connect(self.on_value_change)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)

        self.slider_layout = QHBoxLayout()
        self.slider_layout.addWidget(self.current_time)
        self.slider_layout.addWidget(self.slider)
        self.slider_layout.addWidget(self.total_time)

        self.layout = QVBoxLayout()
        self.layout.addLayout(self.slider_layout)

        widget = QWidget()
        widget.setLayout(self.layout)
        self.setCentralWidget(widget)

        self.resize(500,100)

        while self.client.first_run:
            time.sleep(0.1)

        self.slider.setValue(self.client.first_second)
        self.create_audio_player(0, 0.0)
        # self.timer()

    def timer(self):
        # TODO : check if gui already terminated
        if self.slider.value() == self.audio_length:
            pass
        else:
            threading.Timer(1.0, self.timer).start()
            self.slider.setValue(self.cur_val + 1)
            self.cur_val += 1
            
    def on_value_change(self):
        size = self.slider.value()
        self.current_time.setText(str(size))

    def on_slider_pressed(self):
        # TODO : turn off timer
        try:
            self.player_event.set()
        except Exception as e:
            print("Error : ", e)

    def create_audio_player(self, next_packet, ratio):
        self.audio_thread = PlayAudioThread(self.client, self.player_event, next_packet, ratio)
        self.audio_thread.start()

    def on_slider_released(self):
        sec_to_packet = self.slider.value()*self.client.metadata["num_of_packet"]/self.client.metadata["audio_length"]
        next_packet = int(sec_to_packet) + 1 - self.client.first_packet
        ratio = math.modf(sec_to_packet)[0]
        buf_len = self.client.get_buffer_len()
        if next_packet >= 0 and next_packet < buf_len:
            self.create_audio_player(next_packet, ratio)
            # TODO : create new timer
        elif next_packet < 0:
            print("Error :", "Can only play from", self.client.first_second, "second(s)")
        else:
            print("Error :", "Data not available")

    def closeEvent(self, event):

        self.receive_event.set()
        self.player_event.set()

        while not self.receiver_thread.wait(1):
            pass

        while not self.audio_thread.wait(1):
            pass

        self.client.terminate()
        event.accept()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print()
        print("Error :", "Needs at 1 argument (port)")
        print()
        sys.exit(-1)

    try:
        port = int(sys.argv[1])
        if port < 5000 or port > 5100:
            print("port ....")
            sys.exit(-1)
    except:
        print("port must be an integer")
        sys.exit(-1)

    print("starting client on port {}...".format(port))
    try:
        client = Client(port)
        if client.initiate():
            print("starting gui...")
            app = QApplication(sys.argv)
            window = AudioPlayer(client)
            window.show()
            sys.exit(app.exec_())
    except Exception as e:
        print("Error :", e)