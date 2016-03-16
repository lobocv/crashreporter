__author__ = 'calvin'

import ConfigParser
import datetime
import glob
import json
import logging
import os
import re
import shutil
import smtplib
import sys
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from threading import Thread

import jinja2

from api import upload_report, upload_many_reports, HQ_DEFAULT_TIMEOUT, SMTP_DEFAULT_TIMEOUT
from tools import analyze_traceback


class CrashReporter(object):
    """
    Create a context manager that emails or uploads a report to a webserver (HQ) with the traceback on a crash.
    It can be setup to do both, or just one of the upload methods.

    If a crash report fails to upload, the report is saved locally to the `report_dir` directory. The next time the
    CrashReporter starts up, it will attempt to upload all offline reports every `check_interval` seconds. After a
    successful upload the offline reports are deleted. A maximum of `offline_report_limit` reports are saved at any
    time. Reports are named crashreport01, crashreport02, crashreport03 and so on. The most recent report is always
    crashreport01.

    Report Customizing Attributes:

    application_name: Application name as a string to be included in the report
    application_version: Application version as a string to be included in the report
    user_identifier: User identifier as a string to add to the report
    offline_report_limit: Maximum number of offline reports to save.
    max_string_length: Maximum string length for values returned in variable inspection. This prevents reports which
                       contain array data from becoming too large.
    inspection_level: The number of traceback objects (from most recent) to inspect for source code, local variables etc

    :param report_dir: Directory to save offline reports.
    :param watcher: Enable a thread that periodically checks for any stored offline reports and attempts to send them.
    :param check_interval: How often the watcher will attempt to send offline reports.
    :param logger: Optional logger to use.
    :param config: Path to configuration file that defines the arguments to setup_smtp and setup_hq. The file has the
                   format of a ConfigParser file with sections [SMTP] and [HQ]

    """
    _report_name = "crash_report_%d"
    html_template = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'email_report.html')
    active = False
    application_name = None
    application_version = None
    user_identifier = None
    offline_report_limit = 10
    max_string_length = 1000
    obj_ref_regex = re.compile("[A-z]+[0-9]*\.(?:[A-z]+[0-9]*\.?)+(?!\')")

    def __init__(self, report_dir=None, config='', logger=None, activate=True,
                 watcher=True, check_interval=5*60):
        self.logger = logger if logger else logging.getLogger(__name__)
        # Setup the directory used to store offline crash reports
        self.report_dir = report_dir
        self.check_interval = check_interval
        self.watcher_enabled = watcher
        self._watcher = None
        self._watcher_running = False
        self.etype = None
        self.evalue = None
        self.tb = None
        self.payload = None
        self._excepthook = None
        self.inspection_level = 1
        self._smtp = None
        self._hq = None
        # Load the configuration from a file if specified
        if os.path.isfile(config):
            self.load_configuration(config)
        if activate:
            self.enable()

    def setup_smtp(self, host, port, user, passwd, recipients, **kwargs):
        """
        Set up the crash reporter to send reports via email using SMTP

        :param host: SMTP host
        :param port: SMTP port
        :param user: sender email address
        :param passwd: sender email password
        :param recipients: list or comma separated string of recipients
        """
        self._smtp = kwargs
        self._smtp.update({'host': host, 'port': port, 'user': user, 'passwd': passwd, 'recipients': recipients})
        try:
            self._smtp['timeout'] = int(kwargs.get('timeout', SMTP_DEFAULT_TIMEOUT))
        except Exception as e:
            logging.error(e)
            self._smtp['timeout'] = None
        self._smtp['from'] = kwargs.get('from', user)

    def setup_hq(self, server, **kwargs):
        self._hq = kwargs
        try:
            self._hq['timeout'] = int(kwargs.get('timeout', HQ_DEFAULT_TIMEOUT))
        except Exception as e:
            logging.error(e)
            self._hq['timeout'] = None
        self._hq.update({'server': server})

    def enable(self):
        """
        Enable the crash reporter. CrashReporter is defaulted to be enabled on creation.
        """
        if not CrashReporter.active:
            CrashReporter.active = True
            # Store this function so we can set it back if the CrashReporter is deactivated
            self._excepthook = sys.excepthook
            sys.excepthook = self.exception_handler
            self.logger.info('CrashReporter: Enabled')
            if self.report_dir:
                if os.path.exists(self.report_dir):
                    if self.get_offline_reports():
                        # First attempt to send the reports, if that fails then start the watcher
                        self.submit_offline_reports()
                        remaining_reports = self.delete_offline_reports()
                        if remaining_reports and self.watcher_enabled:
                            self.start_watcher()
                else:
                    os.makedirs(self.report_dir)

    def disable(self):
        """
        Disable the crash reporter. No reports will be sent or saved.
        """
        if CrashReporter.active:
            CrashReporter.active = False
            # Restore the original excepthook
            sys.excepthook = self._excepthook
            self.stop_watcher()
            self.logger.info('CrashReporter: Disabled')

    def start_watcher(self):
        """
        Start the watcher that periodically checks for offline reports and attempts to upload them.
        """
        if self._watcher and self._watcher.is_alive:
            self._watcher_running = True
        else:
            self.logger.info('CrashReporter: Starting watcher.')
            self._watcher = Thread(target=self._watcher_thread, name='offline_reporter')
            self._watcher.setDaemon(True)
            self._watcher_running = True
            self._watcher.start()

    def stop_watcher(self):
        """
        Stop the watcher thread that tries to send offline reports.
        """
        if self._watcher:
            self._watcher_running = False
            self.logger.info('CrashReporter: Stopping watcher.')

    def exception_handler(self, etype, evalue, tb):
        """
        Catches crashes/ un-caught exceptions. Creates and attempts to upload the crash reports. Calls the default
        exception handler (sys.__except_hook__) upon completion.

        :param etype: Exception type
        :param evalue: Exception value
        :param tb: Traceback
        :return:
        """
        if etype:
            self.etype = etype
            self.evalue = evalue
            self.tb = tb
            self.payload = self.generate_payload()

            if CrashReporter.active:
                # Attempt to upload the report
                hq_success = smtp_success = False
                if self._hq is not None:
                    hq_success = self.hq_submit(self.payload)
                    if hq_success:
                        self.payload['HQ Submission'] = 'Sent'
                if self._smtp is not None:
                    # Send the report via email
                    smtp_success = self.smtp_submit(self.subject(), self.body(self.payload), self.attachments())
                    if smtp_success:
                        self.payload['SMTP Submission'] = 'Sent'

            if not CrashReporter.active or (self._smtp and not smtp_success) or (self._hq and not hq_success):
                # Only store the offline report if any of the upload methods fail, or if the Crash Reporter was disabled
                report_path = self.store_report(self.payload)
                self.logger.info('Offline Report stored %s' % report_path)
        else:
            self.logger.info('CrashReporter: No crashes detected.')

        # Call the default exception hook
        sys.__excepthook__(etype, evalue, tb)

    def generate_payload(self):
        dt = datetime.datetime.now()
        payload = {'Error Type': self.etype.__name__,
                   'Error Message': '%s' % self.evalue,
                   'Application Name': self.application_name,
                   'Application Version': self.application_version,
                   'User': self.user_identifier,
                   'Date': dt.strftime('%d %B %Y'),
                   'Time': dt.strftime('%I:%M %p'),
                   'Traceback': analyze_traceback(self.tb),
                   'HQ Submission': 'Not sent' if self._hq else 'Disabled',
                   'SMTP Submission': 'Not sent' if self._smtp else 'Disabled'
                   }
        return payload

    def load_configuration(self, config):
        cfg = ConfigParser.ConfigParser()

        with open(config, 'r') as _f:
            cfg.readfp(_f)
            if cfg.has_section('General'):
                general = dict(cfg.items('General'))
                self.application_name = general.get('application_name', CrashReporter.application_name)
                self.application_version = general.get('application_version', CrashReporter.application_version)
                self.user_identifier = general.get('user_identifier', CrashReporter.user_identifier)
                self.offline_report_limit = general.get('offline_report_limit', CrashReporter.offline_report_limit)
                self.max_string_length = general.get('max_string_length', CrashReporter.max_string_length)
            if cfg.has_section('SMTP'):
                self.setup_smtp(**dict(cfg.items('SMTP')))
                if 'port' in self._smtp:
                    self._smtp['port'] = int(self._smtp['port'])
                if 'recipients' in self._smtp:
                    self._smtp['recipients'] = self._smtp['recipients'].split(',')

            if cfg.has_section('HQ'):
                self.setup_hq(**dict(cfg.items('HQ')))

    def subject(self):
        """
        Return a string to be used as the email subject line.
        """
        if self.application_name and self.application_version:
            return 'Crash Report - {name} (v{version})'.format(name=self.application_name,
                                                               version=self.application_version)
        else:
            return 'Crash Report'

    def body(self, payload):
        return self.render_report(payload, inspection_level=self.inspection_level)

    def render_report(self, payload, inspection_level=1):
        with open(self.html_template, 'r') as _f:
            template = jinja2.Template(_f.read())

        return template.render(info=payload,
                               inspection_level=inspection_level)

    def attachments(self):
        """
        Generate and return a list of attachments to send with the report.
        :return: List of strings containing the paths to the files.
        """
        return []

    def delete_offline_reports(self):
        """
        Delete all stored offline reports
        :return: List of reports that still require submission
        """
        reports = self.get_offline_reports()
        remaining_reports = reports[:]
        for report in reports:
            with open(report, 'r') as _f:
                try:
                    js = json.load(_f)
                except ValueError as e:
                    logging.error("%s. Deleting crash report.")
                    os.remove(report)
                    continue
                if js['SMTP Submission'] in ('Sent', 'Disabled') and js['HQ Submission'] in ('Sent', 'Disabled'):
                    # Only delete the reports which have been sent or who's upload method is disabled.
                    remaining_reports.remove(report)
                    try:
                        os.remove(report)
                    except OSError as e:
                        logging.error(e)

        return remaining_reports

    def submit_offline_reports(self, **kwargs):
        """
        Submit offline reports using the enabled methods (SMTP and/or HQ)
        Returns a list of booleans signifying upload method success (smtp_success, hq_success)
        """
        hq_success = smtp_success = False
        if kwargs.get('smtp', True) and self._smtp is not None:
            try:
                smtp_success = self._smtp_send_offline_reports()
            except Exception as e:
                logging.error(e)
        if kwargs.get('hq', True) and self._hq is not None:
            try:
                hq_success = self._hq_send_offline_reports()
            except Exception as e:
                logging.error(e)

        return smtp_success and hq_success

    def store_report(self, payload):
        """
        Save the crash report to a file. Keeping the last `offline_report_limit` files in a cyclical FIFO buffer.
        The newest crash report always named is 01
        """
        offline_reports = self.get_offline_reports()
        if offline_reports:
            # Increment the name of all existing reports 1 --> 2, 2 --> 3 etc.
            for ii, report in enumerate(reversed(offline_reports)):
                rpath, ext = os.path.splitext(report)
                n = int(re.findall('(\d+)', rpath)[-1])
                new_name = os.path.join(self.report_dir, self._report_name % (n + 1)) + ext
                shutil.copy2(report, new_name)
            os.remove(report)
            # Delete the oldest report
            if len(offline_reports) >= self.offline_report_limit:
                oldest = glob.glob(os.path.join(self.report_dir, self._report_name % (self.offline_report_limit+1) + '*'))[0]
                os.remove(oldest)
        new_report_path = os.path.join(self.report_dir, self._report_name % 1 + '.json')
        # Write a new report
        with open(new_report_path, 'w') as _f:
            json.dump(payload, _f)

        return new_report_path

    def hq_submit(self, payload):
        payload['HQ Parameters'] = self._hq if self._hq is not None else {}
        r = upload_report(self._hq['server'], payload, timeout=self._hq['timeout'])
        if r is False:
            return False
        else:
            return r.status_code == 200

    def smtp_submit(self, subject, body, attachments=None):
        smtp = self._smtp
        msg = MIMEMultipart()
        if isinstance(smtp['recipients'], list) or isinstance(smtp['recipients'], tuple):
            msg['To'] = ', '.join(smtp['recipients'])
        else:
            msg['To'] = smtp['recipients']
        msg['From'] = smtp['from']
        msg['Subject'] = subject

        # Add the body of the message
        msg.attach(MIMEText(body, 'html'))

        # Add any attachments
        if attachments:
            for attachment in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(open(attachments, 'rb').read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition',
                                'attachment; filename="%s"' % os.path.basename(attachment))
                msg.attach(part)

        try:
            ms = smtplib.SMTP(smtp['host'], smtp['port'], timeout=smtp['timeout'])
            ms.ehlo()
            ms.starttls()
            ms.ehlo()
            ms.login(smtp['user'], smtp['passwd'])
            ms.sendmail(smtp['from'], smtp['recipients'], msg.as_string())
            ms.close()
        except Exception as e:
            self.logger.error('CrashReporter: %s' % e)
            return False

        return True

    def get_offline_reports(self):
        return sorted(glob.glob(os.path.join(self.report_dir, self._report_name.replace("%d", "*"))))

    def _watcher_thread(self):
        """
        Periodically attempt to upload the crash reports. If any upload method is successful, delete the saved reports.
        """
        while 1:
            time.sleep(self.check_interval)
            if not self._watcher_running:
                break
            self.logger.info('CrashReporter: Attempting to send offline reports.')
            self.submit_offline_reports()
            remaining_reports = self.delete_offline_reports()
            if len(remaining_reports) == 0:
                break
        self._watcher = None
        self.logger.info('CrashReporter: Watcher stopped.')

    def _smtp_send_offline_reports(self):
        offline_reports = self.get_offline_reports()
        success = []
        if offline_reports:
            # Add the body of the message
            for report in offline_reports:
                with open(report, 'r') as js:
                    payload = json.load(js)
                if payload['SMTP Submission'] == 'Not sent':
                    success.append(self.smtp_submit(self.subject(), self.body(payload)))
                    if success[-1]:
                        # Set the flag in the payload signifying that the SMTP submission was successful
                        payload['SMTP Submission'] = 'Sent'
                        with open(report, 'w') as js:
                            json.dump(payload, js)
            self.logger.info('CrashReporter: %d Offline reports sent.' % sum(success))
            return success

    def _hq_send_offline_reports(self):
        offline_reports = self.get_offline_reports()
        payloads = {}
        if offline_reports:
            for report in offline_reports:
                with open(report, 'r') as _f:
                    payload = json.load(_f)
                    if payload['HQ Submission'] == 'Not sent':
                        payload['HQ Parameters'] = self._hq if self._hq is not None else {}
                        payloads[report] = payload

            if payloads:
                r = upload_many_reports(self._hq['server'], payloads.values(), timeout=self._hq['timeout'])
                if r is False or r.status_code != 200:
                    return [False] * len(payloads)

            # Set the flag in the payload signifying that the HQ submission was successful
            for report, payload in payloads.iteritems():
                payload['HQ Submission'] = 'Sent'
                with open(report, 'w') as js:
                    json.dump(payload, js)

            return [True] * len(payloads)
        else:
            return [False] * len(payloads)
