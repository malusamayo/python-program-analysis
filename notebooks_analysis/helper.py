import os, sys, re
import pandas as pd
import numpy as np
import copy as lib_copy
import collections, functools
import matplotlib, pickle, json
from inspect import getframeinfo, stack
import types

script_path = os.path.realpath(__file__)
my_dir_path = os.path.dirname(os.path.realpath(__file__))
ignore_types = [
    "<class 'module'>", "<class 'type'>", "<class 'function'>",
    "<class 'matplotlib.figure.Figure'>", "<class 'tensorflow.python.keras.engine.sequential.Sequential'>"
]
reset_index_types = [
    "<class 'pandas.core.indexes.range.RangeIndex'>", "<class 'pandas.core.indexes.numeric.Int64Index'>"
]

TRACE_INTO = []

matplotlib.use('Agg')

# global variables for information saving
store_vars = collections.defaultdict(list)
cur_cell = 0
cur_exe = []
get__keys = collections.defaultdict(list)
set__keys = collections.defaultdict(list)
id2name = {}
access_path = []
lineno = 0
# noop = lambda *args, **kwargs: None
id2index = {}

def update_access(col, is_set):
    tup = (col, cur_cell, lineno, is_set)
    if tup not in access_path:
        access_path.append(tup)

def set_index_map(var, name):
    if str(type(var.index)) in reset_index_types:
        saved_name = var.index.name
        var.reset_index(inplace=True, drop=True, sys_flag=True)
        var.index.rename(saved_name, inplace=True)
    if var.index.name == "ignore":
        var.index.rename(None, inplace=True)
    id2name[id(var.index)] = name

def my_store_info(info, var):
    if str(type(var)) in ignore_types:
        return
    if info[1] == 0:
        if type(var) in [pd.DataFrame, pd.Series]: 
            set_index_map(var, info[2])
        elif type(var) == list:
            for i, v in enumerate(var):
                if type(v) in [pd.DataFrame, pd.Series]:
                    set_index_map(v, info[2] + f"[{i}]")
    elif type(var) in [pd.DataFrame] and info[1] == 1:
        if id(var) in id2index:
            try:
                var = var.set_index(id2index[id(var)])
            except ValueError:
                pass
    store_vars[info[0]].append((wrap_copy(var), info))


def wrap_copy(var):
    try:
        # if type(var) == pd.DataFrame:
        #     for col in var.columns:
        #         if type(var[col].iloc[0]) == MyStr:
        #             var[col] = var[col].astype(str)
        # elif type(var) == pd.DataFrame:
        #     if type(var.iloc[0]) == MyStr:
        #         var = var.astype(str)
        if hasattr(var, "__setstate__") or type(var) in [str, int, float, bool, list, tuple, dict]:
            return lib_copy.deepcopy(var)
        else:
            return "NOT COPIED"
    except NotImplementedError:
        return "NOT COPIED"
    except TypeError:
        return "NOT COPIED"
    except SystemError:
        return "NOT COPIED"


def func_info_saver(line):
    def inner_decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # if func.__name__ not in TRACE_INTO and func.__name__ != '<lambda>':
            #     return func(*args, **kwargs)

            try:
                pathTracker.next_iter()
            except:
                # don't track apply/map of other objects
                pathTracker.clean()
                return func(*args, **kwargs)

            # name = func.__name__ + "_" + str(line)
            # args_name = tuple(inspect.signature(func).parameters)
            # arg_dict = dict(zip(args_name, args))
            # arg_dict.update(kwargs)
            # funcs[name]["loc"] = line

            # convert arg of str to MyStr
            new_args = []
            for arg in list(args):
                if type(arg) == str:
                    new_args.append(MyStr(arg))
                else:
                    new_args.append(arg)
            args = tuple(new_args)

            # should make sure it is inside map/apply
            rets = func(*args, **kwargs)
            
            cond = lambda arg: pd.api.types.is_numeric_dtype(type(arg)) and np.isnan(arg)
            if any(cond(arg) for arg in args):
                if not cond(rets):
                    pathTracker.update(1, "fillna")
                else:
                    pathTracker.update(0, "fillna")

            # convert back to str
            if type(rets) == MyStr:
                rets = str(rets)
            elif type(rets) == list:
                rets = tuple([str(i) if type(i) == MyStr else i for i in rets])
            
            if cur_exe:
                pathTracker.update(lib_copy.copy(cur_exe), func.__name__)
            cur_exe.clear()
            return rets

        return wrapper

    return inner_decorator

