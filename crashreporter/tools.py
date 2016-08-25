__author__ = 'calvin'

import inspect
import logging
import re
import traceback
from types import FunctionType, MethodType, ModuleType, BuiltinMethodType, BuiltinFunctionType

try:
    import numpy as np
except ImportError:
    np = None


obj_ref_regex = re.compile("[A-z]+[0-9]*\.(?:[A-z]+[0-9]*\.?)+(?!\')(?:\[(?:\'|\").*(?:\'|\")\])*(?:\.[A-z]+[0-9]*)*")
dict_lookup_regex = re.compile("(?<=\[)(?:\'|\")([^\'\"]*)(?:\'|\")(?=\])")

_repr = repr
def repr(object):
    try:
        return _repr(object)
    except Exception as e:
        logging.error(e)
        return 'String Representation not found'


def string_variable_lookup(tb, s):
    """
    Look up the value of an object in a traceback by a dot-lookup string.
    ie. "self.crashreporter.application_name"

    Returns ValueError if value was not found in the scope of the traceback.

    :param tb: traceback
    :param s: lookup string
    :return: value of the
    """

    refs = []
    dot_refs = s.split('.')
    DOT_LOOKUP = 0
    DICT_LOOKUP = 1
    for ii, ref in enumerate(dot_refs):
        dict_refs = dict_lookup_regex.findall(ref)
        if dict_refs:
            bracket = ref.index('[')
            refs.append((DOT_LOOKUP, ref[:bracket]))
            refs.extend([(DICT_LOOKUP, t) for t in dict_refs])
        else:
            refs.append((DOT_LOOKUP, ref))

    scope = tb.tb_frame.f_locals.get(refs[0][1], ValueError)
    if scope is ValueError:
        return scope
    for lookup, ref in refs[1:]:
        try:
            if lookup == DOT_LOOKUP:
                scope = getattr(scope, ref, ValueError)
            else:
                scope = scope.get(ref, ValueError)
        except Exception as e:
            logging.error(e)
            scope = ValueError

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
    _pass = lambda *args: None
    _numpy_info = ('dtype', 'shape', 'size', 'min', 'max')
    for attr in referenced_attr:
        additionals = []
        value = string_variable_lookup(tb, attr)
        if value is not ValueError:
            if np:
                # Check for numpy info
                for np_attr in _numpy_info:
                    np_value = getattr(value, np_attr, None)
                    if np_value is not None:
                        if inspect.isbuiltin(np_value):
                            try:
                                np_value = np_value()
                            except Exception as e:
                                logging.error(e)
                                continue
                        additionals.append((np_attr, np_value))
            else:
                # Check for length of reference
                length = getattr(value, '__len__', _pass)()
                if length is not None:
                    additionals.append(('length', length))

            if additionals:
                vstr = ', '.join(['%s: %s' % a for a in additionals] + [repr(value)])
            else:
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