import tempfile
import time
import random
from crashreporter import CrashReporter
from crashreporter.process import enable_mp_crash_reporting

enable_mp_crash_reporting()
import multiprocessing

tmp = tempfile.mkdtemp('crashreporter')

cr = CrashReporter(report_dir=tmp, config='./test_config.cfg')


def cp_func():
    n = random.randint(1, 1000)
    while 1:
        note = 'This is occuring a separate process'
        local_var = 'This is a test function that will ultimately fail with a divide by zero error'
        result = n / 0
        time.sleep(0.1)

p = multiprocessing.Process(target=cp_func, name='test_crash_on_other_process')

ii = 0
while 1:
    if ii == 0:
        p.start()
    if cr.poll():
        break
    else:
        time.sleep(0.1)
    ii += 1