# should converted to str when return
class MyStr(str):
    # cnt = 0
    def __new__(cls, content):
        return super().__new__(cls, content)
    
    def replace(self, __old: str, __new: str, __count=-1) -> str:
        ret = super().replace(__old, __new, __count)
        pathTracker.update(int(self != ret), "replace")
        return MyStr(ret)
    
    def split(self, sep=None, maxsplit=-1):
        ret = super().split(sep, maxsplit)
        pathTracker.update(len(ret), "split")
        return [MyStr(x) for x in ret]

    def strip(self, __chars=None) :
        ret = super().strip(__chars)
        pathTracker.update(int(self != ret), "strip")
        return MyStr(ret)
    
    def lower(self):
        ret = super().lower()
        pathTracker.update(int(self != ret), "lower")
        return MyStr(ret)

    def upper(self):
        ret = super().upper()
        pathTracker.update(int(self != ret), "upper")
        return MyStr(ret)
    
    # could not handle str constants (need to wrap them!)
    def join(self):
        ret = super().upper()
        return MyStr(ret)

def if_expr_wrapper(expr):
    if if_expr_wrapper.track_flag and pathTracker.cur_idx >= 0:
        pathTracker.update(int(expr), "if_expr")
    return expr
if_expr_wrapper.track_flag = False

