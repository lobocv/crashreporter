import inspect
import sys

import numpy as np

from crashreporter.tools import analyze_traceback, get_object_references


class A(object):

    def func(self):
        self.a_number = 1
        self._anunderscore = [1, 2, 3, 5]
        self.__adoubleunderscore = {'a': 1, 'b': 2, 'c': 3}
        self.multiple_under_scores = 5
        self.nounderscores = set(['a', 'b', 'c'])
        self.endswithnumber9 = 2
        self.endswithnumbers443 = 3
        self.numbers7and7letters7 = 4
        self.my_numpy = np.arange(100)
        self.custom_dtype_numpy = np.zeros(10, dtype=[('float_field', 'f'), ('uint_field', 'u4'),
                                                      ('double_field', 'd'), ('string_field', 'a10')])

        1/0

try:
    a = A().func()
except ZeroDivisionError:
    tb = sys.exc_traceback.tb_next
    r = analyze_traceback(tb)

    src = ''.join(inspect.getsourcelines(tb)[0])
    objs = get_object_references(tb, src)

for o in objs:
    print o

print 'Test Complete: {} of {} objects found'.format(len(objs), 9)
sdf3=3



