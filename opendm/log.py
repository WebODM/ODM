import sys
import threading
import os
import json
import datetime
import shutil
import multiprocessing
from functools import lru_cache

from opendm.arghelpers import double_quote, args_to_dict
from vmem import virtual_memory

if sys.platform == 'win32' or os.getenv('no_ansiesc'):
    # No colors on Windows (sorry !) or existing no_ansiesc env variable 
    HEADER = ''
    OKBLUE = ''
    OKGREEN = ''
    DEFAULT = ''
    WARN = ''
    FAIL = ''
    ENDC = ''
else:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    DEFAULT = '\033[39m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

lock = threading.Lock()

@lru_cache(maxsize=None)
def get_version():
    with open(os.path.join(os.path.dirname(__file__), "..", "VERSION")) as f:
        return f.read().split("\n")[0].strip()

def memory():
    mem = virtual_memory()
    return {
        'total': round(mem.total / 1024 / 1024),
        'available': round(mem.available / 1024 / 1024)
    }

class Logger:
    def __init__(self):
        self.json = None
        self.json_output_file = None
        self.start_time = datetime.datetime.now()

    def log(self, startc, msg, level_name):
        level = "[" + level_name + "]"
        with lock:
            print("%s%s %s%s" % (startc, level, msg, ENDC))
            sys.stdout.flush()
            if self.json is not None:
                self.json['stages'][-1]['messages'].append({
                    'message': msg,
                    'type': level_name.lower()
                })
    
    def init_json_output(self, output_files, args):
        self.json_output_files = output_files
        self.json_output_file = output_files[0]
        self.json = {}
        self.json['odmVersion'] = get_version() # deprecated
        self.json['engine'] = 'ODX'
        self.json['version'] = get_version()
        self.json['memory'] = memory()
        self.json['cpus'] = multiprocessing.cpu_count()
        self.json['images'] = -1
        self.json['options'] = args_to_dict(args)
        self.json['startTime'] = self.start_time.isoformat()
        self.json['stages'] = []
        self.json['processes'] = []
        self.json['success'] = False

    def log_json_stage_run(self, name, start_time):
        if self.json is not None:
            self.json['stages'].append({
                'name': name,
                'startTime': start_time.isoformat(),
                'messages': [],
            })
    
    def log_json_images(self, count):
        if self.json is not None:
            self.json['images'] = count
    
    def log_json_stage_error(self, error, exit_code, stack_trace = ""):
        if self.json is not None:
            self.json['error'] = {
                'code': exit_code,
                'message': error
            }
            self.json['stackTrace'] = list(map(str.strip, stack_trace.split("\n")))
            self._log_json_end_time()

    def log_json_success(self):
        if self.json is not None:
            self.json['success'] = True
            self._log_json_end_time()
    
    def log_json_process(self, cmd, exit_code, output = []):
        if self.json is not None:
            d = {
                'command': cmd,
                'exitCode': exit_code,
            }
            if output:
                d['output'] = output

            self.json['processes'].append(d)

    def _log_json_end_time(self):
        if self.json is not None:
            end_time = datetime.datetime.now()
            self.json['endTime'] = end_time.isoformat()
            self.json['totalTime'] = round((end_time - self.start_time).total_seconds(), 2)

            if self.json['stages']:
                last_stage = self.json['stages'][-1]
                last_stage['endTime'] = end_time.isoformat()
                start_time = datetime.datetime.fromisoformat(last_stage['startTime'].replace("Z", "+00:00"))
                last_stage['totalTime'] = round((end_time - start_time).total_seconds(), 2)
            
    def info(self, msg):
        self.log(DEFAULT, msg, "INFO")

    def warning(self, msg):
        self.log(WARN, msg, "WARNING")

    def error(self, msg):
        self.log(FAIL, msg, "ERROR")

    def exception(self, msg):
        self.log(FAIL, msg, "EXCEPTION")

    def close(self):
        if self.json is not None and self.json_output_file is not None:
            try:
                with open(self.json_output_file, 'w') as f:
                    f.write(json.dumps(self.json, indent=4))
                for f in self.json_output_files[1:]:
                    shutil.copy(self.json_output_file, f)
            except Exception as e:
                print("Cannot write log.json: %s" % str(e))

logger = Logger()

INFO = logger.info
WARNING = logger.warning
ERROR = logger.error
EXCEPTION = logger.exception
