__author__ = 'calvin'

import re
import inspect
import traceback
from types import FunctionType, MethodType, ModuleType, BuiltinMethodType, BuiltinFunctionType


obj_ref_regex = re.compile("[A-z]+[0-9]*\.(?:[A-z]+[0-9]*\.?)+(?!\')")


def string_variable_lookup(tb, s):
    """
    Look up the value of an object in a traceback by a dot-lookup string.
    ie. "self.crashreporter.application_name"

    Returns ValueError if value was not found in the scope of the traceback.

    :param tb: traceback
    :param s: lookup string
    :return: value of the
    """

    refs = s.split('.')
    scope = tb.tb_frame.f_locals.get(refs[0], ValueError)
    if scope is ValueError:
        return scope
    for ref in refs[1:]:
        scope = getattr(scope, ref, ValueError)
        if scope is ValueError:
            return scope
        elif isinstance(scope, (FunctionType, MethodType, ModuleType, BuiltinMethodType, BuiltinFunctionType)):
            return ValueError
    return scope


def get_object_references(tb, source, max_string_length=1000):
    """
    Find the values of referenced attributes of objects within the traceback scope.

    :param tb: traceback
    :return: list of tuples containing (variable name, value)
    """
    global obj_ref_regex
    referenced_attr = set()
    for line in source.split('\n'):
        referenced_attr.update(set(re.findall(obj_ref_regex, line)))
    referenced_attr = sorted(referenced_attr)
    info = []
    for attr in referenced_attr:
        value = string_variable_lookup(tb, attr)
        if value is not ValueError:
            vstr = repr(value)
            if len(vstr) > max_string_length:
                vstr = vstr[:max_string_length] + ' ...'
            info.append((attr, vstr))
    return info


def get_local_references(tb, max_string_length=1000):
    """
    Find the values of the local variables within the traceback scope.

    :param tb: traceback
    :return: list of tuples containing (variable name, value)
    """
    if 'self' in tb.tb_frame.f_locals:
        _locals = [('self', repr(tb.tb_frame.f_locals['self']))]
    else:
        _locals = []
    for k, v in tb.tb_frame.f_locals.iteritems():
        if k == 'self':
            continue
        try:
            vstr = repr(v)
            if len(vstr) > max_string_length:
                vstr = vstr[:max_string_length] + ' ...'
            _locals.append((k, vstr))
        except TypeError:
            pass
    return _locals


def analyze_traceback(tb, inspection_level=None):
    """
    Extract trace back information into a list of dictionaries.

    :param tb: traceback
    :return: list of dicts containing filepath, line, module, code, traceback level and source code for tracebacks
    """
    info = []
    tb_level = tb
    extracted_tb = traceback.extract_tb(tb)
    for ii, (filepath, line, module, code) in enumerate(extracted_tb):
        func_source, func_lineno = inspect.getsourcelines(tb_level.tb_frame)

        d = {"File": filepath,
             "Error Line Number": line,
             "Module": module,
             "Error Line": code,
             "Module Line Number": func_lineno,
             "Source Code": ''}
        if inspection_level is None or len(extracted_tb) - ii <= inspection_level:
            # Perform advanced inspection on the last `inspection_level` tracebacks.
            d['Source Code'] = ''.join(func_source)
            d['Local Variables'] = get_local_references(tb_level)
            d['Object Variables'] = get_object_references(tb_level, d['Source Code'])
        tb_level = getattr(tb_level, 'tb_next', None)
        info.append(d)

    return info