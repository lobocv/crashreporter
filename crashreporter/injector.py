import sys
import os

print '******************************** WARNING **************************************\n' \
      '              CRASHREPORTER CODE INJECTION HAS BEEN IMPORTED.\n' \
      '       IT IS HIGHLY RECOMMENDED THAT THIS ONLY BE USED IN DEVELOPMENT\n' \
      '    FOR DEBUGGING PURPOSES AS IT ALLOW POSSIBLE MALICIOUS CODE TO BE INJECTED.\n'\
      '*******************************************************************************' \


def inject_path(path):
    """
    Imports :func: from a python file at :path: and executes it with *args, **kwargs arguments. Everytime this function
    is called the module is reloaded so that you can alter your debug code while the application is running.

    The result of the function is returned, otherwise the exception is returned (if one is raised)
    """
    try:
        dirname = os.path.dirname(path)
        if dirname not in sys.path:
            exists_in_sys = False
            sys.path.append(dirname)
        else:
            exists_in_sys = True
        module_name = os.path.splitext(os.path.split(path)[1])[0]
        if module_name in sys.modules:
            reload(sys.modules[module_name])
        else:
            __import__(module_name)
        if not exists_in_sys:
            sys.path.remove(dirname)
    except Exception as e:
        return e


def inject_module(module, *args, **kwargs):
    """
    Imports a function from a python module :module: and executes it with *args, **kwargs arguments. Dotted referencing
    can be used to specify the function from the module.

    For example, the following code will execute func1 and func2 from module mymodule with no arguments
        inject_module('mymodule.func1')
        inject_module('mymodule.func2')

    Everytime this function is called the module is reloaded so that you can alter your
    debug code while the application is running.

    The result of the function is returned, otherwise the exception is returned (if one is raised)
    """

    try:
        parsed = module.split('.')
        if len(parsed) == 1:
            module_name, func_name = parsed[0], 'debug'
        elif len(parsed) == 2:
            module_name, func_name = parsed

        if module_name in sys.modules:
            mod = sys.modules[module_name]
            reload(mod)
        else:
            mod = __import__(module_name)
        f = getattr(mod, func_name, None)
        if f:
            return f(*args, **kwargs)
    except Exception as e:
        print e
        return e