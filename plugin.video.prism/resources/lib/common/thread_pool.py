from __future__ import annotations

import concurrent.futures
import threading
from functools import reduce

from resources.lib.common import tools
from resources.lib.modules.globals import g

_shared_executor = None
_provider_executor = None
_shared_executor_lock = threading.Lock()

# Default, Low, Medium, High, Extreme
_SCALED_WORKERS = [20, 10, 20, 40, 80]


class ThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """
    Support the python 3.9+ option to cancel futures on shutdown
    """

    import queue

    def shutdown(self, wait=True, *, cancel_futures=False):
        """
        Clean-up the resources associated with the Executor.

        It is safe to call this method several times. Otherwise, no other methods can be called after this one.

        :param wait: If True then shutdown will not return until all running futures have finished executing and the
                     resources used by the executor have been reclaimed.
        :param cancel_futures: If cancel_futures is True, this method will cancel all pending futures that the executor
                               has not started running. Any futures that are completed or running won’t be cancelled,
                               regardless of the value of cancel_futures
        :return:
        """
        with self._shutdown_lock:
            self._shutdown = True
            if cancel_futures:
                # Drain all work items from the queue, and then cancel their
                # associated futures.
                while True:
                    try:
                        work_item = self._work_queue.get_nowait()
                    except self.queue.Empty:
                        break
                    if work_item is not None:
                        work_item.future.cancel()

            # Send a wake-up to prevent threads calling
            # _work_queue.get(block=True) for permanently blocking.
            self._work_queue.put(None)
        if wait:
            for t in self._threads:
                t.join()


def _max_pool_workers() -> int:
    limiter = g.get_bool_runtime_setting("threadpool.limiter")
    workers = _SCALED_WORKERS[g.get_int_setting("general.threadpoolScale", -1) + 1]
    return 1 if limiter else workers


def get_shared_executor() -> ThreadPoolExecutor:
    """Process-wide executor for flat parallel work (e.g. Simkl detail enrich)."""
    global _shared_executor
    with _shared_executor_lock:
        if _shared_executor is None or getattr(_shared_executor, "_shutdown", False):
            _shared_executor = ThreadPoolExecutor(max_workers=_max_pool_workers())
        return _shared_executor


def get_provider_executor() -> ThreadPoolExecutor:
    """Separate pool for nested TMDB/TVDB/Fanart fetches inside milling workers.

    Must not share the list-milling executor — workers that block waiting for
    sub-tasks on the same pool will deadlock when the pool is saturated.
    """
    global _provider_executor
    with _shared_executor_lock:
        if _provider_executor is None or getattr(_provider_executor, "_shutdown", False):
            workers = max(6, min(24, _max_pool_workers() * 2))
            _provider_executor = ThreadPoolExecutor(max_workers=workers)
        return _provider_executor


class ThreadPool:
    """
    Helper class to simplify raising worker_pool
    """

    scaled_workers = _SCALED_WORKERS

    def __init__(self, *, shared: bool = False):
        self._shared = shared
        if shared:
            self.executor = get_shared_executor()
            self.max_workers = self.executor._max_workers
        else:
            self.max_workers = _max_pool_workers()
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self.tasks = []

    def __del__(self):
        if self._shared:
            return
        # __init__ may have raised before self.executor was assigned (e.g. a
        # subclass whose construction failed mid-way). Guard so GC of the
        # half-built object doesn't emit a noisy secondary AttributeError.
        executor = getattr(self, "executor", None)
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _handle_results(results):
        result_iter = iter(results)

        for result in result_iter:
            if result is not None:
                break
        else:
            return None

        if isinstance(result, dict):
            return reduce(tools.smart_merge_dictionary, result_iter, result)
        elif isinstance(result, (list, set)):
            result_list = list(result)
            for result in result_iter:
                if result is not None:
                    if isinstance(result, list):
                        result_list.extend(result)
                    else:
                        result_list.append(result)
            return result_list
        else:
            return [result for result in result_iter if result is not None]

    def put(self, func, *args, **kwargs):
        """
        Adds task to executor and starts it running
        :param func: method to run in task
        :type func: object
        :param args: arguments to assign to method
        :type args: any
        :param kwargs: kwargs to assign to method
        :type kwargs: any
        :return:
        :rtype:
        """
        self.tasks.append(self.executor.submit(func, *args, **kwargs))

    def wait_completion(self):
        """
        Joins threads and waits for their completion, raises any exceptions if any present and returns results if
        present
        :return: The results
        :raises: The first exception identified if an exception is raised
        """
        try:
            for task in concurrent.futures.as_completed(self.tasks):
                if exception := task.exception():
                    if not self._shared:
                        self.executor.shutdown(wait=False, cancel_futures=True)
                    raise exception

            results = self._handle_results(task.result() for task in self.tasks if task)
            self.tasks.clear()
            return results
        except Exception:
            g.log_stacktrace()
            if not self._shared:
                self.executor.shutdown(wait=False, cancel_futures=True)
            raise

    def map_results(self, func, args_iterable=None, kwargs_iterable=None):
        """
        Takes iterables for args and kwargs and runs func with them, gathers the results and returns in order
        :param func: The function to execute
        :param args_iterable: An iterable of args tuples
        :param kwargs_iterable: An iterable of kwargs dicts
        :return: The results
        """
        try:
            return self._handle_results(
                self.executor.map(lambda args, kwargs: func(*args, **kwargs), args_iterable, kwargs_iterable)
                if args_iterable and kwargs_iterable
                else self.executor.map(lambda kwargs: func(**kwargs), kwargs_iterable)
                if kwargs_iterable
                else self.executor.map(lambda args: func(*args), args_iterable)
            )
        except Exception:
            if not self._shared:
                self.executor.shutdown(wait=False, cancel_futures=True)
            g.log_stacktrace()
            raise
