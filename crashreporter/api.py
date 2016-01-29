__author__ = 'calvin'

import requests
import json
import logging


def upload_report(server, payload):
    """
    Upload a report to the server.
    :param payload: Dictionary (JSON serializable) of crash data.
    :return: server response
    """
    data = json.dumps(payload)
    try:
        r = requests.post(server + '/reports/upload', data=data)
    except Exception as e:
        logging.error(e)
        return False
    return r


def upload_many_reports(server, payloads):

    data = json.dumps(payloads)
    try:
        r = requests.post(server + '/reports/upload_many', data=data)
    except Exception as e:
        logging.error(e)
        return False
    return r


def delete_report(server, report_number):
    """
    Delete a specific crash report from the server.
    :param report_number: Report Number
    :return: server response
    """
    try:
        r = requests.post(server + "/reports/delete/%d" % report_number)
    except Exception as e:
        logging.error(e)
        return False

    return r
