import queue


q = queue.Queue()

q.put(b"111")
q.put(b"222")

res = b''
while not q.empty():
    res += q.get_nowait()

print(res)
print(q.qsize())
