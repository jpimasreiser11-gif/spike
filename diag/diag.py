import socket, time
for host in ("127.0.0.1", ""):
    t = time.perf_counter(); name = socket.getfqdn(host); print("getfqdn", repr(host), repr(name), round(time.perf_counter() - t, 2), "s")
