import paramiko
import time
import io
import os

# print("默认缓冲区大小：{}".format(io.DEFAULT_BUFFER_SIZE))
#
begin = time.time()
#
ssh = paramiko.SSHClient()
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)

# hostname = "192.168.46.133"
hostname = "192.168.0.106"
port = 22
username = "baikai"
password = "x+y-1=0?x&y"

# 修复已知问题：
# See: https://github.com/paramiko/paramiko/issues/1629
transport = paramiko.Transport((hostname, port))
transport.handshake_timeout = 120
transport.connect(username=username, password=password)
print("已连接，消耗{}秒".format(time.time() - begin))
ssh._transport = transport

sftp = paramiko.SFTPClient.from_transport(transport)


def callback(transferred_bytes, current_bytes, total_bytes):
    # 本次传输的字节数
    print("transferred_bytes:{}, current_bytes:{}, total_bytes:{}".format(transferred_bytes, current_bytes, total_bytes))


#
#
# file = open("/Users/fei00/Downloads/VirtualBox-6.0.14-133895-OSX.dmg", "rb")
# file.seek(0, 2)
# file_size = file.tell()
# file.seek(0)
#
# sftp.putfo(file, "VirtualBox-6.0.14-133895-OSX.dmg", file_size=file_size, callback=callback)
# file.close()

buffer = b''  # type: bytes

#

print(type(buffer))

with open("/Users/fei00/Downloads/ACTIVATION_CODE.txt", "rb") as fl:
    local_file_size = fl.seek(0, 2)
    fl.seek(0)
    buffer += fl.read(local_file_size)

buffer2 = bytearray(buffer)  # type: bytearray
buffer3 = bytes(buffer2)


class SFTPClient:

    def __init__(self):
        self.buffer_size = io.DEFAULT_BUFFER_SIZE
        self.transferred_bytes = 0
        self.fr = None
        self.fr_stat = None
        self.pos = 0

    def put(self, from_bytes: bytes, remote_path: str, file_size: int = 0, callback=None):
        chunk_len = len(from_bytes)

        if file_size == 0:
            raise EOFError("file_size is 0")

        if self.transferred_bytes == 0 or chunk_len == file_size:
            # 第一次传输
            self.fr = sftp.open(remote_path, "wb")
            self.fr.set_pipelined(True)
            self.fr.write(from_bytes)

        else:
            # 剩余文件字节传输
            # x = chunk_len
            # y = 0
            # while True:
            #     if x > self.buffer_size:
            #         self.fr.write(from_bytes[y: y + self.buffer_size])
            #         x -= self.buffer_size
            #         y += self.buffer_size
            #     else:
            #         self.fr.write(from_bytes[y:])
            #         break
            self.fr.write(from_bytes)

        self.transferred_bytes += chunk_len
        self.fr.flush()
        if callback is not None:
            callback(self.transferred_bytes, chunk_len, file_size)

    def stat(self):
        return self.fr.stat()

    def read_bytes(self, buf, n):
        if self.pos >= len(buf):
            return b""
        chunk = buf[self.pos: self.pos + n]
        self.pos += n
        return chunk


client = SFTPClient()
client.buffer_size = 1024 * 1024 * 5

fl = open("/Users/fei00/Downloads/cn_windows_10_enterprise_ltsc_2019_x64_dvd_9c09ff24.iso", "rb")
file_size = fl.seek(0, 2)
fl.seek(0)
while True:
    data = fl.read(client.buffer_size)
    if not data:
        break
    client.put(data, "cn_windows_10_enterprise_ltsc_2019_x64_dvd_9c09ff24.iso", file_size, callback=callback)

# remote_file = sftp.open("ACTIVATION_CODE.txt", "wb")
# # remote_file.set_pipelined(True)
# # local_file.seek(0)
# # remote_file.seek(0)
# print(buffer3[0:1024])
# remote_file.write(buffer3[0:1024])
# remote_file.flush()
# remote_file.close()
#
# remote_file2 = sftp.open("ACTIVATION_CODE.txt", "ab")
# # remote_file.set_pipelined(True)
# # local_file.seek(0)
# # remote_file.seek(0)
# print(buffer3[1024:2048])
# remote_file2.write(buffer3[1024:2048])
# remote_file2.flush()
# remote_file2.close()

#
# file_size = local_file.seek(0, 2)
#
#
#
# with sftp.open("cn_windows_10_enterprise_ltsc_2019_x64_dvd_9c09ff24.iso", "wb") as fr:
#     fr.set_pipelined(True)
#     # fr.seek()
#     fr.write(local_file.read(16777216))
#     fr.flush()
# #
# with sftp.open("cn_windows_10_enterprise_ltsc_2019_x64_dvd_9c09ff24.iso", "ab") as fr:
#     fr.set_pipelined(True)
#     fr.prefetch(file_size)
#     print(fr.tell())
#     # fr.seek()
#     fr.write(local_file.read(16777216))
#     fr.flush()
#
# with sftp.open("nmap.dmg", "wb+") as fr:
#     fr.set_pipelined(True)
#     # fr.seek()
#     fr.write(local_file.read(16777216))
#     fr.flush()

# with sftp.open("nmap.dmg", "wb+") as fr:
#     fr.set_pipelined(True)
#     # fr.seek()
#     fr.write(local_file.read(16777216))
#     fr.flush()

# buffer.write(local_file.read())
# remote_file.write(buffer.read())
# remote_file.flush()

# local_file.close()
