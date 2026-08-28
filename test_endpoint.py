import paramiko
import sys

HOST = "192.168.117.137"
USER = "raysunkr"
PASS = "456258mry"


def run(cmd, timeout=30):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=10)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    stdin.close()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print("OUT:")
    print(out)
    if err:
        print("ERR:")
        print(err)
    client.close()


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "/db"
    port = sys.argv[2] if len(sys.argv) > 2 else "7071"
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    cmd = (
        f"source /home/raysunkr/zan-benchmark/benchmarks/complete/venv/bin/activate && "
        f"python -c \"import requests,time; "
        f"url='http://127.0.0.1:{port}{endpoint}'; "
        f"t=time.time(); "
        f"r=requests.get(url, timeout={timeout}); "
        f"print(r.status_code, len(r.text), time.time()-t)\""
    )
    run(cmd, timeout=timeout + 5)
