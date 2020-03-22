import os
import socket
import socketserver
import selectors
import queue
import time
import json
import paramiko

from threading import Thread

from lib.common.properties import Properties
from lib.common.handshake import handshake
from lib.common.message import Message
from lib.common.message import pack_message
from lib.ssh import sshclient
from lib.common.strings import decode_utf8
from lib.server import shutdownserver
from lib.common.iputils import get_real_ip

import logging
from logging.handlers import RotatingFileHandler

from lib.common.logfilter import AccessLogFilter
from lib.common.logfilter import DebugLogFilter
from lib.common.logfilter import ErrorLogFilter

shutdown_bind_address = "localhost"
shutdown_port = 8898

# 128k
socket_buffer_size = 131072
channel_buffer_size = 131072
# 队列是否阻塞，False：否，True：是
queue_blocking = False

access_log = "../logs/access.log"
debug_log = "../logs/debug.log"
error_log = "../logs/error.log"

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
        # 连接数量
        self.id_counter = 0
        self.sd_server = shutdownserver.ShutdownServer(self, (shutdown_bind_address, shutdown_port),
                                                       shutdownserver.ShutdownRequestHandler)
        super().__init__(server_address, handler)

    def new_client(self, handler):
        self.id_counter += 1
        client = {
            'id': self.id_counter,
            'handler': handler,
            'address': handler.client_address
        }
        self.clients.append(client)

    def shutdown_client(self, shutdown_handler):
        self.id_counter -= 1
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


class WebSocketServerRequestHandler(socketserver.BaseRequestHandler):
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
        self.message = Message()
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
    def handshake(self, request_header):
        """
        :param request_header: str
        :return:
        """
        # 从请求的数据中获取 Sec-WebSocket-Key, Upgrade
        sock = self.request  # type: socket.socket

        request, payload = request_header.split("\r\n", 1)

        maps = Properties(separator=':', ignore_case=True).load(payload)  # type: dict

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
            message = self.request.recv(socket_buffer_size)

            if not message:
                logger.debug('client disconnect. received empty data!')
                self.keep_alive = False
                return

            if self.handshake_done is False:
                try:
                    request_header = str(message, encoding='ascii')
                except UnicodeDecodeError as e:
                    logger.error(e)
                    self.keep_alive = False
                    return
                self.handshake(request_header)
            else:
                self.message.reset_pos()
                # 解析文本
                # 在读下一个字符，看看有没有客户端两次传入，一次解析的。
                while self.message.read_bytes(message, 1):
                    self.message.backward_pos()
                    try:
                        decoded = self.message.unpack_message(message)
                        self.handle_decoded(decoded)
                    except ValueError as e:
                        logger.error(e)
                        self.keep_alive = False
                    # print('read next....')

        except (ConnectionAbortedError, ConnectionResetError, TimeoutError) as es:
            # [Errno 54] Connec tion reset by peer
            self.shutdown_request()

    # 向客户端写发送数据
    # 从消息队列中获取数据(self.queue)
    def send_message(self):
        message = b''
        while not self.queue.empty():
            message += self.queue.get_nowait()
        # 从selection中获取数据
        # selection_key = self.selector.get_key(self.request)
        # message = selection_key.data

        presentation = decode_utf8(message, flag='replace', replace_str='?')
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
        if chan.closed is True:
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
            self.ssh_client.new_terminal_shell()
            # 重新注册ssh通道读取事件
            self.selector.register(self.ssh_client.chan, selectors.EVENT_READ)
            return

        if chan.send_ready():
            chan.send(cmd)
            self.heartbeat_time = time.time()
        else:

            ssh = self.ssh_client  # type: ssh.SSHClient
            self.queue.put('packet_write_wait: Connection to {} port {}: Broken pipe'.format(
                ssh.args.get('hostname'), ssh.args('port')))

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
                logger.debug("received heartbeat!")
                self.queue.put(b'\x1b^3;hi!\x1b\\', block=queue_blocking)
                self.reg_send()
                return

            user_data = json.loads(decoded)  # type: dict

            if self.ssh_client is None:
                self.connect_terminal(user_data)
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
                """
                    {
                        chdir: '',
                        chmod: '',
                        chown: '',
                        file: '',
                        get: '',
                        listdir:
                    }
                """
                pass

        except ValueError:
            # 非JSON数据
            # 判断是否为心跳数据
            pass

    # 连接到终端
    def connect_terminal(self, message):

        """
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

            self.ssh_client = sshclient.SSHClient({
                'hostname': target.get('hostname'),
                'port': target.get('port'),
                'username': target.get('username'),
                'password': target.get('password'),
                'width': size.get('w', 80),
                'height': size.get('h', 24),
                'term': message.get('term', 'vt100')
            })

            # 连接失败？
            msg = self.ssh_client.connect()  # type: dict
            if msg is None:
                # 发送版本及加密方式等的信息
                self.queue.put(json.dumps(self.ssh_client.get_ssh_info()).encode(), block=queue_blocking)
                self.reg_send()
            else:
                # 连接错误信息
                self.queue.put(json.dumps(msg).encode(), block=queue_blocking)
                self.reg_send()
                return

            self.ssh_client.new_terminal_shell()
            # 开始心跳的时间
            self.heartbeat_time = time.time()
            # 注册ssh通道读取事件
            self.selector.register(self.ssh_client.chan, selectors.EVENT_READ)

    # 请求结束
    # 释放资源
    def finish(self):
        self.shutdown_request()
