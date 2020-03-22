import struct

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

OPCODE_TEXT = 0x01
CLOSE_CONN = 0x8


# 打包消息
# 参考：https://www.cnblogs.com/ssyfj/p/9245150.html
def pack_message(message):
    # 参考 websocket-server模块(pip3 install websocket-server)
    """
    :param message: str
    :return: bytes
    """
    if isinstance(message, bytes):
        try:
            message = message.decode('utf-8')
        except UnicodeDecodeError:
            print('Can\'t send message, message is not valid UTF-8!')
            return
    elif isinstance(message, str):
        pass
    else:
        message = str(message)

    header = bytearray()
    header.append(FIN | OPCODE_TEXT)

    payload = message.encode(encoding='utf-8')
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


# 客户端消息处理
class Message:

    def __init__(self):
        self.read_pos = 0

    def reset_pos(self):
        if self.read_pos != 0:
            self.read_pos = 0

    def backward_pos(self):
        self.read_pos -= 1

    # 消息解包
    # struct.pack struct.unpack
    # https://blog.csdn.net/qq_30638831/article/details/80421019
    # 参考：https://www.cnblogs.com/ssyfj/p/9245150.html
    def unpack_message(self, message):
        """
        :param message: bytes
        :return: str
        """
        b1, b2 = self.read_bytes(message, 2)
        # fin = b1 & FIN
        opcode = b1 & OPCODE
        masked = b2 & MASKED
        payload_length = b2 & PAYLOAD_LEN

        if not b1 or opcode == CLOSE_CONN:
            raise ValueError('Client closed connection.')

        if not masked:
            raise ValueError('Client must always be masked.')

        if payload_length == 126:
            # (132,)
            payload_length = struct.unpack('>H', self.read_bytes(message, 2))[0]
        elif payload_length == 127:
            # (132,)
            payload_length = struct.unpack('>Q', self.read_bytes(message, 8))[0]

        masks = self.read_bytes(message, 4)

        decoded = bytearray()
        for c in self.read_bytes(message, payload_length):
            c ^= masks[len(decoded) % 4]
            decoded.append(c)
        return str(decoded, encoding='utf-8')

    # 读取字节
    def read_bytes(self, data, num):
        """
        :param data: bytes
        :param num: int
        :return: bytes
        """
        bs = data[self.read_pos:num + self.read_pos]
        self.read_pos += num
        return bs



