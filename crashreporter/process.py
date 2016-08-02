import logging
import multiprocessing
import sys
import traceback

from .tools import analyze_traceback

mp_crash_reporting_enabled = False


def enable_mp_crash_reporting():
    """
    Monkey-patch the multiprocessing.Process class with our own CrashReportingProcess.
    Any subsequent imports of multiprocessing.Process will reference CrashReportingProcess instead.

    This function must be called before any imports to mulitprocessing in order for the monkey-patching to work.
    """
    global mp_crash_reporting_enabled
    multiprocessing.Process = multiprocessing.process.Process = CrashReportingProcess
    mp_crash_reporting_enabled = True


class CrashReportingProcess(multiprocessing.Process):
    """
    Monkey-patch class that replaces Process in the multiprocessing library. It adds the ability to catch any
    uncaught exceptions, serialize the crash report and pipe it through to the main process which can then use
    it's CrashReporter instance to upload the crash report.

    On the main process, calls to CrashReporter.poll() must periodically be called in order to check if there are
    any crash reports waiting in the pipe.
    """
    _crash_reporting = True
    cr_pipes = []

    def __init__(self, *args, **kwargs):
        super(CrashReportingProcess, self).__init__(*args, **kwargs)
        self.cr_remote_conn, self.cr_local_conn = multiprocessing.Pipe(duplex=False)
        CrashReportingProcess.cr_pipes.append((self.cr_remote_conn, self.cr_local_conn))

    def exception_handler(self, e):
        logging.debug('CrashReporter: Crash detected on process {}'.format(self.name))
        etype, evalue, tb = sys.exc_info()
        analyzed_traceback = analyze_traceback(tb)
        logging.debug('CrashReporter: Done analyzing traceback on process {}'.format(self.name))
        logging.debug('CrashReporter: Sending traceback data to main process'.format(self.name))
        try:
            self.cr_local_conn.send((etype.__name__, '%s' % evalue, analyzed_traceback))
        except Exception as e:
            logging.error('CrashReporter: Could not send traceback data to main process.')

    def run(self):
        clsname = self.__class__.__name__
        try:
            logging.debug('{cls}: Starting {cls}: {name}'.format(cls=clsname, name=self.name))
            super(CrashReportingProcess, self).run()
            logging.debug('{cls}: Preparing to exit {cls}: {name}'.format(cls=clsname, name=self.name))
        except Exception as e:
            logging.info('{cls}: Error encountered in {name}'.format(cls=clsname, name=self.name))
            traceback.print_exc()
            self.exception_handler(e)