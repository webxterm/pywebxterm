import paramiko
import io
import time


class SFTPClient:

    def __init__(self, sftp):
        self.buffer_size = 32768
        self.transferred_bytes = 0
        self.fr = None
        self.sftp = sftp  # type: paramiko.SFTPClient
        self.remote_path = None
        self.file_size = 0
        self.file_name = None
        self.begin_transferred_time = None

    def put_left_packet(self, packet: bytes, remote_path: str = None, file_size: int = 0, callback=None):
        """
        推送第一个数据包
        :param packet: 数据包
        :param remote_path: 目标路径
        :param file_size: 文件大小
        :param callback: 回调函数
        :return:
        """
        self.remote_path = remote_path
        self.file_size = file_size
        if isinstance(packet, str):
            return
        self.put(packet, callback)

    def put(self, packet: bytes, callback=None, finish_callback=None):
        """
        推送数据到目标服务器
        :param packet: 文件数据包
        :param callback: 回调函数
        :param finish_callback: 回调函数
        :return:
        """

        if self.begin_transferred_time is None:
            self.begin_transferred_time = time.time()

        packet_size = len(packet)

        if packet_size == 0:
            return

        if self.transferred_bytes == 0 or packet_size == self.file_size:
            """第一次传输，需要打开文件"""
            self.fr = self.sftp.open(self.remote_path, "wb")
            self.fr.set_pipelined(True)

        """剩余字节传输"""
        while True:
            chunk = packet[0:self.buffer_size]
            self.fr.write(chunk)

            chunk_size = len(chunk)
            self.transferred_bytes += chunk_size

            if callback is not None:
                callback(self.transferred_bytes, chunk_size, self.file_size,
                         (time.time() - self.begin_transferred_time), self.remote_path, self.file_name)

            if packet_size == self.buffer_size or chunk_size < self.buffer_size:
                break
            else:
                packet = packet[self.buffer_size:]

        if self.transferred_bytes == self.file_size:
            """文件传输完成"""
            if finish_callback is not None:
                finish_callback(time.time() - self.begin_transferred_time, self.file_size)
            self.completed()

    def completed(self):
        """传输完成"""
        self.fr.close()
        self.transferred_bytes = 0
        self.file_name = None
        self.begin_transferred_time = None

    def stat(self):
        """获取远程文件的信息"""
        return self.fr.stat()

    def get(self, remote_path: str,
            transform=None,
            buffer_size=32768,
            callback=None,
            finish_callback=None):
        """获取远程的文件"""
        file_size = self.sftp.stat(remote_path).st_size
        size = 0
        start = time.time()

        if callback is not None:
            callback(size, 0, file_size, 0)

        with self.sftp.open(remote_path, "rb") as fr:
            fr.prefetch(file_size)
            while True:
                data = fr.read(buffer_size)
                current_size = len(data)
                if current_size == 0:
                    break
                size += current_size
                if transform is not None:
                    transform(data)

                if callback is not None:
                    callback(size, current_size, file_size, (time.time() - start))
        """传输完成"""
        if finish_callback is not None:
            finish_callback(time.time() - start, file_size)
