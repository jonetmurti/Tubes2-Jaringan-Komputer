import sys
import wave
from packet import Packet, PacketType
import socket
import threading
import time
import struct

class Server:
    PACKET_SIZE = 32774
    CHUNK_SIZE = 1024
    TIMEOUT = 0.5
    CLIENT_TIMEOUT = 10
    ANNOUNCEMENT_TIME = 1

    def __init__(self, ip, port, filename):
        # TODO : Find out how to calculate chunk time
        # Initialize socket
        self.ip = ip
        self.port = port
        self.listener_sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )
        self.listener_sock.bind((self.ip, self.port))
        self.listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.listener_sock.setblocking(False)

        # Initialize wave file to be sent
        self.wf = wave.open(filename, "rb")
        self.audio_length = self.wf.getnframes()/self.wf.getframerate()
        self.chunk_time = self.get_chunk_time(self.wf)

        # Initialize start variable
        self.start = False
        self.start_lock = threading.Lock()

        # Initialize packets
        self.meta_packet = self.create_metapacket()
        # self.packet_dict = self.create_packet_dict()
        self.global_packet = None
        self.packet_lock = threading.Lock()

        # Initialize receiver receive and send queue (for queueing packet)
        self.receive_queue = {}
        self.send_queue = {}

        # Initialize subscribers dict
        self.subscribe_dict = {}
        self.subscribe_lock = threading.Lock()

        # Initialize receiver thread list
        self.receiver_thread = []

    def __del__(self):
        self.listener_sock.close()
        self.wf.close()

    def valid_init_msg(self, address):
        ip = address[0]
        port = address[1]
        self.subscribe_lock.acquire()
        if ip in self.subscribe_dict:
            if port in self.subscribe_dict[ip]:
                self.subscribe_lock.release()
                return False
        else:
            self.subscribe_dict[ip] = {}
        # Save subscribe time
        self.subscribe_dict[ip][port] = time.time()
        self.subscribe_lock.release()

        return True

    def listen(self):
        start_time = time.time()
        announce_time = time.time()
        client_id = 0

        announcement_packet = Packet(
            PacketType.ANNOUNCEMENT
        )
        
        while time.time() - start_time <= self.audio_length:
            # print("audio length:", self.audio_length)
            # print("time elapsed:", time.time() - start_time)
            try:
                init_msg, address = self.listener_sock.recvfrom(self.PACKET_SIZE)
                if (self.valid_init_msg(address)):
                    # self.subscribe_dict[address.ip][address.port] = None
                    new_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_id, address,)
                    )
                    self.receiver_thread.append(new_thread)

                    new_thread.start()

                    client_id += 1
                else:
                    print("client already subscribed")
            except:
                pass
            finally:
                if time.time() - announce_time >= self.ANNOUNCEMENT_TIME:
                    for port in range(5000, 5101):
                        if port != self.port:
                            self.listener_sock.sendto(announcement_packet.to_bin(), ('<broadcast>', port))

                    announce_time = time.time()

            '''
                Alternative algorithm :
                if address not in self.subscriber_queue:
                    lock
                    create receive_queue data (input subscibed time as first elmt)
                    create send_queue data
                    release
                    create thread
                    add thread to thread list

                lock
                push msg to queue
                relase

                for each client in send_queue:
                    if queue not empty:
                        send popped data from send_queue for client
            '''

        print("waiting for client thread to finish...")

        for t in self.receiver_thread:
            t.join()

    def handle_client(self, id, address):
        print("handling client:", id)

        handler_sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )
        handler_sock.settimeout(self.TIMEOUT)
        current_packet = self.meta_packet

        succ = False
        retry = 0
        while not succ and retry <= 5:
            succ = self.send(handler_sock, self.meta_packet, address)
            retry += 1

        start = False
        if succ:
            client_to_timer = time.time()
            while not start and (time.time() - client_to_timer <= self.CLIENT_TIMEOUT):
                self.start_lock.acquire()
                start = self.start
                self.start_lock.release()

        while succ and start:

            self.packet_lock.acquire()
            current_packet = self.global_packet
            self.packet_lock.release()

            if not current_packet:
                break

            start_time = self.get_current_time()
        
            self.send(handler_sock, current_packet, address)

            end_time = self.get_current_time()

            delta = end_time - start_time

            if delta < self.chunk_time:
                time.sleep((self.chunk_time - delta) * 0.001)

        if not succ:
            print("Unable to connect to client:", id)
        elif not start:
            print("Server failed to start audio:", id)
        
        handler_sock.close()
        print("closing thread", id)

        # self.subscribe_lock.acquire()
        # ip = address[0]
        # port = address[1]
        # del self.subscribe_dict[ip][port]
        # if not self.subscribe_dict[ip]:
        #     del self.subscribe_dict[ip]
        # self.subscribe_lock.release()

    def send(self, sock, send_packet, address):
        start_time = self.get_current_time()
        while True:

            sock.sendto(send_packet.to_bin(), address)

            try:
                msg, address = sock.recvfrom(Server.PACKET_SIZE)

                rec_packet = Packet()
                rec_packet.parse(msg)

                if rec_packet.checksum_correct():
                    if rec_packet.packet_type == PacketType.ACK and rec_packet.sequence_number == send_packet.sequence_number:
                        return True
                    elif rec_packet.packet_type == PacketType.FIN_ACK:
                        return True
            except:
                pass

            finally:
                if self.get_current_time() - start_time >= self.chunk_time:
                    return False

    def iterate_audio(self):
        seq_num = 1
        first_run = True

        print("playing audio...")

        while True:
            start_time = self.get_current_time()

            data = self.wf.readframes(self.CHUNK_SIZE)

            if not data:
                self.global_packet = None
                break

            self.packet_lock.acquire()
            self.global_packet = Packet(
                PacketType.DATA,
                len(data),
                seq_num,
                data
            )
            self.packet_lock.release()

            end_time = self.get_current_time()

            if first_run:
                self.start_lock.acquire()
                self.start = True
                self.start_lock.release()
                first_run = False

            # print("playing chunk number:", seq_num)

            seq_num += 1
            delta = end_time - start_time

            if delta < self.chunk_time:
                time.sleep((self.chunk_time - delta) * 0.001)

        print("stopping audio...")
        print("total audio chunk:", seq_num)

    def get_current_time(self):
        # get current time in milliseconds
        return int(round(time.time() * 1000))

    def get_chunk_time(self, wf):
        # returns chunk time in milliseconds
        frame_size = wf.getnchannels()*wf.getsampwidth()
        frame_per_chunk = self.CHUNK_SIZE/frame_size

        num_of_packet = int(wf.getframerate() / self.CHUNK_SIZE * self.audio_length) + 1

        return 1000*(self.audio_length/num_of_packet)

    def create_metapacket(self):
        metadata = struct.pack(
            "4s2s2s", 
            self.wf.getframerate().to_bytes(4, byteorder="big"), 
            self.wf.getnchannels().to_bytes(2, byteorder="big"),
            self.wf.getsampwidth().to_bytes(2, byteorder="big")
        )

        metapacket = Packet(
            PacketType.DATA,
            len(metadata),
            0,
            metadata
        )

        return metapacket

    def create_packet_dict(self):
        # Create packet list based on subscribe time
        return {}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Error:", "Needs 2 arguments (port, filename)")
        sys.exit(-1)

    server = Server(socket.gethostbyname(socket.gethostname()), int(sys.argv[1]), sys.argv[2])

    print("listening on port " + str(server.port) + "...")

    audio_iterator = threading.Thread(target=server.iterate_audio)
    audio_iterator.start()
    server.listen()
    audio_iterator.join()

    print("closing server...")