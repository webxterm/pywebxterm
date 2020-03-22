from hashlib import sha1
from base64 import b64encode

HANDSHAKE_RESPONSE_HEADER = \
    'HTTP/1.1 101 Switching Protocols\r\n' \
    'Connection: Upgrade\r\n' \
    'Upgrade: websocket\r\n' \
    'Sec-WebSocket-Accept: {0}\r\n' \
    'WebSocket-Protocal: chat\r\n' \
    '\r\n'


# 和客户端握手
# 参考：https://www.cnblogs.com/ssyfj/p/9245150.html
def handshake(sock, maps):
    """
    :param sock: socket.socket
    :param maps: dict
    :return:
    """
    # 从请求的数据中获取 Sec-WebSocket-Key, Upgrade
    if maps.get("upgrade") is None:
        raise ValueError("Client tried to connect but was missing upgrade!")

    sw_key = maps.get('sec-websocket-key')
    if sw_key is None:
        raise ValueError('Client tried to connect but was missing a key!')

    hash_value = sha1(sw_key.encode() + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
    resp_key = b64encode(hash_value.digest()).strip().decode('ascii')
    resp_body = HANDSHAKE_RESPONSE_HEADER.format(resp_key).encode()
    handshake_done = sock.send(resp_body)

    return handshake_done

