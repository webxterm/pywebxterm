# 将bytes数据转字符串
def decode_utf8(data, flag='ignore', replace_str='?'):
    try:
        return data.decode(encoding='utf-8')
    except UnicodeDecodeError:
        result = ''
        # last_except = False
        for r in iter(data):
            try:
                result += (bytes([r]).decode(encoding='utf-8'))
                # last_except = False
            except UnicodeDecodeError as ude:
                # if last_except is False:
                if flag == 'ignore':
                    result += ''
                elif flag == 'replace':
                    result += replace_str
                    # last_except = True

        return result




b = b'\x1b[22D\xe4\xb8\x1b[7m<\x1b[7m0\x1b[7m0\x1b[7ma\x1b[7md\x1b[7m>\x1b[27m\xe6\x1b[7m<\x1b[7m0\x1b[7m0\x1b[7m9\x1b[7m6\x1b[7m>\x1b[27m\x1b[7m<\x1b[7m0\x1b[7m0\x1b[7m8\x1b[7m7\x1b[7m>\x1b[27m \x08'


print((decode_utf8(b, flag='replace', replace_str='?').encode()))


import argparse
parser = argparse.ArgumentParser("")
parser.add_argument()