import socketserver
import selectors
import time
import json
import paramiko
import logging

import os
import sys

from threading import Thread
from logging.handlers import RotatingFileHandler
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../')
root_path = os.path.dirname(os.path.abspath(__file__)) + '/../../'

from ..common.properties import Properties
from ..common.handshake import handshake
from ..common.message import *
from ..common.strings import decode_utf8
from ..common.iputils import get_real_ip

from ..ssh.sshclient import SSHClient
from ..ssh.sftp import SFTPClient

from ..server import shutdownserver

from ..common.logfilter import AccessLogFilter
from ..common.logfilter import DebugLogFilter
from ..common.logfilter import ErrorLogFilter

shutdown_bind_address = "localhost"
shutdown_port = 8898

# 128k
socket_buffer_size = 131072
channel_buffer_size = 524288
# 队列是否阻塞，False：否，True：是
queue_blocking = False

access_log = root_path + "logs/access.log"
debug_log = root_path + "logs/debug.log"
error_log = root_path + "logs/error.log"

access_log_format = "%(remoteAddress)s - \"%(user)s\" - [%(asctime)s] - \"%(request)s\" " \
                    "- %(status)d - \"%(httpUserAgent)s\" - \"%(message)s\""
debug_log_format = '%(asctime)s - %(module)s.%(funcName)s[line:%(lineno)d] - %(levelname)s: %(message)s'
error_log_format = '%(asctime)s - %(module)s.%(funcName)s[line:%(lineno)d] - %(levelname)s: %(message)s'

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

accessLoggerHandler = RotatingFileHandler(access_log)
accessLoggerHandler.setLevel(logging.INFO)
accessLoggerHandler.setFormatter(logging.Formatter(access_log_format))
# accessLoggerHandler.addFilter(lambda record: record.levelno == logging.INFO)
accessLoggerHandler.addFilter(AccessLogFilter())

debugLoggerHandler = RotatingFileHandler(debug_log)
debugLoggerHandler.setLevel(logging.DEBUG)
debugLoggerHandler.setFormatter(logging.Formatter(debug_log_format))
# debugLoggerHandler.addFilter(lambda record: record.levelno == logging.DEBUG)
debugLoggerHandler.addFilter(DebugLogFilter())

errorLoggerHandler = RotatingFileHandler(debug_log)
errorLoggerHandler.setLevel(logging.DEBUG)
errorLoggerHandler.setFormatter(logging.Formatter(debug_log_format))
errorLoggerHandler.addFilter(ErrorLogFilter())

logger.addHandler(accessLoggerHandler)
logger.addHandler(debugLoggerHandler)
logger.addHandler(errorLoggerHandler)

if hasattr(os, "fork"):
    from socketserver import ForkingTCPServer

    _TCPServer = ForkingTCPServer
else:
    from socketserver import ThreadingTCPServer

    _TCPServer = ThreadingTCPServer


# web socket 服务器
# Unix... Mix-in class to handle each request in a new process.
# Windows... Mix-in class to handle each request in a new thread.
class WebSocketServer(_TCPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler):
        # 连接的客户端
        self.clients = []
        self.sd_server = shutdownserver.ShutdownServer(self, (shutdown_bind_address, shutdown_port),
                                                       shutdownserver.ShutdownRequestHandler)
        super().__init__(server_address, handler)

    def new_client(self, handler):
        client = {
            'handler': handler,
            'address': handler.client_address
        }
        self.clients.append(client)

    def shutdown_client(self, shutdown_handler):
        for client in self.clients:
            handler = client['handler']  # type: WebSocketServerRequestHandler
            if handler == shutdown_handler:
                self.clients.remove(client)
                break

    def server_activate(self):
        super().server_activate()
        self.sd_server.server_activate()

    def run_sd_server(self):
        self.sd_server.serve_forever(0.5)

    def shutdown(self):
        for client in self.clients:
            handler = client['handler']  # type: WebSocketServerRequestHandler
            handler.shutdown_request()
        super().shutdown()

    def serve_forever(self, poll_interval=0.5):
        Thread(target=self.run_sd_server).start()
        print('Server started.')
        super().serve_forever(poll_interval)

    def handle_request(self):
        print(self)
        super().handle_request()


