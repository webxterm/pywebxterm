# 读取Properties配置文件
class Properties:

    def __init__(self, file=None, separator="=", ignore_case=False):
        self.properties = {}
        self.lines = None
        self.separator = separator
        self.ignore_case = ignore_case

        if file is not None:
            with open(file) as f:
                self.lines = f.readlines()

    def load(self, lines=None):
        if lines is not None:
            self.lines = lines.split('\n')
        chunk = ""
        for line in self.lines:
            if len(line) == 0 or line[0] == '#':
                continue
            if line[-1] == "\r" or line[-1] == "\n":
                line = line[0:-1]
                if len(line) == 0:
                    continue
            if line[-1] == '\\':
                chunk += line[0:-1].strip()
                continue
            if len(chunk) > 0:
                # 处理多行的情况
                line = chunk + line.strip()
                chunk = ""

            ss = line.strip().split(self.separator, 1)
            v1 = '' if len(ss) == 1 else ss[1]
            k1 = ss[0].lower() if self.ignore_case is True else ss[0]
            self.properties[k1.strip()] = v1.strip()
        return self.properties
