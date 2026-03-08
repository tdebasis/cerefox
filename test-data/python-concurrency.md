# Python Concurrency

Python offers three main concurrency models: threading, multiprocessing, and
asyncio. Choosing the right model depends on whether your bottleneck is I/O,
CPU, or a mix of both.

## The Global Interpreter Lock

The GIL (Global Interpreter Lock) is a mutex in CPython that allows only one
thread to execute Python bytecode at a time. This makes threading safe from
race conditions on Python objects, but it prevents true parallelism for
CPU-bound work.

For I/O-bound tasks — reading files, making network requests, querying databases
— threads remain useful because the GIL is released during I/O operations.
While one thread waits for a response, another can run Python code.

## Threading

The `threading` module provides OS-level threads. Threads share the same
memory space, making communication simple but synchronisation necessary.
Use `threading.Lock`, `threading.Event`, and `queue.Queue` to coordinate
between threads safely.

```python
import threading

def worker(name: str) -> None:
    print(f"Worker {name} starting")

threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

Threading is appropriate for I/O-bound tasks when you have a moderate number
of concurrent operations (up to a few hundred threads).

## Multiprocessing

The `multiprocessing` module spawns separate OS processes, each with its own
Python interpreter and GIL. This achieves true parallelism for CPU-bound tasks
at the cost of higher memory usage and inter-process communication overhead.

`ProcessPoolExecutor` from `concurrent.futures` provides a convenient high-level
interface. Communication between processes uses queues, pipes, or shared memory.

Use multiprocessing when your workload is CPU-intensive: numerical computation,
image processing, data parsing, machine learning inference.

## Asyncio and Coroutines

Asyncio is Python's built-in framework for cooperative multitasking. A single
thread runs an event loop that switches between coroutines at `await` points.
This avoids the overhead of thread creation and context switching, making it
highly efficient for large numbers of concurrent I/O operations.

```python
import asyncio

async def fetch(url: str) -> str:
    await asyncio.sleep(1)  # simulates an I/O wait
    return f"response from {url}"

async def main() -> None:
    results = await asyncio.gather(
        fetch("https://example.com"),
        fetch("https://python.org"),
    )
    print(results)

asyncio.run(main())
```

Asyncio is well-suited to web servers, API clients, and anything that makes
many concurrent network calls. Libraries like `httpx`, `aiohttp`, and `asyncpg`
are designed to work with it.

## Choosing the Right Model

| Workload | Recommended model |
|---|---|
| I/O-bound, moderate concurrency | threading |
| I/O-bound, high concurrency | asyncio |
| CPU-bound, parallelisable | multiprocessing |
| Mixed I/O + CPU | asyncio + ProcessPoolExecutor |

## Common Pitfalls

**Race conditions**: shared mutable state accessed from multiple threads without
locking. Use queues or locks to eliminate them.

**Deadlocks**: two threads each hold a lock the other needs. Acquire locks in a
consistent order to prevent this.

**Event loop blocking**: running synchronous CPU-heavy code inside an async
function blocks the entire event loop. Offload to a thread pool with
`asyncio.to_thread()` or `loop.run_in_executor()`.
