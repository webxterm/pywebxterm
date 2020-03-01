import socket
import platform
import sys
import websocketserver
from threading import Thread

shutdown_bind_address = "localhost"
shutdown_port = 8898
bind_address = "0.0.0.0"
port = 8899

shutdown_command = b"\x1b[^shutdown\x1b\\"
check_health_command = b'\x1b[^Hello\x1b\\'
reply_health_command = b'\x1b[^Hi\x1b\\'

__author__ = 'lbk <baikai.liao@qq.com>'
__version__ = '0.3'
__status__ = "production"
__date__ = "2019-11-18(created) -> 2020-02-10(updated)"


# 创建一个客户端，与服务器进行通讯，发送关闭服务器的指令，让服务器执行shutdown()。
def shutdown():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect((shutdown_bind_address, shutdown_port))
            sock.sendall(shutdown_command)
        except ConnectionRefusedError:
            print('ERROR: Could not contact [%s:%s]. Server may not be running.'
                  % (shutdown_bind_address, shutdown_port))


# 检查主服务器的健康状态
def check_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect((shutdown_bind_address, shutdown_port))
            sock.sendall(check_health_command)
            if sock.recv(64) == reply_health_command:
                print('Server running...')
        except ConnectionRefusedError:
            print('Server not running!')


# 启动服务器
def startup():
    # 打印相关信息
    # print_base_info()
    # 初始化服务器
    server = websocketserver.WebSocketServer((bind_address, port), websocketserver.WebSocketServerRequestHandler)
    # 查看端口是否被占用
    server.server_activate()
    # 不是Windows系统的话，切换到守护进程
    # if hasattr(os, "fork"):
    #    daemon(get_pid_file())
    # 启动服务器
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('shutdown server...')

        def shutdown_server():
            server.sd_server.shutdown()
            server.shutdown()

        Thread(target=shutdown_server).start()

    # try:
    #     os.remove(get_pid_file())
    # except FileNotFoundError:
    #     pass


# 关闭服务器
# def kill():
#     if os.path.exists(get_pid_file()) is False:
#         print("PID file not exists!")
#         return
#     with open(get_pid_file()) as f:
#         pid = f.read()
#     try:
#         os.kill(int(pid), signal.SIGTERM)
#     except ProcessLookupError as ple:
#         print(ple)
#     finally:
#         try:
#             os.remove(get_pid_file())
#         except OSError:
#             pass


if __name__ == '__main__':

    if len(sys.argv) > 1:
        commands = sys.argv[-1]
        if commands == 'start':
            startup()
        elif commands == 'run':
            startup()
        elif commands == 'stop':
            shutdown()
        # elif commands == 'stop-force':
        #     kill()
        elif commands == 'version':
            # print_base_info()
            try:
                fs = platform.platform().split('-')
                os_name = fs[0]
                os_version = fs[1]
                architecture = fs[2]
            except ValueError as e:
                os_name = platform.platform(aliased=True, terse=True)
                os_version = platform.version()
                architecture = platform.architecture()[0]

            print('Server version: ', __version__)
            print('OS Name:        ', os_name)
            print('OS Version:     ', os_version)
            print('Architecture:   ', architecture)
            print('Python build:   ', platform.python_build()[0])
        elif commands == 'status':
            # print_base_info()
            # print('Using server pid file:   ', get_pid_file())
            # if os.path.exists(get_pid_file()):
            #     with open(get_pid_file()) as pf:
            #         print('Using PID:               ', pf.read())
            # #
            # print('Using server bind:       ', bind_address)
            # print('Using server port:       ', port)
            # print('Using server sd port:    ', shutdown_port)
            check_server()
        else:
            print('Usage: xterm ( commands ... )')
            print('commands:')
            print('  run:        Start Server in the current window')
            print('  start:      Start Server in a separate window')
            print('  stop:       Stop Server, waiting up to 5 seconds for the process to end')
            print('  status:     View running Server status')
            print('  version:    What version of server are you running?')
    else:
        startup()
