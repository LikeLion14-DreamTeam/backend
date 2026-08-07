import subprocess
import sys
from sshtunnel import SSHTunnelForwarder
import os, json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(BASE_DIR, "secrets.json")

with open(SECRET_FILE) as f:
    secrets = json.load(f)

def get_secret(key):
    try:
        return secrets[key]
    except KeyError:
        raise Exception(f"'{key}' 키 에러")

# EC2 SSH 정보
EC2_HOST = get_secret("EC2_HOST")
EC2_USER = get_secret("EC2_USER")
EC2_KEY_PATH = get_secret("EC2_KEY_PATH")

# RDS 정보
RDS_HOST = get_secret("RDS_HOST")
RDS_PORT = 3306
LOCAL_PORT = 3307

if __name__ == "__main__":
    # 터널 열기
    with SSHTunnelForwarder(
        (EC2_HOST, 22),
        ssh_username=EC2_USER,
        ssh_pkey=EC2_KEY_PATH,
        remote_bind_address=(RDS_HOST, RDS_PORT),
        local_bind_address=('127.0.0.1', LOCAL_PORT),
    ) as tunnel:
        print(f"SSH 터널: localhost:{LOCAL_PORT} → {RDS_HOST}:{RDS_PORT}")
        # Django 명령어 실행
        try:
            subprocess.run([sys.executable, "manage.py"] + sys.argv[1:], check=True)
        except subprocess.CalledProcessError as e:
            print("명령어 에러", e)