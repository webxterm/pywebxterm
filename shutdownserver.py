import socketserver
from socketserver import TCPServer
from threading import Thread

shutdown_command = b"\x1b[^shutdown\x1b\\"
check_health_command = b'\x1b[^Hello\x1b\\'
reply_health_command = b'\x1b[^Hi\x1b\\'


# websocketserver shutdown的进程
class ShutdownServer(TCPServer):
    def __init__(self, server, server_address, handler):
        self.http = server
        super().__init__(server_address, handler)


class ShutdownRequestHandler(socketserver.BaseRequestHandler):

    # 做出关闭的动作
    def shutdown(self):
        self.server.shutdown()
        # 发出shutdown的命令
        http = self.server.http  # type: BkXtermServer
        http.shutdown()

    def handle(self):
        data = self.request.recv(64)
        if data == shutdown_command:
            # 执行shutdown需要另外开一个进程，不然会造成死锁。
            # 参考：https://blog.csdn.net/candcplusplus/article/details/51794411
            #      结束serve_forever()
            Thread(target=self.shutdown).start()
        elif data == check_health_command:
            # 健康检查，响应客户端
            self.request.send(reply_health_command)
