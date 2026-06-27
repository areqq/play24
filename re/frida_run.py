import frida, sys, time

pkg = "com.play.play24m"
dev = frida.get_usb_device(timeout=10)

# attach po PID (arg) lub po nazwie "Play24"
target = sys.argv[1] if len(sys.argv) > 1 else "Play24"
if target.isdigit():
    target = int(target)
session = dev.attach(target)

with open("/home/areq/play24/unpin.js") as f:
    src = f.read()
script = session.create_script(src)
def on_msg(m, d):
    if m.get("type") == "send":
        print("[send]", m.get("payload"), flush=True)
    elif m.get("type") == "error":
        print("[error]", m.get("stack") or m.get("description"), flush=True)
script.on("message", on_msg)
script.load()
print("[runner] attached + script loaded", flush=True)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
