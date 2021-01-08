import socket
from packet import Packet, PacketType
import os
import sys
import pyaudio
import threading
import time
import signal

class Client:

    PACKET_SIZE = 32774
    RECEIVER_TIMEOUT = 5

    def __init__(self, port):

        self.ip = socket.gethostbyname(socket.gethostname())
        self.port = port

        self.rec_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )
        self.rec_socket.bind((self.ip, self.port))
        self.rec_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # init buffer that will contain audio data (chunk)
        self.audio_buffer = []
        self.buffer_len = 0
        self.buffer_lock = threading.Lock()

        self.audio_player = pyaudio.PyAudio()
        self.first_run = True

    def __del__(self):
        try:
            self.rec_socket.close()
        except Exception as e:
            print("Error destructor :", e)
        print("closing client...")

    def interrupt(self, signum, stack_frame):
        try:
            self.rec_socket.close()
        except Exception as e:
            print("Error destructor :", e)
        print("sleeping...")
        print("interrupted")

    def find_server(self):
        self.rec_socket.settimeout(self.RECEIVER_TIMEOUT)
        retry = 0

        while retry < 100:
            try:
                msg, address = self.rec_socket.recvfrom(self.PACKET_SIZE)

                rec_packet = Packet()
                rec_packet.parse(msg)

                if rec_packet.packet_type == PacketType.ANNOUNCEMENT:
                    self.server_address = address
                    return True

                retry += 1
            except:
                return False

        return False

    def receive_metadata(self):
        retry = 0
        init_packet = Packet()

        self.rec_socket.settimeout(0.1)
        while retry < 100:
            try:
                self.rec_socket.sendto(init_packet.to_bin(), self.server_address)

                announcement = True
                i = 0
                while announcement:
                    msg, address = self.rec_socket.recvfrom(self.PACKET_SIZE)

                    rec_packet = Packet()
                    rec_packet.parse(msg)
                    seq_num = int.from_bytes(rec_packet.sequence_number, "big")
                    
                    announcement = rec_packet.packet_type == PacketType.ANNOUNCEMENT

                if seq_num == 0:
                    ack_packet = Packet(
                            packet_type = PacketType.ACK,
                            sequence_number = seq_num
                        )

                    self.rec_socket.sendto(ack_packet.to_bin(), address)

                    self.metadata = rec_packet.get_metadata()

                    return True

            except:
                retry += 1

        return False

    def receive_data(self, event):
        self.rec_socket.settimeout(10)
        last_seq_num = 0
        audio_thread = None

        while not event.is_set():
            try:
                announcement = True
                i = 0
                while announcement:
                    msg, address = self.rec_socket.recvfrom(self.PACKET_SIZE)

                    rec_packet = Packet()
                    rec_packet.parse(msg)
                    
                    announcement = rec_packet.packet_type == PacketType.ANNOUNCEMENT

                if rec_packet.checksum_correct():
                    seq_num = int.from_bytes(rec_packet.sequence_number, "big")
                    ack_packet = Packet(
                            packet_type = PacketType.ACK,
                            sequence_number = seq_num
                        )

                    self.rec_socket.sendto(ack_packet.to_bin(), address)

                    if seq_num > last_seq_num:
                        self.buffer_lock.acquire()
                        self.audio_buffer.append(rec_packet.data)
                        self.buffer_len = len(self.audio_buffer)
                        self.buffer_lock.release()
                        last_seq_num = seq_num
                        if self.first_run:
                            self.first_run = False

            except:
                break

    def play_audio(self, packet_played, stream, event):
        # TODO : modified play_audio

        data = None
        packet = packet_played
        retry = 0
        while not event.is_set() and retry < 100:
            play = False
            self.buffer_lock.acquire()
            if self.buffer_len > packet:
                data = self.audio_buffer[packet]
                packet += 1
                play = True
            self.buffer_lock.release()

            if play:
                retry = 0
                stream.write(bytes(data))
            else:
                retry += 1
                time.sleep(0.1)

    def process(self):
        if self.find_server():
            if self.receive_metadata():
                print("playing audio...")

                stream = self.audio_player.open(
                    format = self.audio_player.get_format_from_width(self.metadata["sampwidth"]),
                    channels = self.metadata["channel"],
                    rate = self.metadata["framerate"],
                    output = True)
                
                receiver_event = threading.Event()
                receiver_thread = threading.Thread(
                    target=self.receive_data,
                    args=(receiver_event,)
                )
                receiver_thread.start()

                while self.first_run:
                    time.sleep(0.1)

                packet_played = 0

                while True:
                    rewind_event = threading.Event()
                    audio_thread = threading.Thread(
                        target=self.play_audio,
                        args=(packet_played, stream, rewind_event,)
                    )
                    audio_thread.start()

                    accepted = False
                    while not accepted:
                        try:
                            packet_played = int(input("input packet to rewind (-1 to terminate):"))
                            self.buffer_lock.acquire()
                            buf_len = self.buffer_len
                            self.buffer_lock.release()
                            if packet_played < -1:
                                print("Error :", "< -1 not allowed")
                                continue
                            elif packet_played >= buf_len:
                                print("Error :", "data not available")
                                continue
                            accepted = True
                        except:
                            print("input must be an integer")

                    rewind_event.set()
                    audio_thread.join()

                    if packet_played == -1:
                        break

                stream.stop_stream()
                self.audio_player.terminate()
                receiver_event.set()
                receiver_thread.join()


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
        signal.signal(signal.SIGINT, client.interrupt)
        client.process()
    except Exception as e:
        print("Error :", e)