# CLIP + 얼굴/신체 감지 스코어링 전용 Lambda 컨테이너 이미지.
# recommendations 앱이 boto3로 이 함수를 호출한다 (docs/IMPLEMENTATION.md 2026-08-16 결정).

FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# torch/torchvision은 이미지 용량을 줄이기 위해 CPU 전용 휠을 쓴다. 반드시 같은 인덱스에서
# 같이 설치할 것 — torchvision을 open-clip-torch의 의존성으로 나중에 따로 설치하면 torch와
# 빌드가 어긋나 "operator torchvision::nms does not exist" 에러가 난다(2026-08-16 확인).
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CLIP 가중치를 빌드 시점에 미리 받아 이미지에 포함시킨다. Lambda 런타임은 /tmp를 제외하고
# 읽기 전용 파일시스템이라, 첫 호출 때 가중치를 그 자리에서 다운로드하려고 하면
# "[Errno 30] Read-only file system"으로 실패한다(2026-08-16 확인). HF_HOME을 이미지 안
# 고정 경로로 지정해 빌드 때 받아두고, 런타임에도 같은 경로를 읽기만 하도록 한다.
ENV HF_HOME=/opt/hf_home
RUN python3 -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')"

COPY photo_measurement.py .
COPY dnn_models ./dnn_models
COPY handler.py .

# 로컬 소스 파일 권한(예: -rw-------)이 그대로 복사되면 Lambda 실행 사용자가 못 읽는 문제가
# 있어(PermissionError, 2026-08-16 확인) 명시적으로 읽기 권한을 열어준다. HF_HOME 캐시도
# 같은 이유로 함께 열어준다.
RUN chmod -R a+rX ${LAMBDA_TASK_ROOT} /opt/hf_home

CMD ["handler.lambda_handler"]
