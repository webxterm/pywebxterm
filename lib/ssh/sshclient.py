import paramiko
import socket


# 检查SSH的版本号
def check_banner(version):
    seg = version.split("-", 2)
    if len(seg) < 3:
        raise ValueError("Invalid SSH banner")
    version = seg[1]
    client = seg[2]
    if version != "1.99" and version != "2.0":
        msg = "Incompatible version ({} instead of 2.0)"
        raise ValueError(msg.format(version))
    return version, client


# SSH客户端
class SSHClient:

    def __init__(self, args=None, heartbeat=30):
        """

        :param args:
        :param heartbeat: 心跳时间
        """
        self.ssh = paramiko.SSHClient()
        self.ssh.load_system_host_keys()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)

        self.heartbeat = heartbeat
        self.chan = None
        self.args = args  # type: dict
        self.connected = False

    # 连接终端
    def connect(self):

        error_msg = None
        try:
            hostname = self.args.get("hostname")
            port = self.args.get("port", 22)
            username = self.args.get("username")
            password = self.args.get("password")

            if not hostname:
                error_msg = {'status': 'fail',
                             'e': 'HostName',
                             'zh_msg': '无效的主机名',
                             'en_msg': 'invalid hostname!'}
                return error_msg

            if not username:
                error_msg = {'status': 'fail',
                             'e': 'UserName',
                             'zh_msg': '无效的用户名',
                             'en_msg': 'invalid username!'}
                return error_msg

            """更改握手超时时间，避免握手超过15秒抛出EOFError"""
            handshake_timeout = self.args.get("handshake_timeout", 120)

            """
            修复已知问题：
            See: https://github.com/paramiko/paramiko/issues/1629
            """
            transport = paramiko.Transport((hostname, port))
            transport.handshake_timeout = handshake_timeout
            transport.connect(username=username, password=password)
            self.ssh._transport = transport
            self.connected = True

        except paramiko.BadHostKeyException:
            error_msg = {'status': 'fail',
                         'e': 'BadHostKey',
                         'zh_msg': '无法验证服务器的主机密钥',
                         'en_msg': 'the server\'s host key could not be verified'}
        except paramiko.AuthenticationException:
            error_msg = {'status': 'fail',
                         'e': 'Authentication',
                         'zh_msg': '身份验证失败',
                         'en_msg': 'authentication failed'}
        except paramiko.SSHException:
            error_msg = {'status': 'fail',
                         'e': 'SSH',
                         'zh_msg': '连接或建立会话时出现其他错误，请检查主机名或端口。',
                         'en_msg': 'there was any other error connecting or establishing an SSH session'}
        except socket.error:
            error_msg = {'e': 'socket.error',
                         'zh_msg': '连接时发生套接字错误',
                         'en_msg': 'socket error occurred while connecting'}

        return error_msg

    # 获取ssh通道
    def new_terminal_shell(self):

        if self.ssh.get_transport() is None:
            error_msg = {'status': 'fail',
                         'e': 'Server Network not ready',
                         'zh_msg': '服务器网络未就绪',
                         'en_msg': 'Server Network not ready'}
            return error_msg

        if self.ssh.get_transport().is_active() is False:
            # session不活跃
            # 需要重新连接
            self.connect()

        width = self.args.get("width")
        height = self.args.get("height")
        term = self.args.get("term")

        self.chan = self.ssh.invoke_shell(term=term,
                                          width=width,
                                          height=height)  # type: paramiko.Channel
        # 如果设置了env
        # self.chan.send('export LANG=zh_CN.UTF-8\r')

        self.chan.setblocking(True)
        self.chan.send_exit_status(0)

    # 创建终端
    def new_terminal(self):
        self.connect()
        self.new_terminal_shell()

    # 获取SSH版本号
    def get_ssh_info(self):
        # 获取版本号
        transport = self.ssh.get_transport()  # type: paramiko.Transport

        remote_version, remote_client = check_banner(transport.remote_version)

        return {
            'status': 'success',
            'version': remote_version,
            'cipher': transport.remote_cipher
        }
