# CLIP + 얼굴/신체 감지 스코어링 전용 Lambda 컨테이너 이미지.
# recommendations 앱이 boto3로 이 함수를 호출한다 (docs/IMPLEMENTATION.md 2026-08-16 결정).

FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# torch는 이미지 용량을 줄이기 위해 CPU 전용 휠을 별도 인덱스에서 설치
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY photo_measurement.py .
COPY dnn_models ./dnn_models
COPY handler.py .

CMD ["handler.lambda_handler"]
