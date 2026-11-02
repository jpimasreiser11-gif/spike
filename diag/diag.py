import os, platform, subprocess, sys, time
import psutil

print("exe", sys.executable, "real", os.path.realpath(sys.executable), platform.platform(), "psutil", psutil.__version__)
code = ("import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); "
        "print(s.getsockname()[1], flush=True); time.sleep(25)")
for label, argv in (("framework", [sys.executable, "-c", code]),
                    ("realpath", [os.path.realpath(sys.executable), "-c", code])):
    print("=====", label, argv[0])
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, start_new_session=True)
    for i in range(5):
        try:
            print(i, "name", psutil.Process(p.pid).name(), "exe", psutil.Process(p.pid).exe())
        except Exception as e:
            print(i, "name err", repr(e))
        time.sleep(0.05)
    print("port", p.stdout.readline().strip())
    proc = psutil.Process(p.pid)
    print("name now", proc.name(), "children", proc.children(recursive=True))
    for f in ("net_connections", "memory_info", "cmdline"):
        try:
            print(f, getattr(proc, f)())
        except Exception as e:
            print(f, "ERR", repr(e))
    try:
        print("sys-wide", [c for c in psutil.net_connections("tcp") if c.pid == p.pid])
    except Exception as e:
        print("sys-wide ERR", repr(e))
    r = subprocess.run(["lsof", "-nP", "-a", "-p", str(p.pid), "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True)
    print("lsof", r.returncode, r.stdout, r.stderr)
    p.kill()
    p.wait()
r = subprocess.run(["codesign", "-dv", "--verbose=2", os.path.realpath(sys.executable)], capture_output=True, text=True)
print("codesign", r.stderr)
