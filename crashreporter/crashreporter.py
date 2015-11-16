__author__ = 'calvin'

import sys
import traceback
import os
import re
import glob
import datetime
import shutil
import smtplib
import time
import logging
import ftplib
import ConfigParser
from threading import Thread
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

import jinja2

from tools import analyze_traceback


class CrashReporter(object):
    """
    Create a context manager that emails or uploads a report by FTP with the traceback on a crash.
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
    :param config: Path to configuration file that defines the arguments to setup_smtp and setup_ftp. The file has the
                   format of a ConfigParser file with sections [SMTP] and [FTP]
    :param html: Create HTML reports (True) or plain text (False).

    """
    _report_name = "crashreport%02d"
    html_template = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'crashreport.html')
    active = False
    application_name = None
    application_version = None
    user_identifier = None
    offline_report_limit = 10
    max_string_length = 1000
    inspection_level = 1
    obj_ref_regex = re.compile("[A-z]+[0-9]*\.(?:[A-z]+[0-9]*\.?)+(?!\')")

    def __init__(self, report_dir=None, html=True, config='', logger=None, activate=True,
                 watcher=True, check_interval=5*60):
        self.html = html
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
        self.tb_info = None
        self._excepthook = None
        # Load the configuration from a file if specified
        if os.path.isfile(config):
            self.load_configuration(config)
        else:
            self._smtp = None
            self._ftp = None
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
        self._smtp['from'] = kwargs.get('from', user)

    def setup_ftp(self, host, user, passwd, path, port=21, acct='', timeout=5, **kwargs):
        """
        Set up the crash reporter to upload reports via FTP.

        :param host: FTP host
        :param user: FTP user
        :param passwd: FTP password for user
        :param path: path to directory on the FTP server to upload files to
        :param port: FTP port
        :param acct: FTP account
        :param timeout: FTP timeout
        """
        self._ftp = kwargs
        self._ftp.update({'host': host, 'port': port, 'user': user, 'passwd': passwd, 'path': path, 'timeout': timeout,
                          'acct': acct})

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
                    if self._get_offline_reports():
                        # First attempt to send the reports, if that fails then start the watcher
                        if any(self.submit_offline_reports(smtp=True, ftp=True)):
                            self.delete_offline_reports()
                        elif self.watcher_enabled:
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
        if CrashReporter.active:
            if etype:
                self.etype = etype
                self.evalue = evalue
                self.tb = tb
                self.tb_info = analyze_traceback(tb)
                # Save the offline report. If the upload of the report is successful, then delete the report.
                report_path = self._save_report()
                great_success = False
                if self._smtp is not None:
                    # Send the report via email
                    with open(report_path, 'r') as _cr:
                        body = _cr.read()
                    great_success |= self._sendmail(self.subject(), body, self.attachments(), html=self.html)
                if self._ftp is not None:
                    # Send the report via FTP
                    great_success |= self._ftp_submit(report_path)
                if great_success:  # Very nice..
                    os.remove(report_path)
            else:
                self.logger.info('CrashReporter: No crashes detected.')

        # Call the default exception hook
        sys.__excepthook__(etype, evalue, tb)

    def load_configuration(self, config):
        cfg = ConfigParser.ConfigParser()

        with open(config, 'r') as _f:
            cfg.readfp(_f)
            if cfg.has_section('SMTP'):
                self.setup_smtp(**dict(cfg.items('SMTP')))
                if 'port' in self._smtp:
                    self._smtp['port'] = int(self._smtp['port'])
                if 'recipients' in self._smtp:
                    self._smtp['recipients'] = self._smtp['recipients'].split(',')

            if cfg.has_section('FTP'):
                self.setup_ftp(**dict(cfg.items('FTP')))
                if 'timeout' in self._ftp:
                    self._ftp['timeout'] = int(self._ftp['timeout'])
                if 'port' in self._ftp:
                    self._ftp['port'] = int(self._ftp['port'])

    def subject(self):
        """
        Return a string to be used as the email subject line.
        """
        if self.application_name and self.application_version:
            return 'Crash Report - {name} (v{version})'.format(name=self.application_name,
                                                               version=self.application_version)
        else:
            return 'Crash Report'

    def html_body(self):
        """
        Return a string to be used as the email body. Can be html if html is turned on.
        """
        dt = datetime.datetime.now()
        error = traceback.format_exception_only(self.etype, self.evalue)[0].strip()
        fields = {'date': dt.strftime('%d %B %Y'),
                  'time': dt.strftime('%I:%M %p'),
                  'traceback': self.tb_info,
                  'error': error,
                  'app_name': self.application_name,
                  'app_version': self.application_version,
                  'user': self.user_identifier
                  }

        with open(self.html_template, 'r') as _f:
            template = jinja2.Template(_f.read())
        html_body = template.render(**fields)
        return html_body

    def raw_body(self):

        body = datetime.datetime.now().strftime('%d %B %Y, %I:%M %p\n')
        body += '\n'.join(traceback.format_exception(self.etype, self.evalue, self.tb))
        body += '\n'
        # Print the source code in the local scope of the error
        body += 'Source Code:\n\n'
        scope_lines = self.tb_info[-1]['source']
        for ln, line in scope_lines:
            body += "{ln}.{line}".format(ln=ln, line=line)
        body += '\nLocal Variables in the scope of {}\n'.format(self.tb_info[-1]['module'])
        # Print a table of local variables
        fmt = "{name:<25s}{value:<25s}\n"
        body += '-' * 90 + '\n'
        body += fmt.format(name='Variable', value='Value')
        body += '-' * 90 + '\n'
        for name, value in self.tb_info[-1]['local_vars']:
            body += fmt.format(name=name, value=value)
        body += '\nObject Inspection in the scope of {}\n'.format(self.tb_info[-1]['module'])
        # Print a table of object attribute references
        body += '-' * 90 + '\n'
        body += fmt.format(name='Variable', value='Value')
        body += '-' * 90 + '\n'
        for name, value in self.tb_info[-1]['object_vars']:
            body += fmt.format(name=name, value=value)
        return body

    def attachments(self):
        """
        Generate and return a list of attachments to send with the report.
        :return: List of strings containing the paths to the files.
        """
        return []

    def delete_offline_reports(self):
        """
        Delete all stored offline reports
        """
        for report in self._get_offline_reports():
            try:
                os.remove(report)
            except OSError as e:
                logging.error(e)

    def submit_offline_reports(self, smtp=True, ftp=True):
        """
        Submit offline reports using the enabled methods (SMTP and/or FTP)
        Returns a tuple of booleans specifying which methods passed (smtp_success, ftp_success)
        """
        ftp_success = smtp_success = False

        if smtp and self._smtp is not None:
            try:
                smtp_success = self._smtp_send_offline_reports()
            except Exception as e:
                logging.error(e)
        if ftp and self._ftp is not None:
            try:
                ftp_success = self._ftp_send_offline_reports()
            except Exception as e:
                logging.error(e)

        return smtp_success, ftp_success

    def _ftp_submit(self, path):
        """
        Upload the database to the FTP server. Only submit new information contained in the partial database.
        Merge the partial database back into master after a successful upload.
        """
        info = self._ftp
        try:
            ftp = ftplib.FTP()
            ftp.connect(host=info['host'], port=info['port'], timeout=info['timeout'])
            ftp.login(user=info['user'], passwd=info['passwd'], acct=info['acct'])
        except ftplib.all_errors as e:
            self.logger.error(e)
            self.stop_watcher()
            return False
        extension = os.path.splitext(path)[1]
        ftp.cwd(info['path'])
        with open(path, 'rb') as _f:
            new_filename = self._report_name % (len(ftp.nlst()) + 1) + extension
            ftp.storlines('STOR %s' % new_filename, _f)
            self.logger.info('CrashReporter: FTP submission to %s successful.' % info['host'])
            return True

    def _ftp_send_offline_reports(self):
        """
        Upload the database to the FTP server. Only submit new information contained in the partial database.
        Merge the partial database back into master after a successful upload.
        """
        info = self._ftp
        try:
            ftp = ftplib.FTP()
            ftp.connect(host=info['host'], port=info['port'], timeout=info['timeout'])
            ftp.login(user=info['user'], passwd=info['passwd'], acct=info['acct'])
        except ftplib.all_errors as e:
            self.logger.error(e)
            return False

        ftp.cwd(info['path'])
        for report in self._get_offline_reports():
            with open(report, 'rb') as _f:
                ext = os.path.splitext(report)[1]
                new_filename = self._report_name % (len(ftp.nlst()) + 1) + ext
                ftp.storlines('STOR %s' % new_filename, _f)
                self.logger.info('CrashReporter: Submission of %s to %s successful.' % (new_filename, info['host']))
        return True

    def _sendmail(self, subject, body, attachments=None, html=False):
        smtp = self._smtp
        msg = MIMEMultipart()
        if isinstance(smtp['recipients'], list) or isinstance(smtp['recipients'], tuple):
            msg['To'] = ', '.join(smtp['recipients'])
        else:
            msg['To'] = smtp['recipients']
        msg['From'] = smtp['from']
        msg['Subject'] = subject

        # Add the body of the message
        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body))

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
            ms = smtplib.SMTP(smtp['host'], smtp['port'])
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

    def _smtp_send_offline_reports(self):
        offline_reports = self._get_offline_reports()
        if offline_reports:
            spacer = '<br>' if self.html else '-------------------------------------------------\n'
            # Add the body of the message
            body = 'Here is a list of crash reports that were stored offline.\n'
            body += spacer
            for report in offline_reports:
                with open(report, 'r') as _f:
                    text = _f.readlines()
                    body += ''.join(text)
                    body += spacer
            great_success = self._sendmail(self.subject(), body, html=self.html)
            if great_success:
                self.logger.info('CrashReporter: Offline reports sent.')
            return great_success

    def _save_report(self):
        """
        Save the crash report to a file. Keeping the last `offline_report_limit` files in a cyclical FIFO buffer.
        The newest crash report always named is 01
        """
        offline_reports = self._get_offline_reports()
        if offline_reports:
            # Increment the name of all existing reports 1 --> 2, 2 --> 3 etc.
            for ii, report in enumerate(reversed(offline_reports)):
                rpath, ext = os.path.splitext(report)
                n = int(rpath[-2:])
                new_name = os.path.join(self.report_dir, self._report_name % (n + 1)) + ext
                shutil.copy2(report, new_name)
            os.remove(report)
            # Delete the oldest report
            if len(offline_reports) >= self.offline_report_limit:
                oldest = glob.glob(os.path.join(self.report_dir, self._report_name % (self.offline_report_limit+1) + '*'))[0]
                os.remove(oldest)
        new_report_path = os.path.join(self.report_dir, self._report_name % 1 + ('.html' if self.html else '.txt'))
        # Write a new report
        with open(new_report_path, 'w') as _f:
            _f.write(self.html_body() if self.html else self.raw_body())

        return new_report_path

    def _get_offline_reports(self):
        return sorted(glob.glob(os.path.join(self.report_dir, "crashreport*")))

    def _watcher_thread(self):
        """
        Periodically attempt to upload the crash reports. If any upload method is successful, delete the saved reports.
        """
        great_success = False
        while not great_success:
            time.sleep(self.check_interval)
            if not self._watcher_running:
                break
            self.logger.info('CrashReporter: Attempting to send offline reports.')
            great_success |= any(self.submit_offline_reports(smtp=True, ftp=True))
        if great_success:
            self.delete_offline_reports()
        self._watcher = None
        self.logger.info('CrashReporter: Watcher stopped.')