class WebSocketServerRequestHandler(socketserver.StreamRequestHandler):
    def __init__(self, request, client_address, server):
        self.keep_alive = True
        self.ssh_client = None
        self.sftp_client = None

        self.handshake_done = False  # 是否握手成功
        self.selector = selectors.DefaultSelector()
        # 默认注册请求读取事件
        self.selector.register(request, selectors.EVENT_READ)
        self.reg_selector = None
        self.heartbeat_time = None
        self.queue = queue.Queue()  # 消息队列，主要用于ssh服务器返回的数据缓冲。

        super().__init__(request, client_address, server)

    # 注册从客户端中接收
    def reg_read(self):
        self.selector.modify(self.request, selectors.EVENT_READ)

    # 注册发送给客户端
    def reg_send(self):
        self.selector.modify(self.request, selectors.EVENT_WRITE)

    # 和客户端握手
    # 参考：https://www.cnblogs.com/ssyfj/p/9245150.html
    def handshake(self, request, maps):
        """
        :param request: str
        :param maps: dict
        :return:
        """
        # 从请求的数据中获取 Sec-WebSocket-Key, Upgrade
        sock = self.request  # type: socket.socket

        try:
            self.handshake_done = handshake(self.request, maps)

            if self.handshake_done > 0:
                self.server.new_client(self)

                ip = get_real_ip(maps)
                if not ip or ip == "unknown":
                    ip = sock.getpeername()[0]

                logger.info('handshake success...', extra={
                    "remoteAddress": ip,
                    "user": "-",
                    "request": request,
                    "status": 200,
                    "httpUserAgent": maps.get("user-agent")
                })

            else:
                self.keep_alive = False

        except ValueError as ve:
            logger.error(ve)

    # 读取客户端传过来的数据
    def read_message(self):
        try:
            # 客户端

            # data = b''
            # while True:
            #     chunk = self.request.recv(socket_buffer_size)
            #     data += chunk
            #     if len(chunk) < socket_buffer_size:
            #         break

            # if not data:
            #     logger.debug('client disconnect. received empty data!')
            #     self.keep_alive = False
            #     return

            if self.handshake_done is False:

                data = self.request.recv(1024)

                try:
                    request_header = str(data, encoding='ascii')
                except UnicodeDecodeError as e:
                    logger.error(e)
                    self.keep_alive = False
                    return

                request, payload = request_header.split("\r\n", 1)
                maps = Properties(separator=':', ignore_case=True).load(payload)  # type: dict
                self.handshake(request, maps)

            else:
                """int, bytearray"""
                opcode = None
                decoded = None
                try:
                    opcode, decoded = unpack_message(self.rfile)
                    # opcode, decoded = self.read_next_message()
                except (ConnectionError, ValueError) as e:
                    self.keep_alive = False
                    logger.error(e)

                if opcode is None:
                    pass
                elif opcode == OPCODE_TEXT:
                    """文本"""
                    self.handle_decoded(str(decoded, encoding="utf-8"))
                elif opcode == OPCODE_BINARY:
                    """
                    二进制数据，主要是上传文件
                    => 从客户端传输过来的二进制包，需要直接传递给服务器端
                    
                    """

                    def on_put_callback(transferred_bytes,
                                        current_bytes, total_bytes, consume_seconds, remote_path, file_name):
                        # 本次传输的字节数
                        response_msg = {
                            "sftp": 1,
                            "type": "put",
                            "path": remote_path,
                            "name": file_name,
                            "tx": transferred_bytes,
                            "ctx": current_bytes,
                            "file_size": total_bytes,
                            "consume_seconds": "%d" % consume_seconds
                        }
                        self.send_message(response_msg)

                    def on_finish_callback(consume_seconds, total_bytes):
                        self.response_log_message("文件传输成功，传输了 %d 字节 (用时%d 秒)" % (total_bytes, consume_seconds))

                    sftp = self.sftp_client  # type: SFTPClient
                    sftp.put(bytes(decoded), callback=on_put_callback, finish_callback=on_finish_callback)
                    pass
                elif opcode == OPCODE_PING:
                    """ping"""
                    pass
                elif opcode == OPCODE_PONG:
                    """pong"""
                    pass

        except (ConnectionAbortedError, ConnectionResetError, TimeoutError):
            # [Errno 54] Connec tion reset by peer
            self.shutdown_request()

    # 向客户端写发送数据
    # 从消息队列中获取数据(self.queue)
    def send_message(self, data=None):

        if not data:
            message = b''
            while not self.queue.empty():
                message += self.queue.get_nowait()
            presentation = decode_utf8(message, flag='replace', replace_str='?')
            print("presentation")
            print(presentation.encode())
        else:
            if isinstance(data, dict):
                presentation = json.dumps(data).encode()
            else:
                presentation = data

        payload = pack_message(presentation)
        try:
            self.request.send(payload)
        except BrokenPipeError as bpe:
            # 发送失败，可能客户端已经异常断开。
            logger.error('BrokenPipeError: {}'.format(bpe))
            # 取消ssh-chan注册
            try:
                self.selector.unregister(self.ssh_client.chan)
            except KeyError:
                # 当read_channel_message取消注册后，再次取消注册会抛出错误
                pass
            finally:
                self.shutdown_request()

        self.heartbeat_time = time.time()
        # 将事件类型改成selectors.EVENT_READ
        # 切换到读取的功能
        self.reg_read()

    # 响应连接断开信息
    def resp_closed_message(self, flag):
        try:
            chan = self.ssh_client.chan  # type: paramiko.Channel
            self.selector.unregister(chan)
        except KeyError:
            pass
        # '\x1b^exit\x07'
        logger.debug("{} 连接已断开。按回车键重新连接... ".format(flag))
        self.queue.put((flag + '连接已断开。按回车键重新连接...\r\n').encode('utf-8'), block=queue_blocking)
        self.reg_send()

    # 从ssh通道中获取数据
    def packet_read_wait(self):
        chan = self.ssh_client.chan  # type: paramiko.Channel

        data = None
        if chan.recv_stderr_ready():
            logger.debug("recv_stderr_ready: {}".format(chan.recv_stderr(4096)))

        elif chan.recv_ready():
            try:
                data = chan.recv(channel_buffer_size)
            except socket.timeout as st:
                logger.debug("read_channel_message: {}".format(st))
        elif chan.recv_exit_status():
            logger.debug("recv_exit_status: {}".format(chan.recv_exit_status()))
            # 取消注册选择器，防止循环输出。
            self.resp_closed_message('\x1b^0\x07')
            chan.close()
        elif chan.closed is True:
            # 取消注册选择器，防止循环输出。
            self.resp_closed_message('\x1b^1\x07')

        if data is not None and len(data) > 0:
            logger.debug("channel data: {}".format(data))

            self.queue.put(data, block=queue_blocking)
            # 将事件类型改成selectors.EVENT_WRITE
            # 切换到写入的功能
            # self.selector.modify(self.request, selectors.EVENT_WRITE, data=data)
            self.reg_send()

    # 向通道发送数据
    def packet_write_wait(self, cmd):
        """
        :param cmd: str
        """
        chan = self.ssh_client.chan  # type: paramiko.Channel
        if chan and chan.closed is True:
            # 取消注册ssh通道读取事件
            try:
                self.selector.unregister(chan)
            except KeyError:
                # 当read_channel_message取消注册后，再次取消注册会抛出错误
                pass

            logger.debug("正在重新连接...")
            self.queue.put('正在重新连接...\r\n\r\n'.encode('utf-8'), block=queue_blocking)
            self.reg_send()

            # 重新创建终端。
            error_msg = self.ssh_client.new_terminal_shell()
            if error_msg is not None:
                self.queue.put(json.dumps(error_msg).encode('utf-8'), block=queue_blocking)
                self.reg_send()
                return

            # 重新注册ssh通道读取事件
            self.selector.register(self.ssh_client.chan, selectors.EVENT_READ)
            return

        if chan.send_ready():
            chan.send(cmd)
            self.heartbeat_time = time.time()
        else:

            ssh = self.ssh_client  # type: SSHClient
            self.queue.put('packet_write_wait: Connection to {} port {}: Broken pipe'.format(
                ssh.args.get('hostname'), ssh.args['port']))

    # shutdown请求
    def shutdown_request(self):
        logger.debug('shutdown request...')
        self.keep_alive = False
        try:
            ssh = self.ssh_client.ssh  # type: paramiko.SSHClient
            chan = self.ssh_client.chan  # type: paramiko.Channel
            chan.shutdown(socket.SHUT_RDWR)
            chan.close()
            ssh.close()
        except AttributeError:
            pass

        self.selector.close()
        server = self.server  # type: WebSocketServer
        server.shutdown_client(self)

    # 处理请求
    def handle(self):

        while self.keep_alive:

            selection_keys = self.selector.select()

            for key, events in selection_keys:

                if key.fileobj == self.request:
                    if events == selectors.EVENT_READ:
                        # 从客户端中读取
                        self.read_message()
                    elif events == selectors.EVENT_WRITE:
                        # 发送数据给客户端
                        self.send_message()
                elif key.fileobj == self.ssh_client.chan:
                    if events == selectors.EVENT_READ:
                        # 从ssh通道读取数据
                        self.packet_read_wait()

    # 处理解码后的文本
    def handle_decoded(self, decoded):
        """
        :param decoded: str
        """
        if decoded is None:
            return
        try:
            # 通过私钥解密数据
            # try:
            #     source = rsa.decrypt(decoded.encode(), decode_pri_key).decode()
            # except rsa.DecryptionError as de:
            #     print(de)
            #     return

            if decoded == '\x1b^hello!\x1b\\':
                # 心跳
                if not self.ssh_client.connected:
                    # 发送date命令给服务器。
                    self.finish()
                    return

                logger.debug("received heartbeat!")
                self.queue.put(b'\x1b^3;hi!\x1b\\', block=queue_blocking)
                self.reg_send()
                return

            user_data = json.loads(decoded)  # type: dict

            if self.ssh_client is None:
                if "sftp" in user_data:
                    """sftp"""
                    self.connect(user_data)

                else:
                    """字符终端"""
                    self.connect_terminal(user_data)

            if not self.ssh_client.connected:
                print("连接失败。。。")
                return
            if 'size' in user_data:

                size = user_data.get('size')
                width = size.get('w', 80)
                height = size.get('h', 24)

                if self.ssh_client.chan is not None:
                    self.ssh_client.chan.resize_pty(width=width, height=height)

                logger.debug("update size: width:{}, height:{}".format(width, height))

            if 'cmd' in user_data:
                cmd = user_data.get('cmd')
                if cmd:
                    self.packet_write_wait(cmd)

            if 'sftp' in user_data:
                print("user_data:", user_data)
                """
                    action: {
                        chdir: '',
                        chmod: '',
                        chown: '',
                        file: '',
                        get: '',
                        put: '',
                        listdir:
                    },
                    packet: '',
                    path: '',
                    size: '',
                    name: ''
                """
                if not self.sftp_client:
                    """初始化"""
                    ssh = self.ssh_client.ssh  # type: paramiko.SSHClient
                    sftp = paramiko.SFTPClient.from_transport(ssh.get_transport())
                    self.sftp_client = SFTPClient(sftp)

                sftp_json = user_data.get('sftp')  # type: dict
                if sftp_json:

                    if "put" in sftp_json:
                        """上传文件"""
                        self.response_log_message("开始上传 “{}”".format(sftp_json.get("name")))
                        self.sftp_client.file_name = sftp_json.get("name")
                        self.sftp_client.put_left_packet(
                            packet=sftp_json.get("packet"),
                            remote_path=sftp_json.get("put"),
                            file_size=sftp_json.get("size"))

                    elif "listdir" in sftp_json:
                        """列出目录文件"""

                        ret = []
                        listdir = sftp_json.get("listdir", ".")
                        if sftp_json.get("input", False):
                            """判断是否在输入框中输入，还是直接点击目录"""
                            self.response_command_log_message("cd {}".format(listdir))
                        try:
                            """改变当前的目录"""
                            self.sftp_client.sftp.chdir(listdir)
                        except FileNotFoundError:
                            self.response_error_log_message("文件或目录 “{}” 不存在".format(listdir))
                            self.response_error_log_message("读取目录列表失败")
                            return

                        """获取当前的工作目录"""
                        cwd = self.sftp_client.sftp.getcwd()

                        self.response_log_message("正在读取 “{}” 目录列表... ".format(cwd))
                        listdir_attr = self.sftp_client.sftp.listdir_attr()
                        self.response_log_message("正在列出目录 “{}”... ".format(cwd))

                        for file in listdir_attr:
                            ret.append({
                                "longName": file.longname,
                                "mode": file.st_mode & 0o170000,
                                "name": file.filename,
                                "modifyTime": file.st_mtime,
                            })
                        self.response_log_message("列出目录 “{}” 成功".format(cwd))

                        sftp_message = {
                            "data": ret,
                            "type": "listdir",
                            "sftp": 1,
                            "cwd": self.sftp_client.sftp.getcwd()
                        }

                        self.send_message(sftp_message)

                    elif "get" in sftp_json:
                        """下载文件"""
                        file_name = sftp_json.get("get", None)
                        if not file_name:
                            self.response_error_log_message("get “{}” ".format(file_name))
                            return
                        # 获取主机名
                        # hostname = self.ssh_client.args["hostname"]
                        # 文件远程路径
                        remote_path = os.path.join(self.sftp_client.sftp.getcwd(), file_name)

                        self.response_command_log_message("get “{}” => [BLOB](内存)".format(file_name))
                        self.response_command_log_message("remote:{} => local:[BLOB](内存)".format(remote_path))

                        def get_file_transform(data):
                            payload = pack_message(data, OPCODE_BINARY)
                            self.request.send(payload)

                        def get_file_callback(transferred_bytes, current_transferred_bytes, file_size, consume_seconds):
                            response_msg = {
                                "sftp": 1,
                                "type": "get",
                                "path": remote_path,
                                "name": file_name,
                                "tx": transferred_bytes,
                                "ctx": current_transferred_bytes,
                                "file_size": file_size,
                                "consume_seconds": "%d" % consume_seconds
                            }
                            self.send_message(response_msg)

                        def finish_callback(cost_seconds, file_size):
                            self.response_log_message("文件传输成功，传输了 %d 字节 (用时%d 秒)" % (file_size, cost_seconds))

                        self.sftp_client.get(remote_path,
                                             transform=get_file_transform,
                                             # buffer_size=1024*1024,
                                             callback=get_file_callback,
                                             finish_callback=finish_callback)

        except ValueError:
            # 非JSON数据
            # 判断是否为心跳数据
            pass

    def response_command_log_message(self, msg, extra=None):
        self.response_log_message(msg, -logging.INFO, "命令", extra)

    def response_error_log_message(self, msg, extra=None):
        self.response_log_message(msg, logging.ERROR, "错误", extra)

    def response_log_message(self, msg: str, level: int = logging.INFO, title: str = "状态", extra=None):
        """
        响应日志消息
        :param extra:
        :param title:
        :param level:
        :param msg:
        :return:
        """
        sftp_message = {
            "sftp": 1,
            "type": "message",
            "level": level,
            "title": title,
            "message": msg
        }

        if extra is not None:
            for name in extra:
                sftp_message[name] = extra.get(name)

        self.send_message(json.dumps(sftp_message).encode())

    def connect(self, message):
        """
        连接到终端
        :param message: dict
        """
        target = message.get('target')  # type: dict
        logger.debug(self.request.getpeername())
        logger.debug(message)

        if target is None:
            logger.debug('无效的主机信息！！！')
        else:
            # 连接终端
            size = message.get('size')
            if size is None:
                size = {}

            self.ssh_client = SSHClient({
                'hostname': target.get('hostname'),
                'port': target.get('port', 22),
                'username': target.get('username'),
                'password': target.get('password'),
                'width': size.get('w', 80),
                'height': size.get('h', 24),
                'term': message.get('term', 'vt100')
            })

            if "sftp" in message:
                self.response_log_message("正在连接 {}:{}... ".format(target.get('hostname'), target.get('port', 22)))

            # 连接失败？
            msg = self.ssh_client.connect()  # type: dict
            if msg is None:
                # 发送版本及加密方式等的信息
                resp = json.dumps(self.ssh_client.get_ssh_info()).encode()

                if "sftp" in message:
                    """返回连接状态"""
                    sftp_message = {
                        "sftp": 1,
                        "type": "message",
                        "level": logging.INFO,
                        "title": "状态",
                        "message": "已连接到 {}".format(target.get('hostname'))
                    }
                    resp += json.dumps(sftp_message).encode()

                self.send_message(resp)

            else:
                # 连接错误信息
                self.send_message(msg)
                return

    # 连接到终端
    def connect_terminal(self, message):

        self.connect(message)

        error_msg = self.ssh_client.new_terminal_shell()
        if error_msg is not None:
            self.queue.put(json.dumps(error_msg).encode('utf-8'), block=queue_blocking)
            self.reg_send()
            return

        # 开始心跳的时间
        self.heartbeat_time = time.time()
        # 注册ssh通道读取事件
        self.selector.register(self.ssh_client.chan, selectors.EVENT_READ)

    # 请求结束
    # 释放资源
    def finish(self):
        self.shutdown_request()

    # def read_next_message(self):
    #     """读取消息"""
    #     b1, b2 = self.rfile.read(2)
    #     opcode = b1 & OPCODE
    #     masked = b2 & MASKED
    #     payload_length = b2 & PAYLOAD_LEN
    #
    #     if not b1:
    #         logger.error("Client closed connection.")
    #         self.keep_alive = False
    #         return None, None
    #     elif opcode == CLOSE_CONN:
    #         logger.error("Client asked to close connection.")
    #         self.keep_alive = False
    #         return opcode, None
    #     if not masked:
    #         logger.error("Client must always be masked.")
    #         self.keep_alive = False
    #         return opcode, None
    #
    #     if payload_length == 126:
    #         # (132,)
    #         payload_length = struct.unpack('>H', self.rfile.read(2))[0]
    #     elif payload_length == 127:
    #         # (132,)
    #         payload_length = struct.unpack('>Q', self.rfile.read(8))[0]
    #
    #     masks = self.rfile.read(4)
    #
    #     decoded = bytearray()
    #     for c in self.rfile.read(payload_length):
    #         c ^= masks[len(decoded) % 4]
    #         decoded.append(c)
    #
    #     return opcode, decoded
