import logging


class AccessLogFilter(logging.Filter):

    def filter(self, record):
        if record.levelno != logging.INFO:
            return 0
        return 1


class DebugLogFilter(logging.Filter):

    def filter(self, record):
        if record.levelno != logging.DEBUG:
            return 0
        return 1

