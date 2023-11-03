"""Module with various generic functional tools and function-related utilities
"""
import cProfile
import contextlib
import inspect
import io
import pstats
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path


def describe_func_call(func, *args, **kwargs):
    """Return string with function call details

    Based on https://stackoverflow.com/a/6278457/46058 response to
    https://stackoverflow.com/questions/6200270/decorator-that-prints-function-call-details-argument-names-and-values


    NOTE: does not work for built-in functions like 'print':
    >>> describe_func_call(print, "message")
    [...]
    ValueError: no signature found for builtin <built-in function print>.

    Example:
    >>> def foo(bar):
    ...     pass
    ...
    >>> describe_func_call(foo, "message")
    "foo(bar='message')"

    :param func: Called function to describe
    :type: typing.Callable
    :param args: Positional parameters to function call being described
    :param kwargs: Named parameters to function call being described
    :return: Function call details
    :rtype: str
    """
    func_args = inspect.signature(func).bind(*args, **kwargs).arguments
    func_args_str = ", ".join(map("{0[0]}={0[1]!r}".format, func_args.items()))
    if func.__module__ == "__main__":
        return f"{func.__qualname__}({func_args_str})"
    else:
        return f"{func.__module__}.{func.__qualname__}({func_args_str})"


def throttled(delay):
    """Delay returning value of decorated function by `delay` seconds.

    It checks if the `delay` is greater than zero, because you cannot
    time.sleep() for negative time.

    :param float delay: time in seconds to sleep before returning value
    """
    def decorator_throttled(func):
        @wraps(func)
        def wrapper_throttle(*args, **kwargs):
            value = func(*args, **kwargs)
            if delay > 0:
                time.sleep(delay)
            return value

        return wrapper_throttle

    return decorator_throttled


def timed(func):
    """Decorator that times wrapped function, and prints its execution time

    Example:
        >>> @timed
        ... def bar():
        ...    time.sleep(1.1)
        ...    return True
        ...
        >>> bar()
        Start time: 2023-08-23 12:00:56.486206 ==============================
        End time: 2023-08-23 12:00:57.602275 ================================
        Function bar() {} took 1.1028 seconds = 0:00:01.102849
        True

    Based on https://dev.to/kcdchennai/python-decorator-to-measure-execution-time-54hk
    """
    @wraps(func)
    def wrapper_timed(*args, **kwargs):
        print(f"Start time: {datetime.now()} ==============================")
        start_time_ns = time.perf_counter_ns()
        result = func(*args, **kwargs)
        end_time_ns = time.perf_counter_ns()
        print(f"End time: {datetime.now()} ================================")
        total_time_sec = (end_time_ns - start_time_ns)/1e9
        # NOTE: it could have used `describe_func_call()`
        print(f'Function {func.__name__}{args} {kwargs} took {total_time_sec:.4f} seconds',
              f'= {timedelta(seconds=total_time_sec)}')

        return result

    return wrapper_timed


@contextlib.contextmanager
def profile(basename: Path, *args, **kwargs):
    """Context manager for profiling

    Usage:
        >>> def my_function():
        ...     with profile(Path("/home/ubuntu/profiles/prof")):
        ...         return 1
        ...

    Based on code by Ricardo Ander-Egg Aguilar (polyrand).

    https://ricardoanderegg.com/posts/python-profiling-timing-utils/
    https://gist.github.com/polyrand/bb39fb93246ced7464abf52d87fec3a7

    :param Path basename: results are saved in `basename`.txt and `basename`.prof
    :param args: positional params passed to `cProfile.Profile`
    :param kwargs: keyword params passed to `cProfile.Profile`
    :rtype: None
    """
    prof = cProfile.Profile(*args, **kwargs)

    prof.enable()
    yield
    prof.disable()

    s = io.StringIO()
    sort_by = pstats.SortKey.CUMULATIVE
    ps = pstats.Stats(prof, stream=s).strip_dirs().sort_stats(sort_by)
    ps.print_stats()
    with open(basename.with_suffix(".txt"), "w") as f:
        f.write(s.getvalue())

    prof.dump_stats(basename.with_suffix(".prof"))


def profiled(basename: Path):
    """Decorator for profiling

    Uses `profile` context manager, but doesn't allow to pass optional
    parameters to `cProfile.Profile` like `profile` did.

    Usage:
        >>> @profiled(Path("/home/ubuntu/profiles/prof"))
        >>> def my_function():
        ...     return 1
        ...

    Based on code by Ricardo Ander-Egg Aguilar (polyrand).

    https://ricardoanderegg.com/posts/python-profiling-timing-utils/
    https://gist.github.com/polyrand/bb39fb93246ced7464abf52d87fec3a7

    :param Path basename: results are saved in `basename`.txt and `basename`.prof
    """
    def decorator_profiled(func):
        @wraps(func)
        def wrapper_profiled(*args, **kwargs):
            with profile(basename):
                return func(*args, **kwargs)

        return wrapper_profiled

    return decorator_profiled