class LibDecorator(object):
    def __init__(self):
        super().__init__()
        pd.DataFrame.__getitem__ = self.get_decorator(pd.DataFrame.__getitem__)
        pd.Series.__getitem__ = self.get_decorator(pd.Series.__getitem__)
        pd.DataFrame.__setitem__ = self.set_decorator(pd.DataFrame.__setitem__)
        pd.Series.__setitem__ = self.set_decorator(pd.Series.__setitem__)
        pd.core.indexing._LocationIndexer.__setitem__ = self.index_set_decorator(pd.core.indexing._LocationIndexer.__setitem__)
        pd.core.indexing._ScalarAccessIndexer.__setitem__ = self.index_set_decorator(pd.core.indexing._ScalarAccessIndexer.__setitem__)
        pd.get_dummies = self.get_dummies_decorator(pd.get_dummies)
        pd.Series.replace = self.replace_decorator(pd.Series.replace)
        pd.Series.fillna = self.fillna_decorator(pd.Series.fillna)
        pd.DataFrame.fillna = self.fillna_decorator(pd.DataFrame.fillna)
        pd.Series.map  = self.map_decorator(pd.Series.map)
        pd.Series.apply  = self.apply_decorator(pd.Series.apply)
        pd.DataFrame.apply  = self.df_apply_decorator(pd.DataFrame.apply)
        pd.Series.str.split = self.str_split_decorator(pd.Series.str.split)
        pd.Series.str.extract = self.str_extract_decorator(pd.Series.str.extract)
        pd.Series.str.replace = self.str_replace_decorator(pd.Series.str.replace)
        
        pd.DataFrame.reset_index = self.reset_index_decorator(pd.DataFrame.reset_index)
        pd.Series.reset_index = self.reset_index_decorator(pd.Series.reset_index)

        pd.Series.dropna = self.dropna_decorator(pd.Series.dropna)
        pd.DataFrame.dropna = self.dropna_decorator(pd.DataFrame.dropna)

        
        # pd.Series.__iter__ = self.iter_decorator(pd.Series.__iter__)
        # pd.Series.__next__ = self.next_decorator()

        # ignore merge for now
        pd.DataFrame.merge = self.merge_decorator(pd.DataFrame.merge)
        pd.merge = self.merge_decorator(pd.merge)
        
    def merge_decorator(self, wrapped_method):
        def decorate(*args, **kwargs):
            res = wrapped_method(*args, **kwargs)
            res.index.name = "ignore"
            return res
        return decorate

    def iter_decorator(self, wrapped_method):
        def decorate(self, *args, **kwargs):
            pathTracker.reset(self.index)
            res = wrapped_method(self, *args, **kwargs)
            self.my_iter = res
            return self
        return decorate

    def next_decorator(self):
        def decorate(self):
            pathTracker.next_iter()
            x = next(self.my_iter)
            if type(x) == str:
                return MyStr(x)
            else:
                return x
            return x
        return decorate
    
    def replace_decorator(self, wrapped_method):
        def f(x, key, value, regex):
            pathTracker.next_iter()
            if type(value) in [list, tuple, range]:
                if regex:
                    for i, pat in enumerate(key):
                        try:
                            if bool(re.search(pat, x)):
                                pathTracker.update(i, "replace_ls")
                                return
                        except:
                            pathTracker.update(-2, "replace_ls") # error
                            return
                    pathTracker.update(-1, "replace_ls")
                else:
                    pathTracker.update(key.index(x) if x in key else -1, "replace_ls")
            elif type(key) == list:
                if regex:
                    try:
                        pathTracker.update(int(any(re.search(item, x) for item in key)), "replace")
                    except:
                        pathTracker.update(-2, "replace") # error
                else:
                    pathTracker.update(int(x in key), "replace")
            else:
                if regex:
                    try:
                        pathTracker.update(int(re.search(key, x)), "replace")
                    except:
                        pathTracker.update(-2, "replace") # error
                else:
                    pathTracker.update(int(x != key), "replace")
        def decorate(self, to_replace=None, value=None, inplace=False, limit=None, regex=False, method="pad"):
            if to_replace != None and type(to_replace) != dict:
                self.map(lambda x: f(x, to_replace, value, regex), sys_flag=True)
            return wrapped_method(self, to_replace, value, inplace, limit, regex, method)
        return decorate

    def fillna_decorator(self, wrapped_method):
        def f(x):
            pathTracker.next_iter()
            pathTracker.update(int(x), "fillna")

        def decorate(self, *args, **kwargs):
            # cmp before and after?
            if type(self) == pd.Series:
                self.isnull().map(f, sys_flag=True)
            elif type(self) == pd.DataFrame:
                self.isnull().sum(axis=1).map(f, sys_flag=True)
            return wrapped_method(self, *args, **kwargs)
        return decorate
    
    def dropna_decorator(self, wrapped_method):
        def f(x):
            pathTracker.next_iter()
            pathTracker.update(int(x), "dropna")

        def decorate(self, *args, **kwargs):
            # cmp before and after?
            if type(self) == pd.Series:
                self.isnull().map(f, sys_flag=True)
            elif type(self) == pd.DataFrame:
                self.isnull().any(axis=1).map(f, sys_flag=True)
            ret = wrapped_method(self, *args, **kwargs)
            if id(self.index) in id2name:
                id2name[id(ret.index)] = id2name[id(self.index)]
            return ret
        return decorate

    def str_split_decorator(self, wrapped_method):
        def f(x, pat, n):
            pathTracker.next_iter()
            try:
                ret = x.split(pat, n)
                pathTracker.update(len(ret), "split")
            except AttributeError:
                pathTracker.update(-2, "split") # x not str
        def decorate(self, pat=None, n=-1, expand=False):
            self._parent.map(lambda x: f(x, pat, n), sys_flag=True)
            return wrapped_method(self, pat, n, expand)
        return decorate

    def str_replace_decorator(self, wrapped_method):
        def f(x):
            pathTracker.next_iter()
            pathTracker.update(int(x), "replace")
        def decorate(self, *args, **kwargs):
            ret = wrapped_method(self, *args, **kwargs)
            cmp_res = (ret != self._parent)
            if type(cmp_res) == pd.Series:
                cmp_res.map(f, sys_flag=True)
            return ret
        return decorate

    def str_extract_decorator(self, wrapped_method):
        def f(x):
            pathTracker.next_iter()
            pathTracker.update(int(x), "extract")

        def decorate(self, *args, **kwargs):
            ret = wrapped_method(self, *args, **kwargs)
            if type(ret) == pd.Series:
                ret.notnull().map(f, sys_flag=True)
            elif type(ret) == pd.DataFrame:
                ret.notnull().sum(axis=1).map(f, sys_flag=True)
            return ret
        return decorate

    def map_decorator(self, wrapped_method):
        def f(x, d):
            pathTracker.next_iter()
            pathTracker.update(list(d).index(x) if x in d else -1, "map_dict")
        def decorate(self, arg, na_action=None, sys_flag=False):
            # should do init work here
            pathTracker.reset(self.index)
            if type(arg) == dict:
                self.map(lambda x: f(x, arg), sys_flag=True)
            if not sys_flag and isinstance(arg, types.FunctionType):
                arg = func_info_saver(296)(arg)

            if_expr_wrapper.track_flag = True
            ret = wrapped_method(self, arg, na_action)
            if_expr_wrapper.track_flag = False
            return ret
        return decorate

    def apply_decorator(self, wrapped_method):
        def decorate(self, func, *args, **kwargs):
            pathTracker.reset(self.index)
            if isinstance(func, types.FunctionType):
                func = func_info_saver(304)(func)

            if_expr_wrapper.track_flag = True
            ret = wrapped_method(self, func, *args, **kwargs)
            if_expr_wrapper.track_flag = False
            return ret
        return decorate


    def df_apply_decorator(self, wrapped_method):
        def decorate(self, func, *args, **kwargs):
            if "axis" in kwargs:
                if kwargs["axis"] == 1 or kwargs["axis"] == 'columns':
                    pathTracker.reset(self.index)
                else:
                    pathTracker.clean()
            if isinstance(func, types.FunctionType):
                func = func_info_saver(317)(func)
                
            if_expr_wrapper.track_flag = True
            ret = wrapped_method(self, func, *args, **kwargs)
            if_expr_wrapper.track_flag = False
            return ret
        return decorate

    def reset_index_decorator(self, wrapped_method):
        def decorate(self, *args, sys_flag=False,**kwargs):
            saved_index = self.index
            ret = wrapped_method(self, *args, **kwargs)
            if not sys_flag:
                # if "inplace" in kwargs and kwargs["inplace"]:
                #     self.set_index(saved_index, inplace=True)
                # else:
                #     ret.set_index(saved_index, inplace=True)
                if "inplace" in kwargs and kwargs["inplace"]:
                    id2index[id(self)] = saved_index
                else:
                    id2index[id(ret)] = saved_index
            return ret
        return decorate
    
    def get_dummies_decorator(self, wrapped_method):
        def f(x, ls):
            pathTracker.next_iter()
            pathTracker.update(ls.index(x) if x in ls else -1, "get_dummies")
        def append(key, ls):
            if pd.core.dtypes.common.is_hashable(key) and key not in ls:
                ls.append(key)
        def decorate_acc(data, prefix=None, prefix_sep='_', dummy_na=False, columns=None, sparse=False, drop_first=False, dtype=None):
            if type(data) == pd.DataFrame:
                if columns:
                    for item in columns:
                        append(item, get__keys[cur_cell])
                        update_access(item, False)
                        data[item].map(lambda x: f(x, list(data[item].unique())), sys_flag=True)
                else:
                    for item in data.select_dtypes(include=['object', 'category']).columns:
                        append(item, get__keys[cur_cell])
                        update_access(item, False)
                        data[item].map(lambda x: f(x, list(data[item].unique())), sys_flag=True)
            elif type(data) == pd.Series:
                data.map(lambda x: f(x, list(data.unique())), sys_flag=True)
            return wrapped_method(data, prefix, prefix_sep, dummy_na, columns, sparse, drop_first, dtype)
        return decorate_acc

    def get_decorator(self, method):     
        def append(key, ls):
            if pd.core.dtypes.common.is_hashable(key) and key not in ls:
                ls.append(key)
        def decorate_acc(self, key):
            # caller = getframeinfo(stack()[1][0])
            # lineno = caller.lineno if script_path.endswith(caller.filename) else 0
            if type(key) == list:
                for item in key:
                    append(item, get__keys[cur_cell])
                    update_access(item, False)
            elif type(key) == str:
                append(key, get__keys[cur_cell])
                update_access(key, False)
            return method(self, key)
        return decorate_acc
    def set_decorator(self, method):
        def append(key, ls):
            if pd.core.dtypes.common.is_hashable(key) and key not in ls:
                ls.append(key)
        def index_model(key, index):
            if len(key) != len(index):
                return
            pathTracker.reset(index)
            for i, v in enumerate(key):
                pathTracker.next_iter()
                pathTracker.update(int(v), "set")
        def decorate_acc(self, key, value):
            # caller = getframeinfo(stack()[1][0])
            # lineno = caller.lineno if script_path.endswith(caller.filename) else 0  
            if type(key) == list:
                for item in key:
                    append(item, set__keys[cur_cell])
                    update_access(item, True)
            elif type(key) == str:
                append(key, set__keys[cur_cell])
                update_access(key, True)
            elif type(key) == pd.Series and key.dtype == bool:
                index_model(key, self.index)
            return method(self, key, value)
        return decorate_acc
    def index_set_decorator(self, method):
        def append(key, ls):
            if pd.core.dtypes.common.is_hashable(key) and key not in ls:
                ls.append(key)
        def index_model(key, index):
            if len(key) != len(index):
                return
            pathTracker.reset(index)
            for i, v in enumerate(key):
                pathTracker.next_iter()
                pathTracker.update(int(v), "loc/at")
        def decorate_acc(self, key, value):
            # caller = getframeinfo(stack()[1][0])
            # lineno = caller.lineno if script_path.endswith(caller.filename) else 0
            if hasattr(self, "obj") and type(self.obj) == pd.Series:
                append(self.obj.name, set__keys[cur_cell])
                update_access(self.obj.name, True)
                # maybe we could model scalr/slice?
                if type(key) == pd.Series and key.dtype == bool:
                    index_model(key, self.obj.index)
            if hasattr(self, "obj") and type(self.obj) == pd.DataFrame:
                if type(key) == tuple and type(key[0]) == pd.Series and key[0].dtype == bool:
                    index_model(key[0], self.obj.index)
                    if type(key[1]) == str:
                        update_access(key[1], True)
            return method(self, key, value)
        return decorate_acc

