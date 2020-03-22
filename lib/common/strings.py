# 将bytes数据转字符串
def decode_utf8(data, flag='ignore', replace_str=''):
    try:
        return data.decode(encoding='utf-8')
    except UnicodeDecodeError:
        result = ''
        last_except = False
        for r in iter(data):
            try:
                result += (bytes([r]).decode(encoding='utf-8'))
                last_except = False
            except UnicodeDecodeError as ude:
                if last_except is False:
                    if flag == 'ignore':
                        result += ''
                    elif flag == 'replace':
                        result += replace_str
                    last_except = True

        return result
