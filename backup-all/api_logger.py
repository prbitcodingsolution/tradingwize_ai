
import logging
import time

class ApiLogger:
    def __init__(self):
        self.logger = logging.getLogger("api_logger")
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        self.logger.addHandler(handler)

    def log_request(self, **kwargs):
        pass

api_logger = ApiLogger()

def log_api_call(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def should_wait_for_rate_limit(api_name):
    return False, 0
