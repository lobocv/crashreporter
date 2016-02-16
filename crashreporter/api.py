__author__ = 'calvin'

import requests
import json
import logging


HQ_DEFAULT_TIMEOUT = 10
SMTP_DEFAULT_TIMEOUT = 5


def upload_report(server, payload, timeout=HQ_DEFAULT_TIMEOUT):
    """
    Upload a report to the server.
    :param payload: Dictionary (JSON serializable) of crash data.
    :return: server response
    """
    data = json.dumps(payload)
    try:
        r = requests.post(server + '/reports/upload', data=data, timeout=timeout)
    except Exception as e:
        logging.error(e)
        return False
    return r


def upload_many_reports(server, payloads, timeout=HQ_DEFAULT_TIMEOUT):

    data = json.dumps(payloads)
    try:
        r = requests.post(server + '/reports/upload_many', data=data, timeout=timeout)
    except Exception as e:
        logging.error(e)
        return False
    return r


def delete_report(server, report_number, timeout=HQ_DEFAULT_TIMEOUT):
    """
    Delete a specific crash report from the server.
    :param report_number: Report Number
    :return: server response
    """
    try:
        r = requests.post(server + "/reports/delete/%d" % report_number, timeout=timeout)
    except Exception as e:
        logging.error(e)
        return False

    return r
