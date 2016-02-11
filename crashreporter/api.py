__author__ = 'calvin'

import requests
import json
import logging


def upload_report(server, payload, timeout=10):
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


def upload_many_reports(server, payloads, timeout=10):

    data = json.dumps(payloads)
    try:
        r = requests.post(server + '/reports/upload_many', data=data, timeout=timeout)
    except Exception as e:
        logging.error(e)
        return False
    return r


def delete_report(server, report_number, timeout=5):
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
