import io
import paramiko
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HOST = "192.168.117.137"
USER = "raysunkr"
PASS = "456258mry"


def stream_exec(client, cmd, timeout=3600):
    print(f"\n>>> {cmd}\n")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    stdin.close()
    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            data = stdout.channel.recv(4096).decode("utf-8", errors="replace")
            if data:
                print(data, end="")
        if stderr.channel.recv_stderr_ready():
            data = stderr.channel.recv_stderr(4096).decode("utf-8", errors="replace")
            if data:
                print(data, end="", file=sys.stderr)
        time.sleep(0.05)
    while stdout.channel.recv_ready():
        data = stdout.channel.recv(4096).decode("utf-8", errors="replace")
        if data:
            print(data, end="")
    while stderr.channel.recv_stderr_ready():
        data = stderr.channel.recv_stderr(4096).decode("utf-8", errors="replace")
        if data:
            print(data, end="", file=sys.stderr)
    exit_status = stdout.channel.recv_exit_status()
    print(f"\n<<< exit status: {exit_status}\n")
    return exit_status


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    stream_exec(
        client,
        "source $HOME/.cargo/env && cd /home/raysunkr/zan-benchmark/benchmarks/complete && bash benchmark.sh",
        timeout=3600,
    )
    client.close()


if __name__ == "__main__":
    main()
