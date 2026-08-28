#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs

export DEBIAN_FRONTEND=noninteractive

# 1. system dependencies
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev postgresql postgresql-contrib \
    build-essential libpq-dev wrk linux-tools-common linux-tools-generic

# 2. PostgreSQL user/db
sudo -u postgres psql -c "CREATE USER tfb WITH PASSWORD 'tfb';" || true
sudo -u postgres psql -c "CREATE DATABASE tfb OWNER tfb;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE tfb TO tfb;"

# 3. Python venv
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install maturin
pip install -r requirements.txt

# 4. Build zan from source if no wheel available
if ! python -c "import _zan" 2>/dev/null; then
    cd ../..
    maturin develop --release
    cd - >/dev/null
fi

# 5. init DB
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" python init_db.py

# 6. kill old processes
pkill -f 'zan_app/app.py' || true
pkill -f 'zan_app/multi.py' || true
pkill -f 'flask_app.app:app' || true
sleep 1

# 7. start services
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" ZAN_DB_POOL_SIZE=64 PORT=7071 nohup python zan_app/app.py > logs/zan.log 2>&1 &
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" ZAN_DB_POOL_SIZE=16 PORT=7073 nohup python zan_app/multi.py > logs/zan_multi.log 2>&1 &
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" nohup gunicorn -k gevent -w $((2 * $(nproc) + 1)) -b 0.0.0.0:7072 flask_app.app:app > logs/flask.log 2>&1 &

# 8. wait for readiness
for port in 7071 7072 7073; do
    ready=0
    for i in {1..30}; do
        if curl -s "http://127.0.0.1:$port/plaintext" >/dev/null; then
            echo "Port $port ready"
            ready=1
            break
        fi
        sleep 1
    done
    if [ "$ready" -ne 1 ]; then
        echo "ERROR: Port $port did not become ready" >&2
        exit 1
    fi
done

# 9. correctness checks
BASE=http://127.0.0.1:7071 python check.py
BASE=http://127.0.0.1:7072 python check.py
BASE=http://127.0.0.1:7073 python check.py

echo "Deployment complete."
