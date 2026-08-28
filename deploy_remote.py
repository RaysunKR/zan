import io
import paramiko
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

HOST = "192.168.117.137"
USER = "raysunkr"
PASS = "456258mry"
LOCAL_TAR = r"C:\Users\raysu\AppData\Local\Temp\zan-update.tar.gz"
REMOTE_TAR = "/home/raysunkr/zan-update.tar.gz"
REPO_DIR = "/home/raysunkr/zan-benchmark"

def stream_exec(client, cmd, timeout=1200):
    print(f"\n>>> {cmd}\n")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    # Close stdin so remote sees EOF
    stdin.close()
    # Stream output
    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            data = stdout.channel.recv(4096).decode("utf-8", errors="replace")
            if data:
                print(data, end="")
        if stderr.channel.recv_stderr_ready():
            data = stderr.channel.recv_stderr(4096).decode("utf-8", errors="replace")
            if data:
                print(data, end="", file=__import__("sys").stderr)
        time.sleep(0.05)
    # Drain remaining
    while stdout.channel.recv_ready():
        data = stdout.channel.recv(4096).decode("utf-8", errors="replace")
        if data:
            print(data, end="")
    while stderr.channel.recv_stderr_ready():
        data = stderr.channel.recv_stderr(4096).decode("utf-8", errors="replace")
        if data:
            print(data, end="", file=__import__("sys").stderr)
    exit_status = stdout.channel.recv_exit_status()
    print(f"\n<<< exit status: {exit_status}\n")
    return exit_status


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)

    sftp = client.open_sftp()
    print(f"Uploading {LOCAL_TAR} -> {REMOTE_TAR}")
    sftp.put(LOCAL_TAR, REMOTE_TAR)
    sftp.close()

    # Extract update, normalize shell scripts line endings, and deploy
    stream_exec(client, f"cd {REPO_DIR} && tar -xzf {REMOTE_TAR}")
    stream_exec(client, f"cd {REPO_DIR} && find . -name '*.sh' -exec sed -i 's/\\r$//' {{}} +")
    stream_exec(client, f"source $HOME/.cargo/env && cd {REPO_DIR}/benchmarks/complete && bash deploy.sh", timeout=1800)

    client.close()


if __name__ == "__main__":
    main()
