import struct
import socket
import queue
'''
+-+-+-+-+-------+-+-------------+-------------------------------+
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                     Payload Data continued ...                |
+---------------------------------------------------------------+
'''
FIN = 0x80
OPCODE = 0x0f
MASKED = 0x80
PAYLOAD_LEN = 0x7f
PAYLOAD_LEN_EXT16 = 0x7e
PAYLOAD_LEN_EXT64 = 0x7f


# https://datatracker.ietf.org/doc/rfc6455/?include_text=1
"""Continuation Frame, 连续帧"""
OPCODE_CONTINUATION = 0x00
"""Text Frame，文本帧"""
OPCODE_TEXT = 0x01
"""Binary Frame，二进制帧"""
OPCODE_BINARY = 0x02
"""Connection Close Frame，链接关闭帧"""
CLOSE_CONN = 0x8
"""Ping Frame，ping帧（心跳发起）"""
OPCODE_PING = 0x9
"""Pong Frame，pong帧（心跳回应）"""
OPCODE_PONG = 0xA


# https://blog.csdn.net/yangzai187/article/details/93905594

# 打包消息
# 参考：https://www.cnblogs.com/ssyfj/p/9245150.html
def pack_message(data, opcode=OPCODE_TEXT):
    # 参考 websocket-server模块(pip3 install websocket-server)
    """
    :param data: 需要打包的数据
    :param opcode:  打包类型：OPCODE_TEXT：文本，OPCODE_BINARY：二进制
    :return: bytes
    """
    if opcode == OPCODE_TEXT:
        # 文本
        if isinstance(data, bytes):
            try:
                msg = data.decode('utf-8')
            except UnicodeDecodeError:
                print('Can\'t send message, message is not valid UTF-8!')
                return
        elif isinstance(data, str):
            msg = data
        else:
            msg = str(data)

        payload = msg.encode(encoding='utf-8')

    else:
        payload = data

    header = bytearray()
    header.append(FIN | opcode)

    payload_length = len(payload)
    if payload_length <= 125:
        header.append(payload_length)
    elif 126 <= payload_length <= 65535:
        header.append(PAYLOAD_LEN_EXT16)
        header.extend(struct.pack('>H', payload_length))
    elif payload_length < 18446744073709551616:
        header.append(PAYLOAD_LEN_EXT64)
        header.extend(struct.pack('>Q', payload_length))
    else:
        raise Exception("Message is too big. Consider breaking it into chunks.")

    return header + payload


def unpack_message(rfile):
    """读取消息"""
    b1, b2 = rfile.read(2)
    opcode = b1 & OPCODE
    masked = b2 & MASKED
    payload_length = b2 & PAYLOAD_LEN

    if not b1:
        raise ConnectionError("Client closed connection.")
    elif opcode == CLOSE_CONN:
        raise ConnectionError("Client asked to close connection.")
    if not masked:
        raise ValueError("Client must always be masked.")

    if payload_length == 126:
        # (132,)
        payload_length = struct.unpack('>H', rfile.read(2))[0]
    elif payload_length == 127:
        # (132,)
        payload_length = struct.unpack('>Q', rfile.read(8))[0]

    masks = rfile.read(4)

    decoded = bytearray()
    for c in rfile.read(payload_length):
        c ^= masks[len(decoded) % 4]
        decoded.append(c)

    return opcode, decoded