class PathTracker(object):
    def __init__(self) -> None:
        super().__init__()
        self.paths = collections.defaultdict(lambda: collections.defaultdict(list))
        self.partitions = {}
        self.cur_idx = -1
        sys.settrace(self.trace_calls)

    def reset(self, index):
        self.index = index
        self.id = id(index)
        if self.id in id2name:
            self.id = id2name[self.id]
        self.iter = iter(index)
        self.cur_idx = 0
    
    def clean(self):
        self.iter = iter(())
        self.cur_idx = -1

    def next_iter(self):
        # try:
        self.cur_idx = next(self.iter)
        # except StopIteration:
        #     self.cur_idx = next(iter(self.index))

    def update(self, new_path, func_name):
        self.paths[self.id][self.cur_idx].append([new_path, func_name])

    def to_partition(self):
        id2index.clear()
        if not self.paths:
            return
        row_eq = {}
        for i, path in self.paths.items():
            row_eq[i] = collections.defaultdict(list)
            for k, v in path.items():
                row_eq[i][str(v)].append(k)
        self.partitions[cur_cell] = row_eq
        self.paths.clear()

    def trace_lines(self, frame, event, arg):
        if event != 'line':
            return
        co = frame.f_code
        func_name = co.co_name
        line_no = frame.f_lineno
        filename = co.co_filename
        cur_exe.append(line_no)


    def trace_calls(self, frame, event, arg):
        
        line_no = frame.f_lineno
        if frame.f_code.co_name == "decorate_acc":
            caller = frame.f_back
            caller_line_no = caller.f_lineno
            caller_filename = caller.f_code.co_filename
            if caller_filename.endswith("generic.py"):
                caller = caller.f_back
                caller_line_no = caller.f_lineno
                caller_filename = caller.f_code.co_filename
            if script_path.endswith(caller_filename):
                global lineno
                lineno = caller_line_no
        if event != 'call':
            return
        co = frame.f_code
        func_name = co.co_name
        try:
            if func_name not in TRACE_INTO:
                return
        except TypeError:
            print(func_name, TRACE_INTO)
            return
        line_no = frame.f_lineno
        return self.trace_lines

libDec = LibDecorator()
pathTracker = PathTracker()