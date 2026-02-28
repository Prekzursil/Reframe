Running in Docker worker:
  input:   /tmp/reframe-worktrees/mainline-stabilize-2026-03-01/samples/sample.wav
  backend: pyannote
  extra:   diarize-pyannote

time="2026-03-01T00:52:05+02:00" level=warning msg="/tmp/reframe-worktrees/mainline-stabilize-2026-03-01/infra/docker-compose.yml: the attribute `version` is obsolete, it will be ignored, please remove it to avoid potential confusion"
time="2026-03-01T00:52:06+02:00" level=warning msg="Found orphan containers ([infra-db-1]) for this project. If you removed or renamed this service in your compose file, you can run this command with the --remove-orphans flag to clean it up."
 Container infra-redis-1 Running 
 Image infra-worker Building 
#1 [internal] load local bake definitions
#1 reading from stdin 559B done
#1 DONE 0.0s

#2 [internal] load build definition from Dockerfile.worker
#2 transferring dockerfile: 686B done
#2 DONE 0.0s

#3 [internal] load metadata for docker.io/library/python:3.11-slim
#3 ...

#4 [auth] library/python:pull token for registry-1.docker.io
#4 DONE 0.0s

#3 [internal] load metadata for docker.io/library/python:3.11-slim
#3 DONE 1.0s

#5 [internal] load .dockerignore
#5 transferring context: 2B done
#5 DONE 0.0s

#6 [ 1/10] FROM docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39
#6 resolve docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39 0.0s done
#6 DONE 0.0s

#7 [internal] load build context
#7 transferring context: 1.95MB 0.0s done
#7 DONE 0.1s

#8 [ 4/10] COPY services/worker/requirements.txt ./requirements.txt
#8 CACHED

#9 [ 2/10] WORKDIR /worker
#9 CACHED

#10 [ 3/10] RUN apt-get update     && apt-get install -y --no-install-recommends ffmpeg     && rm -rf /var/lib/apt/lists/*
#10 CACHED

#11 [ 5/10] RUN pip install --no-cache-dir -r requirements.txt
#11 CACHED

#12 [ 6/10] COPY packages/media-core /worker/packages/media-core
#12 DONE 0.0s

#13 [ 7/10] RUN pip install --no-cache-dir '/worker/packages/media-core[transcribe-faster-whisper,translate-local]'
#13 1.570 Processing ./packages/media-core
#13 1.573   Installing build dependencies: started
#13 4.495   Installing build dependencies: finished with status 'done'
#13 4.496   Getting requirements to build wheel: started
#13 4.859   Getting requirements to build wheel: finished with status 'done'
#13 4.860   Preparing metadata (pyproject.toml): started
#13 5.226   Preparing metadata (pyproject.toml): finished with status 'done'
#13 5.235 Requirement already satisfied: pydantic>=2.7 in /usr/local/lib/python3.11/site-packages (from media-core==0.1.0) (2.12.5)
#13 5.466 Collecting faster-whisper>=1.0.0 (from media-core==0.1.0)
#13 5.660   Downloading faster_whisper-1.2.1-py3-none-any.whl.metadata (16 kB)
#13 5.735 Collecting argostranslate>=1.9.0 (from media-core==0.1.0)
#13 5.795   Downloading argostranslate-1.11.0-py3-none-any.whl.metadata (9.7 kB)
#13 6.218 Collecting ctranslate2<5,>=4.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.256   Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 6.300 Collecting minisbd (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.337   Downloading minisbd-0.9.3-py3-none-any.whl.metadata (47 kB)
#13 6.372      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 47.2/47.2 kB 1.4 MB/s eta 0:00:00
#13 6.380 Requirement already satisfied: packaging in /usr/local/lib/python3.11/site-packages (from argostranslate>=1.9.0->media-core==0.1.0) (26.0)
#13 6.419 Collecting sacremoses<0.2,>=0.0.53 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.459   Downloading sacremoses-0.1.1-py3-none-any.whl.metadata (8.3 kB)
#13 6.534 Collecting sentencepiece<0.3,>=0.2.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.572   Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 6.730 Collecting spacy (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.769   Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (27 kB)
#13 6.813 Collecting stanza==1.10.1 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.850   Downloading stanza-1.10.1-py3-none-any.whl.metadata (13 kB)
#13 7.124 Collecting emoji (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.164   Downloading emoji-2.15.0-py3-none-any.whl.metadata (5.7 kB)
#13 7.378 Collecting numpy (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.417   Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (6.6 kB)
#13 7.610 Collecting protobuf>=3.15.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.648   Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl.metadata (595 bytes)
#13 7.698 Collecting requests (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.736   Downloading requests-2.32.5-py3-none-any.whl.metadata (4.9 kB)
#13 7.783 Collecting networkx (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.821   Downloading networkx-3.6.1-py3-none-any.whl.metadata (6.8 kB)
#13 7.913 Collecting torch>=1.3.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.952   Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (31 kB)
#13 8.019 Collecting tqdm (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.057   Downloading tqdm-4.67.3-py3-none-any.whl.metadata (57 kB)
#13 8.069      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 57.7/57.7 kB 5.4 MB/s eta 0:00:00
#13 8.157 Collecting huggingface-hub>=0.21 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.194   Downloading huggingface_hub-1.5.0-py3-none-any.whl.metadata (13 kB)
#13 8.384 Collecting tokenizers<1,>=0.13 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.429   Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (7.3 kB)
#13 8.544 Collecting onnxruntime<2,>=1.14 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.582   Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (5.0 kB)
#13 8.652 Collecting av>=11 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.691   Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (4.6 kB)
#13 8.697 Requirement already satisfied: annotated-types>=0.6.0 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.7.0)
#13 8.698 Requirement already satisfied: pydantic-core==2.41.5 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (2.41.5)
#13 8.698 Requirement already satisfied: typing-extensions>=4.14.1 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (4.15.0)
#13 8.700 Requirement already satisfied: typing-inspection>=0.4.2 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.4.2)
#13 8.707 Requirement already satisfied: setuptools in /usr/local/lib/python3.11/site-packages (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0) (79.0.1)
#13 8.765 Collecting pyyaml<7,>=5.3 (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.803   Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.4 kB)
#13 8.925 Collecting filelock>=3.10.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.964   Downloading filelock-3.24.3-py3-none-any.whl.metadata (2.0 kB)
#13 9.011 Collecting fsspec>=2023.5.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.048   Downloading fsspec-2026.2.0-py3-none-any.whl.metadata (10 kB)
#13 9.124 Collecting hf-xet<2.0.0,>=1.2.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.162   Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (4.9 kB)
#13 9.209 Collecting httpx<1,>=0.23.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.250   Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
#13 9.304 Collecting typer (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.341   Downloading typer-0.24.1-py3-none-any.whl.metadata (16 kB)
#13 9.383 Collecting flatbuffers (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.424   Downloading flatbuffers-25.12.19-py2.py3-none-any.whl.metadata (1.0 kB)
#13 9.487 Collecting sympy (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.529   Downloading sympy-1.14.0-py3-none-any.whl.metadata (12 kB)
#13 10.05 Collecting regex (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.10   Downloading regex-2026.2.28-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (40 kB)
#13 10.13      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.4/40.4 kB 1.6 MB/s eta 0:00:00
#13 10.13 Requirement already satisfied: click in /usr/local/lib/python3.11/site-packages (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0) (8.3.1)
#13 10.21 Collecting joblib (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.25   Downloading joblib-1.5.3-py3-none-any.whl.metadata (5.5 kB)
#13 10.38 Collecting spacy-legacy<3.1.0,>=3.0.11 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.42   Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl.metadata (2.8 kB)
#13 10.47 Collecting spacy-loggers<2.0.0,>=1.0.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.52   Downloading spacy_loggers-1.0.5-py3-none-any.whl.metadata (23 kB)
#13 10.62 Collecting murmurhash<1.1.0,>=0.28.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.66   Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.3 kB)
#13 10.71 Collecting cymem<2.1.0,>=2.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.75   Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (9.7 kB)
#13 10.81 Collecting preshed<3.1.0,>=3.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.85   Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.5 kB)
#13 11.00 Collecting thinc<8.4.0,>=8.3.4 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.04   Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (15 kB)
#13 11.08 Collecting wasabi<1.2.0,>=0.9.1 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.12   Downloading wasabi-1.1.3-py3-none-any.whl.metadata (28 kB)
#13 11.19 Collecting srsly<3.0.0,>=2.4.3 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.23   Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (19 kB)
#13 11.27 Collecting catalogue<2.1.0,>=2.0.6 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.31   Downloading catalogue-2.0.10-py3-none-any.whl.metadata (14 kB)
#13 11.35 Collecting weasel<0.5.0,>=0.4.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.38   Downloading weasel-0.4.3-py3-none-any.whl.metadata (4.6 kB)
#13 11.49 Collecting typer-slim<1.0.0,>=0.3.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.53   Downloading typer_slim-0.24.0-py3-none-any.whl.metadata (4.2 kB)
#13 11.60 Collecting jinja2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.64   Downloading jinja2-3.1.6-py3-none-any.whl.metadata (2.9 kB)
#13 11.74 Collecting anyio (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 11.78   Downloading anyio-4.12.1-py3-none-any.whl.metadata (4.3 kB)
#13 11.82 Collecting certifi (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 11.86   Downloading certifi-2026.2.25-py3-none-any.whl.metadata (2.5 kB)
#13 11.90 Collecting httpcore==1.* (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 11.94   Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
#13 11.98 Collecting idna (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 12.02   Downloading idna-3.11-py3-none-any.whl.metadata (8.4 kB)
#13 12.06 Collecting h11>=0.16 (from httpcore==1.*->httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 12.10   Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
#13 12.31 Collecting charset_normalizer<4,>=2 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.42   Downloading charset_normalizer-3.4.4-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (37 kB)
#13 12.49 Collecting urllib3<3,>=1.21.1 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.53   Downloading urllib3-2.6.3-py3-none-any.whl.metadata (6.9 kB)
#13 12.65 Collecting blis<1.4.0,>=1.3.0 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.69   Downloading blis-1.3.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (7.5 kB)
#13 12.74 Collecting confection<1.0.0,>=0.0.1 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.78   Downloading confection-0.1.5-py3-none-any.whl.metadata (19 kB)
#13 12.88 Collecting cuda-bindings==12.9.4 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.93   Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (2.6 kB)
#13 12.97 Collecting nvidia-cuda-nvrtc-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.01   Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 13.05 Collecting nvidia-cuda-runtime-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.09   Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 13.13 Collecting nvidia-cuda-cupti-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.16   Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 13.20 Collecting nvidia-cudnn-cu12==9.10.2.21 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.24   Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 13.28 Collecting nvidia-cublas-cu12==12.8.4.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.32   Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 13.36 Collecting nvidia-cufft-cu12==11.3.3.83 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.40   Downloading nvidia_cufft_cu12-11.3.3.83-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 13.43 Collecting nvidia-curand-cu12==10.3.9.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.47   Downloading nvidia_curand_cu12-10.3.9.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 13.52 Collecting nvidia-cusolver-cu12==11.7.3.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.56   Downloading nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 13.60 Collecting nvidia-cusparse-cu12==12.5.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.64   Downloading nvidia_cusparse_cu12-12.5.8.93-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 13.67 Collecting nvidia-cusparselt-cu12==0.7.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.71   Downloading nvidia_cusparselt_cu12-0.7.1-py3-none-manylinux2014_x86_64.whl.metadata (7.0 kB)
#13 13.75 Collecting nvidia-nccl-cu12==2.27.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.79   Downloading nvidia_nccl_cu12-2.27.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.0 kB)
#13 13.82 Collecting nvidia-nvshmem-cu12==3.4.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.86   Downloading nvidia_nvshmem_cu12-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.1 kB)
#13 13.90 Collecting nvidia-nvtx-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.94   Downloading nvidia_nvtx_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 13.98 Collecting nvidia-nvjitlink-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.02   Downloading nvidia_nvjitlink_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 14.06 Collecting nvidia-cufile-cu12==1.13.1.3 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.10   Downloading nvidia_cufile_cu12-1.13.1.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 14.14 Collecting triton==3.6.0 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.18   Downloading triton-3.6.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (1.7 kB)
#13 14.22 Collecting cuda-pathfinder~=1.1 (from cuda-bindings==12.9.4->torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.26   Downloading cuda_pathfinder-1.4.0-py3-none-any.whl.metadata (1.9 kB)
#13 14.39 Collecting mpmath<1.4,>=1.1.0 (from sympy->onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 14.42   Downloading mpmath-1.3.0-py3-none-any.whl.metadata (8.6 kB)
#13 14.48 Collecting shellingham>=1.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 14.52   Downloading shellingham-1.5.4-py2.py3-none-any.whl.metadata (3.5 kB)
#13 14.59 Collecting rich>=12.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 14.63   Downloading rich-14.3.3-py3-none-any.whl.metadata (18 kB)
#13 14.67 Collecting annotated-doc>=0.0.2 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 14.71   Downloading annotated_doc-0.0.4-py3-none-any.whl.metadata (6.6 kB)
#13 14.77 Collecting cloudpathlib<1.0.0,>=0.7.0 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.81   Downloading cloudpathlib-0.23.0-py3-none-any.whl.metadata (16 kB)
#13 14.85 Collecting smart-open<8.0.0,>=5.2.1 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.89   Downloading smart_open-7.5.1-py3-none-any.whl.metadata (24 kB)
#13 14.98 Collecting MarkupSafe>=2.0 (from jinja2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.02   Downloading markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.7 kB)
#13 15.17 Collecting markdown-it-py>=2.2.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 15.21   Downloading markdown_it_py-4.0.0-py3-none-any.whl.metadata (7.3 kB)
#13 15.25 Collecting pygments<3.0.0,>=2.13.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 15.29   Downloading pygments-2.19.2-py3-none-any.whl.metadata (2.5 kB)
#13 15.54 Collecting wrapt (from smart-open<8.0.0,>=5.2.1->weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.58   Downloading wrapt-2.1.1-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (7.4 kB)
#13 15.67 Collecting mdurl~=0.1 (from markdown-it-py>=2.2.0->rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 15.71   Downloading mdurl-0.1.2-py3-none-any.whl.metadata (1.6 kB)
#13 15.77 Downloading argostranslate-1.11.0-py3-none-any.whl (41 kB)
#13 15.78    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 41.6/41.6 kB 12.7 MB/s eta 0:00:00
#13 15.97 Downloading stanza-1.10.1-py3-none-any.whl (1.1 MB)
#13 16.15    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 6.3 MB/s eta 0:00:00
#13 16.19 Downloading faster_whisper-1.2.1-py3-none-any.whl (1.1 MB)
#13 16.32    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 8.2 MB/s eta 0:00:00
#13 16.36 Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl (40.8 MB)
#13 21.66    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.8/40.8 MB 9.0 MB/s eta 0:00:00
#13 21.70 Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (38.8 MB)
#13 26.99    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 38.8/38.8 MB 7.1 MB/s eta 0:00:00
#13 27.03 Downloading huggingface_hub-1.5.0-py3-none-any.whl (596 kB)
#13 27.10    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 596.3/596.3 kB 8.7 MB/s eta 0:00:00
#13 27.14 Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (17.1 MB)
#13 29.25    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 17.1/17.1 MB 8.0 MB/s eta 0:00:00
#13 29.29 Downloading sacremoses-0.1.1-py3-none-any.whl (897 kB)
#13 29.39    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 897.5/897.5 kB 9.7 MB/s eta 0:00:00
#13 29.43 Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (1.4 MB)
#13 29.62    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.4/1.4 MB 7.3 MB/s eta 0:00:00
#13 29.66 Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (3.3 MB)
#13 30.20    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.3/3.3 MB 6.1 MB/s eta 0:00:00
#13 30.24 Downloading tqdm-4.67.3-py3-none-any.whl (78 kB)
#13 30.25    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.4/78.4 kB 6.5 MB/s eta 0:00:00
#13 30.30 Downloading minisbd-0.9.3-py3-none-any.whl (40 kB)
#13 30.33    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.9/40.9 kB 2.5 MB/s eta 0:00:00
#13 30.38 Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (32.3 MB)
#13 53.97    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 32.3/32.3 MB 1.9 MB/s eta 0:00:00
#13 54.02 Downloading catalogue-2.0.10-py3-none-any.whl (17 kB)
#13 54.11 Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (244 kB)
#13 54.16    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 244.5/244.5 kB 4.9 MB/s eta 0:00:00
#13 54.21 Downloading filelock-3.24.3-py3-none-any.whl (24 kB)
#13 54.26 Downloading fsspec-2026.2.0-py3-none-any.whl (202 kB)
#13 54.31    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 202.5/202.5 kB 4.3 MB/s eta 0:00:00
#13 54.38 Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.2 MB)
#13 58.36    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.2/4.2 MB 1.0 MB/s eta 0:00:00
#13 58.41 Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
#13 58.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 73.5/73.5 kB 3.8 MB/s eta 0:00:00
#13 58.47 Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
#13 58.51    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.8/78.8 kB 2.7 MB/s eta 0:00:00
#13 58.55 Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (128 kB)
#13 58.64    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 128.4/128.4 kB 1.4 MB/s eta 0:00:00
#13 58.70 Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (16.9 MB)
#13 61.17    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 16.9/16.9 MB 6.9 MB/s eta 0:00:00
#13 61.21 Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (824 kB)
#13 61.32    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 824.7/824.7 kB 7.2 MB/s eta 0:00:00
#13 61.36 Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl (324 kB)
#13 61.40    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 324.3/324.3 kB 8.6 MB/s eta 0:00:00
#13 61.44 Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (806 kB)
#13 61.56    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 806.6/806.6 kB 6.7 MB/s eta 0:00:00
#13 61.60 Downloading requests-2.32.5-py3-none-any.whl (64 kB)
#13 61.61    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64.7/64.7 kB 5.5 MB/s eta 0:00:00
#13 61.65 Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl (29 kB)
#13 61.69 Downloading spacy_loggers-1.0.5-py3-none-any.whl (22 kB)
#13 61.74 Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.1 MB)
#13 61.89    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 8.2 MB/s eta 0:00:00
#13 61.93 Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.1 MB)
#13 62.46    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.1/4.1 MB 7.7 MB/s eta 0:00:00
#13 62.51 Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (915.6 MB)
#13 213.7    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 915.6/915.6 MB 7.2 MB/s eta 0:00:00
#13 213.8 Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (12.2 MB)
#13 215.8    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 12.2/12.2 MB 5.8 MB/s eta 0:00:00
#13 215.8 Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl (594.3 MB)
#13 299.2    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 594.3/594.3 MB 5.4 MB/s eta 0:00:00
#13 299.2 Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (10.2 MB)
#13 300.7    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.2/10.2 MB 7.2 MB/s eta 0:00:00
#13 300.7 Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl (88.0 MB)
#13 313.9    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 88.0/88.0 MB 7.0 MB/s eta 0:00:00
#13 313.9 Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (954 kB)
#13 314.1    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 954.8/954.8 kB 6.2 MB/s eta 0:00:00
#13 314.1 Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl (706.8 MB)
#13 429.6    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 706.8/706.8 MB 8.0 MB/s eta 0:00:00
#13 429.7 Downloading nvidia_cufft_cu12-11.3.3.83-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (193.1 MB)
#13 456.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 193.1/193.1 MB 7.5 MB/s eta 0:00:00
#13 456.6 Downloading nvidia_cufile_cu12-1.13.1.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.2 MB)
#13 457.2    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.2/1.2 MB 2.0 MB/s eta 0:00:00
#13 457.2 Downloading nvidia_curand_cu12-10.3.9.90-py3-none-manylinux_2_27_x86_64.whl (63.6 MB)
#13 466.2    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 63.6/63.6 MB 6.0 MB/s eta 0:00:00
#13 466.2 Downloading nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl (267.5 MB)
#13 506.1    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 267.5/267.5 MB 7.3 MB/s eta 0:00:00
#13 506.2 Downloading nvidia_cusparse_cu12-12.5.8.93-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (288.2 MB)
#13 558.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 288.2/288.2 MB 4.5 MB/s eta 0:00:00
#13 558.2 Downloading nvidia_cusparselt_cu12-0.7.1-py3-none-manylinux2014_x86_64.whl (287.2 MB)
#13 613.7    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 287.2/287.2 MB 8.0 MB/s eta 0:00:00
#13 613.7 Downloading nvidia_nccl_cu12-2.27.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (322.3 MB)
#13 661.3    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 322.3/322.3 MB 5.9 MB/s eta 0:00:00
#13 661.3 Downloading nvidia_nvjitlink_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl (39.3 MB)
#13 666.9    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 39.3/39.3 MB 6.3 MB/s eta 0:00:00
#13 667.0 Downloading nvidia_nvshmem_cu12-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (139.1 MB)
#13 687.8    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 139.1/139.1 MB 2.6 MB/s eta 0:00:00
#13 687.9 Downloading nvidia_nvtx_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (89 kB)
#13 687.9    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 90.0/90.0 kB 7.6 MB/s eta 0:00:00
#13 687.9 Downloading triton-3.6.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (188.2 MB)
#13 715.2    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 188.2/188.2 MB 5.1 MB/s eta 0:00:00
#13 715.3 Downloading networkx-3.6.1-py3-none-any.whl (2.1 MB)
#13 715.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.1/2.1 MB 8.5 MB/s eta 0:00:00
#13 715.6 Downloading sympy-1.14.0-py3-none-any.whl (6.3 MB)
#13 716.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.3/6.3 MB 6.6 MB/s eta 0:00:00
#13 716.6 Downloading typer_slim-0.24.0-py3-none-any.whl (3.4 kB)
#13 716.6 Downloading typer-0.24.1-py3-none-any.whl (56 kB)
#13 716.6    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 56.1/56.1 kB 8.8 MB/s eta 0:00:00
#13 716.6 Downloading wasabi-1.1.3-py3-none-any.whl (27 kB)
#13 716.7 Downloading weasel-0.4.3-py3-none-any.whl (50 kB)
#13 716.7    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 50.8/50.8 kB 24.1 MB/s eta 0:00:00
#13 716.7 Downloading emoji-2.15.0-py3-none-any.whl (608 kB)
#13 716.8    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 608.4/608.4 kB 9.4 MB/s eta 0:00:00
#13 716.8 Downloading flatbuffers-25.12.19-py2.py3-none-any.whl (26 kB)
#13 716.9 Downloading jinja2-3.1.6-py3-none-any.whl (134 kB)
#13 716.9    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 134.9/134.9 kB 19.4 MB/s eta 0:00:00
#13 716.9 Downloading joblib-1.5.3-py3-none-any.whl (309 kB)
#13 717.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 309.1/309.1 kB 9.3 MB/s eta 0:00:00
#13 717.0 Downloading regex-2026.2.28-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (800 kB)
#13 717.1    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 800.2/800.2 kB 10.3 MB/s eta 0:00:00
#13 717.1 Downloading annotated_doc-0.0.4-py3-none-any.whl (5.3 kB)
#13 717.2 Downloading blis-1.3.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (11.4 MB)
#13 718.4    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 11.4/11.4 MB 9.3 MB/s eta 0:00:00
#13 718.4 Downloading certifi-2026.2.25-py3-none-any.whl (153 kB)
#13 718.4    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 153.7/153.7 kB 15.1 MB/s eta 0:00:00
#13 718.5 Downloading charset_normalizer-3.4.4-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (151 kB)
#13 718.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 151.6/151.6 kB 13.9 MB/s eta 0:00:00
#13 718.5 Downloading cloudpathlib-0.23.0-py3-none-any.whl (62 kB)
#13 718.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.8/62.8 kB 16.1 MB/s eta 0:00:00
#13 718.6 Downloading confection-0.1.5-py3-none-any.whl (35 kB)
#13 718.6 Downloading idna-3.11-py3-none-any.whl (71 kB)
#13 718.6    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 71.0/71.0 kB 16.4 MB/s eta 0:00:00
#13 718.7 Downloading markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (22 kB)
#13 718.7 Downloading mpmath-1.3.0-py3-none-any.whl (536 kB)
#13 718.8    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 536.2/536.2 kB 9.8 MB/s eta 0:00:00
#13 718.8 Downloading rich-14.3.3-py3-none-any.whl (310 kB)
#13 718.8    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 310.5/310.5 kB 11.8 MB/s eta 0:00:00
#13 718.9 Downloading shellingham-1.5.4-py2.py3-none-any.whl (9.8 kB)
#13 718.9 Downloading smart_open-7.5.1-py3-none-any.whl (64 kB)
#13 718.9    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64.1/64.1 kB 13.2 MB/s eta 0:00:00
#13 719.0 Downloading urllib3-2.6.3-py3-none-any.whl (131 kB)
#13 719.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 131.6/131.6 kB 11.0 MB/s eta 0:00:00
#13 719.0 Downloading anyio-4.12.1-py3-none-any.whl (113 kB)
#13 719.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 113.6/113.6 kB 12.3 MB/s eta 0:00:00
#13 719.1 Downloading cuda_pathfinder-1.4.0-py3-none-any.whl (38 kB)
#13 719.1 Downloading h11-0.16.0-py3-none-any.whl (37 kB)
#13 719.1 Downloading markdown_it_py-4.0.0-py3-none-any.whl (87 kB)
#13 719.2    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 87.3/87.3 kB 5.5 MB/s eta 0:00:00
#13 719.2 Downloading pygments-2.19.2-py3-none-any.whl (1.2 MB)
#13 719.3    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.2/1.2 MB 8.8 MB/s eta 0:00:00
#13 719.4 Downloading wrapt-2.1.1-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (113 kB)
#13 719.4    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 113.9/113.9 kB 11.9 MB/s eta 0:00:00
#13 719.4 Downloading mdurl-0.1.2-py3-none-any.whl (10.0 kB)
#13 734.7 Building wheels for collected packages: media-core
#13 734.7   Building wheel for media-core (pyproject.toml): started
#13 735.6   Building wheel for media-core (pyproject.toml): finished with status 'done'
#13 735.6   Created wheel for media-core: filename=media_core-0.1.0-py3-none-any.whl size=32578 sha256=107eade001561cca77fbb751efc8305d1030cb9f80c3bccc346f0a8dab918618
#13 735.6   Stored in directory: /tmp/pip-ephem-wheel-cache-y8xhlg1d/wheels/b3/1b/bb/820896c27a04aa0a1c42405a1e408db8e7a4c37ac4ee5b822f
#13 735.6 Successfully built media-core
#13 736.3 Installing collected packages: nvidia-cusparselt-cu12, mpmath, flatbuffers, wrapt, wasabi, urllib3, triton, tqdm, sympy, spacy-loggers, spacy-legacy, shellingham, sentencepiece, regex, pyyaml, pygments, protobuf, nvidia-nvtx-cu12, nvidia-nvshmem-cu12, nvidia-nvjitlink-cu12, nvidia-nccl-cu12, nvidia-curand-cu12, nvidia-cufile-cu12, nvidia-cuda-runtime-cu12, nvidia-cuda-nvrtc-cu12, nvidia-cuda-cupti-cu12, nvidia-cublas-cu12, numpy, networkx, murmurhash, mdurl, MarkupSafe, joblib, idna, hf-xet, h11, fsspec, filelock, emoji, cymem, cuda-pathfinder, cloudpathlib, charset_normalizer, certifi, catalogue, av, annotated-doc, srsly, smart-open, sacremoses, requests, preshed, onnxruntime, nvidia-cusparse-cu12, nvidia-cufft-cu12, nvidia-cudnn-cu12, markdown-it-py, jinja2, httpcore, cuda-bindings, ctranslate2, blis, anyio, rich, nvidia-cusolver-cu12, minisbd, media-core, httpx, confection, typer, torch, thinc, typer-slim, stanza, huggingface-hub, weasel, tokenizers, spacy, faster-whisper, argostranslate
#13 867.4 Successfully installed MarkupSafe-3.0.3 annotated-doc-0.0.4 anyio-4.12.1 argostranslate-1.11.0 av-16.1.0 blis-1.3.3 catalogue-2.0.10 certifi-2026.2.25 charset_normalizer-3.4.4 cloudpathlib-0.23.0 confection-0.1.5 ctranslate2-4.7.1 cuda-bindings-12.9.4 cuda-pathfinder-1.4.0 cymem-2.0.13 emoji-2.15.0 faster-whisper-1.2.1 filelock-3.24.3 flatbuffers-25.12.19 fsspec-2026.2.0 h11-0.16.0 hf-xet-1.3.2 httpcore-1.0.9 httpx-0.28.1 huggingface-hub-1.5.0 idna-3.11 jinja2-3.1.6 joblib-1.5.3 markdown-it-py-4.0.0 mdurl-0.1.2 media-core-0.1.0 minisbd-0.9.3 mpmath-1.3.0 murmurhash-1.0.15 networkx-3.6.1 numpy-2.4.2 nvidia-cublas-cu12-12.8.4.1 nvidia-cuda-cupti-cu12-12.8.90 nvidia-cuda-nvrtc-cu12-12.8.93 nvidia-cuda-runtime-cu12-12.8.90 nvidia-cudnn-cu12-9.10.2.21 nvidia-cufft-cu12-11.3.3.83 nvidia-cufile-cu12-1.13.1.3 nvidia-curand-cu12-10.3.9.90 nvidia-cusolver-cu12-11.7.3.90 nvidia-cusparse-cu12-12.5.8.93 nvidia-cusparselt-cu12-0.7.1 nvidia-nccl-cu12-2.27.5 nvidia-nvjitlink-cu12-12.8.93 nvidia-nvshmem-cu12-3.4.5 nvidia-nvtx-cu12-12.8.90 onnxruntime-1.24.2 preshed-3.0.12 protobuf-7.34.0 pygments-2.19.2 pyyaml-6.0.3 regex-2026.2.28 requests-2.32.5 rich-14.3.3 sacremoses-0.1.1 sentencepiece-0.2.1 shellingham-1.5.4 smart-open-7.5.1 spacy-3.8.11 spacy-legacy-3.0.12 spacy-loggers-1.0.5 srsly-2.5.2 stanza-1.10.1 sympy-1.14.0 thinc-8.3.10 tokenizers-0.22.2 torch-2.10.0 tqdm-4.67.3 triton-3.6.0 typer-0.24.1 typer-slim-0.24.0 urllib3-2.6.3 wasabi-1.1.3 weasel-0.4.3 wrapt-2.1.1
#13 867.4 WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv
#13 867.6 
#13 867.6 [notice] A new release of pip is available: 24.0 -> 26.0.1
#13 867.6 [notice] To update, run: pip install --upgrade pip
#13 DONE 879.3s

#14 [ 8/10] COPY apps/api /worker/apps/api
#14 DONE 0.6s

#15 [ 9/10] COPY services/worker /worker
#15 DONE 0.1s

#16 [10/10] COPY scripts /worker/scripts
#16 DONE 0.1s

#17 exporting to image
#17 exporting layers
#17 exporting layers 298.0s done
#17 exporting manifest sha256:5345c2b728bca5964b2d351ca3e867ac59355cd63cf2692129d04e88ff0b5d5e 0.0s done
#17 exporting config sha256:e4377edf657bec19f765ea9c95128aa18c6812fb40f8163449d02107f55f5ceb 0.0s done
#17 exporting attestation manifest sha256:ec6ad763ddbd2db59a12be39ae46e180acfa6f02841edd1985c855f6f125e912 0.0s done
#17 exporting manifest list sha256:967bb77ca894284dfa1671a8cf78504b6286c4a9f5fec055a998f85e31b65410 0.0s done
#17 naming to docker.io/library/infra-worker:latest
#17 naming to docker.io/library/infra-worker:latest 0.0s done
#17 unpacking to docker.io/library/infra-worker:latest
#17 unpacking to docker.io/library/infra-worker:latest 107.5s done
#17 DONE 406.0s

#18 resolving provenance for metadata file
#18 DONE 0.0s
 Image infra-worker Built 
 Container infra-worker-run-c630fd448e05 Creating 
 Container infra-worker-run-c630fd448e05 Created 
Processing ./packages/media-core
  Installing build dependencies: started
  Installing build dependencies: finished with status 'done'
  Getting requirements to build wheel: started
  Getting requirements to build wheel: finished with status 'done'
  Preparing metadata (pyproject.toml): started
  Preparing metadata (pyproject.toml): finished with status 'done'
Requirement already satisfied: pydantic>=2.7 in /usr/local/lib/python3.11/site-packages (from media-core==0.1.0) (2.12.5)
Collecting pyannote.audio>=3.1.1 (from media-core==0.1.0)
  Downloading pyannote_audio-4.0.4-py3-none-any.whl.metadata (13 kB)
Collecting asteroid-filterbanks>=0.4.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading asteroid_filterbanks-0.4.0-py3-none-any.whl.metadata (3.3 kB)
Collecting einops>=0.8.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading einops-0.8.2-py3-none-any.whl.metadata (13 kB)
Requirement already satisfied: huggingface-hub>=0.28.1 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.0)
Collecting lightning>=2.4 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading lightning-2.6.1-py3-none-any.whl.metadata (44 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 44.8/44.8 kB 996.5 kB/s eta 0:00:00
Collecting matplotlib>=3.10.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading matplotlib-3.10.8-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (52 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 52.8/52.8 kB 56.3 MB/s eta 0:00:00
Collecting opentelemetry-api>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_api-1.39.1-py3-none-any.whl.metadata (1.5 kB)
Collecting opentelemetry-exporter-otlp>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp-1.39.1-py3-none-any.whl.metadata (2.4 kB)
Collecting opentelemetry-sdk>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_sdk-1.39.1-py3-none-any.whl.metadata (1.5 kB)
Collecting pyannote-core>=6.0.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_core-6.0.1-py3-none-any.whl.metadata (1.9 kB)
Collecting pyannote-database>=6.1.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_database-6.1.1-py3-none-any.whl.metadata (30 kB)
Collecting pyannote-metrics>=4.0.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_metrics-4.0.0-py3-none-any.whl.metadata (2.2 kB)
Collecting pyannote-pipeline>=4.0.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_pipeline-4.0.0-py3-none-any.whl.metadata (5.4 kB)
Collecting pyannoteai-sdk>=0.3.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannoteai_sdk-0.4.0-py3-none-any.whl.metadata (2.4 kB)
Collecting pytorch-metric-learning>=2.8.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pytorch_metric_learning-2.9.0-py3-none-any.whl.metadata (18 kB)
Requirement already satisfied: rich>=13.9.4 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (14.3.3)
Collecting safetensors>=0.5.2 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (4.1 kB)
Collecting torch-audiomentations>=0.12.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torch_audiomentations-0.12.0-py3-none-any.whl.metadata (15 kB)
Requirement already satisfied: torch>=2.8.0 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (2.10.0)
Collecting torchaudio>=2.8.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchaudio-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (6.9 kB)
Collecting torchcodec>=0.7.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchcodec-0.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (11 kB)
Collecting torchmetrics>=1.6.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchmetrics-1.8.2-py3-none-any.whl.metadata (22 kB)
Requirement already satisfied: annotated-types>=0.6.0 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.7.0)
Requirement already satisfied: pydantic-core==2.41.5 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (2.41.5)
Requirement already satisfied: typing-extensions>=4.14.1 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (4.15.0)
Requirement already satisfied: typing-inspection>=0.4.2 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.4.2)
Requirement already satisfied: numpy in /usr/local/lib/python3.11/site-packages (from asteroid-filterbanks>=0.4.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.4.2)
Requirement already satisfied: filelock>=3.10.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (3.24.3)
Requirement already satisfied: fsspec>=2023.5.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (2026.2.0)
Requirement already satisfied: hf-xet<2.0.0,>=1.2.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.3.2)
Requirement already satisfied: httpx<1,>=0.23.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.28.1)
Requirement already satisfied: packaging>=20.9 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (26.0)
Requirement already satisfied: pyyaml>=5.1 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (6.0.3)
Requirement already satisfied: tqdm>=4.42.1 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (4.67.3)
Requirement already satisfied: typer in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.24.1)
Collecting lightning-utilities<2.0,>=0.10.0 (from lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading lightning_utilities-0.15.3-py3-none-any.whl.metadata (5.5 kB)
Collecting pytorch-lightning (from lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pytorch_lightning-2.6.1-py3-none-any.whl.metadata (21 kB)
Collecting contourpy>=1.0.1 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading contourpy-1.3.3-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (5.5 kB)
Collecting cycler>=0.10 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading cycler-0.12.1-py3-none-any.whl.metadata (3.8 kB)
Collecting fonttools>=4.22.0 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading fonttools-4.61.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (114 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 114.2/114.2 kB 2.6 MB/s eta 0:00:00
Collecting kiwisolver>=1.3.1 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading kiwisolver-1.4.9-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (6.3 kB)
Collecting pillow>=8 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pillow-12.1.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (8.8 kB)
Collecting pyparsing>=3 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyparsing-3.3.2-py3-none-any.whl.metadata (5.8 kB)
Requirement already satisfied: python-dateutil>=2.7 in /usr/local/lib/python3.11/site-packages (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.9.0.post0)
Collecting importlib-metadata<8.8.0,>=6.0 (from opentelemetry-api>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading importlib_metadata-8.7.1-py3-none-any.whl.metadata (4.7 kB)
Collecting opentelemetry-exporter-otlp-proto-grpc==1.39.1 (from opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_grpc-1.39.1-py3-none-any.whl.metadata (2.5 kB)
Collecting opentelemetry-exporter-otlp-proto-http==1.39.1 (from opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_http-1.39.1-py3-none-any.whl.metadata (2.4 kB)
Collecting googleapis-common-protos~=1.57 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading googleapis_common_protos-1.72.0-py3-none-any.whl.metadata (9.4 kB)
Collecting grpcio<2.0.0,>=1.63.2 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading grpcio-1.78.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (3.8 kB)
Collecting opentelemetry-exporter-otlp-proto-common==1.39.1 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_common-1.39.1-py3-none-any.whl.metadata (1.8 kB)
Collecting opentelemetry-proto==1.39.1 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_proto-1.39.1-py3-none-any.whl.metadata (2.3 kB)
Requirement already satisfied: requests~=2.7 in /usr/local/lib/python3.11/site-packages (from opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.32.5)
Collecting protobuf<7.0,>=5.0 (from opentelemetry-proto==1.39.1->opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading protobuf-6.33.5-cp39-abi3-manylinux2014_x86_64.whl.metadata (593 bytes)
Collecting opentelemetry-semantic-conventions==0.60b1 (from opentelemetry-sdk>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_semantic_conventions-0.60b1-py3-none-any.whl.metadata (2.4 kB)
Collecting pandas>=2.2.3 (from pyannote-core>=6.0.1->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pandas-3.0.1-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (79 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 79.5/79.5 kB 9.5 MB/s eta 0:00:00
Collecting sortedcontainers>=2.4.0 (from pyannote-core>=6.0.1->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading sortedcontainers-2.4.0-py2.py3-none-any.whl.metadata (10 kB)
Collecting scikit-learn>=1.6.1 (from pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading scikit_learn-1.8.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (11 kB)
Collecting scipy>=1.15.1 (from pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading scipy-1.17.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (62 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.1/62.1 kB 2.7 MB/s eta 0:00:00
Collecting optuna>=4.2.0 (from pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading optuna-4.7.0-py3-none-any.whl.metadata (17 kB)
Requirement already satisfied: markdown-it-py>=2.2.0 in /usr/local/lib/python3.11/site-packages (from rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (4.0.0)
Requirement already satisfied: pygments<3.0.0,>=2.13.0 in /usr/local/lib/python3.11/site-packages (from rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (2.19.2)
Requirement already satisfied: sympy>=1.13.3 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.14.0)
Requirement already satisfied: networkx>=2.5.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.6.1)
Requirement already satisfied: jinja2 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.1.6)
Requirement already satisfied: cuda-bindings==12.9.4 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.9.4)
Requirement already satisfied: nvidia-cuda-nvrtc-cu12==12.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.93)
Requirement already satisfied: nvidia-cuda-runtime-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-cuda-cupti-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-cudnn-cu12==9.10.2.21 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (9.10.2.21)
Requirement already satisfied: nvidia-cublas-cu12==12.8.4.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.4.1)
Requirement already satisfied: nvidia-cufft-cu12==11.3.3.83 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (11.3.3.83)
Requirement already satisfied: nvidia-curand-cu12==10.3.9.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (10.3.9.90)
Requirement already satisfied: nvidia-cusolver-cu12==11.7.3.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (11.7.3.90)
Requirement already satisfied: nvidia-cusparse-cu12==12.5.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.5.8.93)
Requirement already satisfied: nvidia-cusparselt-cu12==0.7.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (0.7.1)
Requirement already satisfied: nvidia-nccl-cu12==2.27.5 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.27.5)
Requirement already satisfied: nvidia-nvshmem-cu12==3.4.5 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.4.5)
Requirement already satisfied: nvidia-nvtx-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-nvjitlink-cu12==12.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.93)
Requirement already satisfied: nvidia-cufile-cu12==1.13.1.3 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.13.1.3)
Requirement already satisfied: triton==3.6.0 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.6.0)
Requirement already satisfied: cuda-pathfinder~=1.1 in /usr/local/lib/python3.11/site-packages (from cuda-bindings==12.9.4->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.4.0)
Collecting julius<0.3,>=0.2.3 (from torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading julius-0.2.7.tar.gz (59 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 59.6/59.6 kB 7.1 MB/s eta 0:00:00
  Preparing metadata (setup.py): started
  Preparing metadata (setup.py): finished with status 'done'
Collecting torch-pitch-shift>=1.2.2 (from torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torch_pitch_shift-1.2.5-py3-none-any.whl.metadata (2.5 kB)
Collecting aiohttp!=4.0.0a0,!=4.0.0a1 (from fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiohttp-3.13.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (8.1 kB)
Requirement already satisfied: anyio in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (4.12.1)
Requirement already satisfied: certifi in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (2026.2.25)
Requirement already satisfied: httpcore==1.* in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.0.9)
Requirement already satisfied: idna in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (3.11)
Requirement already satisfied: h11>=0.16 in /usr/local/lib/python3.11/site-packages (from httpcore==1.*->httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.16.0)
Collecting zipp>=3.20 (from importlib-metadata<8.8.0,>=6.0->opentelemetry-api>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading zipp-3.23.0-py3-none-any.whl.metadata (3.6 kB)
Requirement already satisfied: mdurl~=0.1 in /usr/local/lib/python3.11/site-packages (from markdown-it-py>=2.2.0->rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (0.1.2)
Collecting alembic>=1.5.0 (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading alembic-1.18.4-py3-none-any.whl.metadata (7.2 kB)
Collecting colorlog (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading colorlog-6.10.1-py3-none-any.whl.metadata (11 kB)
Requirement already satisfied: sqlalchemy>=1.4.2 in /usr/local/lib/python3.11/site-packages (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.0.47)
Requirement already satisfied: six>=1.5 in /usr/local/lib/python3.11/site-packages (from python-dateutil>=2.7->matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.17.0)
Requirement already satisfied: charset_normalizer<4,>=2 in /usr/local/lib/python3.11/site-packages (from requests~=2.7->opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.4.4)
Requirement already satisfied: urllib3<3,>=1.21.1 in /usr/local/lib/python3.11/site-packages (from requests~=2.7->opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.6.3)
Requirement already satisfied: joblib>=1.3.0 in /usr/local/lib/python3.11/site-packages (from scikit-learn>=1.6.1->pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.3)
Collecting threadpoolctl>=3.2.0 (from scikit-learn>=1.6.1->pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading threadpoolctl-3.6.0-py3-none-any.whl.metadata (13 kB)
Requirement already satisfied: mpmath<1.4,>=1.1.0 in /usr/local/lib/python3.11/site-packages (from sympy>=1.13.3->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.3.0)
Collecting primePy>=1.3 (from torch-pitch-shift>=1.2.2->torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading primePy-1.3-py3-none-any.whl.metadata (4.8 kB)
Requirement already satisfied: MarkupSafe>=2.0 in /usr/local/lib/python3.11/site-packages (from jinja2->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.0.3)
Requirement already satisfied: click>=8.2.1 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (8.3.1)
Requirement already satisfied: shellingham>=1.3.0 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.4)
Requirement already satisfied: annotated-doc>=0.0.2 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.0.4)
Collecting aiohappyeyeballs>=2.5.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiohappyeyeballs-2.6.1-py3-none-any.whl.metadata (5.9 kB)
Collecting aiosignal>=1.4.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiosignal-1.4.0-py3-none-any.whl.metadata (3.7 kB)
Collecting attrs>=17.3.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading attrs-25.4.0-py3-none-any.whl.metadata (10 kB)
Collecting frozenlist>=1.1.1 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading frozenlist-1.8.0-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (20 kB)
Collecting multidict<7.0,>=4.5 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading multidict-6.7.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (5.3 kB)
Collecting propcache>=0.2.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading propcache-0.4.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (13 kB)
Collecting yarl<2.0,>=1.17.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading yarl-1.22.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (75 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 75.1/75.1 kB 13.5 MB/s eta 0:00:00
Collecting Mako (from alembic>=1.5.0->optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading mako-1.3.10-py3-none-any.whl.metadata (2.9 kB)
Requirement already satisfied: greenlet>=1 in /usr/local/lib/python3.11/site-packages (from sqlalchemy>=1.4.2->optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.3.2)
Downloading pyannote_audio-4.0.4-py3-none-any.whl (893 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 893.7/893.7 kB 4.8 MB/s eta 0:00:00
Downloading asteroid_filterbanks-0.4.0-py3-none-any.whl (29 kB)
Downloading einops-0.8.2-py3-none-any.whl (65 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 65.6/65.6 kB 9.5 MB/s eta 0:00:00
Downloading lightning-2.6.1-py3-none-any.whl (853 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 853.6/853.6 kB 6.0 MB/s eta 0:00:00
Downloading matplotlib-3.10.8-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (8.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 8.7/8.7 MB 8.5 MB/s eta 0:00:00
Downloading opentelemetry_api-1.39.1-py3-none-any.whl (66 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 66.4/66.4 kB 15.0 MB/s eta 0:00:00
Downloading opentelemetry_exporter_otlp-1.39.1-py3-none-any.whl (7.0 kB)
Downloading opentelemetry_exporter_otlp_proto_grpc-1.39.1-py3-none-any.whl (19 kB)
Downloading opentelemetry_exporter_otlp_proto_http-1.39.1-py3-none-any.whl (19 kB)
Downloading opentelemetry_exporter_otlp_proto_common-1.39.1-py3-none-any.whl (18 kB)
Downloading opentelemetry_proto-1.39.1-py3-none-any.whl (72 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 72.5/72.5 kB 12.7 MB/s eta 0:00:00
Downloading opentelemetry_sdk-1.39.1-py3-none-any.whl (132 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 132.6/132.6 kB 12.4 MB/s eta 0:00:00
Downloading opentelemetry_semantic_conventions-0.60b1-py3-none-any.whl (219 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 220.0/220.0 kB 17.1 MB/s eta 0:00:00
Downloading pyannote_core-6.0.1-py3-none-any.whl (57 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 57.5/57.5 kB 16.5 MB/s eta 0:00:00
Downloading pyannote_database-6.1.1-py3-none-any.whl (53 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 53.7/53.7 kB 19.3 MB/s eta 0:00:00
Downloading pyannote_metrics-4.0.0-py3-none-any.whl (49 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 49.7/49.7 kB 21.6 MB/s eta 0:00:00
Downloading pyannote_pipeline-4.0.0-py3-none-any.whl (22 kB)
Downloading pyannoteai_sdk-0.4.0-py3-none-any.whl (8.9 kB)
Downloading pytorch_metric_learning-2.9.0-py3-none-any.whl (127 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 127.8/127.8 kB 4.8 MB/s eta 0:00:00
Downloading safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (507 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 507.2/507.2 kB 9.7 MB/s eta 0:00:00
Downloading torch_audiomentations-0.12.0-py3-none-any.whl (48 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 48.5/48.5 kB 16.1 MB/s eta 0:00:00
Downloading torchaudio-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (1.9 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.9/1.9 MB 9.0 MB/s eta 0:00:00
Downloading torchcodec-0.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (2.1 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.1/2.1 MB 9.5 MB/s eta 0:00:00
Downloading torchmetrics-1.8.2-py3-none-any.whl (983 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 983.2/983.2 kB 10.4 MB/s eta 0:00:00
Downloading contourpy-1.3.3-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (355 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 355.2/355.2 kB 12.3 MB/s eta 0:00:00
Downloading cycler-0.12.1-py3-none-any.whl (8.3 kB)
Downloading fonttools-4.61.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (5.0 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 5.0/5.0 MB 9.3 MB/s eta 0:00:00
Downloading importlib_metadata-8.7.1-py3-none-any.whl (27 kB)
Downloading kiwisolver-1.4.9-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.4 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.4/1.4 MB 7.6 MB/s eta 0:00:00
Downloading lightning_utilities-0.15.3-py3-none-any.whl (31 kB)
Downloading optuna-4.7.0-py3-none-any.whl (413 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 413.9/413.9 kB 2.6 MB/s eta 0:00:00
Downloading pandas-3.0.1-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (11.3 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 11.3/11.3 MB 5.7 MB/s eta 0:00:00
Downloading pillow-12.1.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (7.0 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 7.0/7.0 MB 7.1 MB/s eta 0:00:00
Downloading pyparsing-3.3.2-py3-none-any.whl (122 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 122.8/122.8 kB 18.0 MB/s eta 0:00:00
Downloading scikit_learn-1.8.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (9.1 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 9.1/9.1 MB 7.1 MB/s eta 0:00:00
Downloading scipy-1.17.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (35.3 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 35.3/35.3 MB 7.5 MB/s eta 0:00:00
Downloading sortedcontainers-2.4.0-py2.py3-none-any.whl (29 kB)
Downloading torch_pitch_shift-1.2.5-py3-none-any.whl (5.0 kB)
Downloading pytorch_lightning-2.6.1-py3-none-any.whl (857 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 857.3/857.3 kB 8.4 MB/s eta 0:00:00
Downloading aiohttp-3.13.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (1.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.7/1.7 MB 8.7 MB/s eta 0:00:00
Downloading alembic-1.18.4-py3-none-any.whl (263 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 263.9/263.9 kB 12.9 MB/s eta 0:00:00
Downloading googleapis_common_protos-1.72.0-py3-none-any.whl (297 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 297.5/297.5 kB 4.6 MB/s eta 0:00:00
Downloading grpcio-1.78.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (6.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.7/6.7 MB 8.1 MB/s eta 0:00:00
Downloading primePy-1.3-py3-none-any.whl (4.0 kB)
Downloading threadpoolctl-3.6.0-py3-none-any.whl (18 kB)
Downloading zipp-3.23.0-py3-none-any.whl (10 kB)
Downloading colorlog-6.10.1-py3-none-any.whl (11 kB)
Downloading aiohappyeyeballs-2.6.1-py3-none-any.whl (15 kB)
Downloading aiosignal-1.4.0-py3-none-any.whl (7.5 kB)
Downloading attrs-25.4.0-py3-none-any.whl (67 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67.6/67.6 kB 18.7 MB/s eta 0:00:00
Downloading frozenlist-1.8.0-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (231 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 231.1/231.1 kB 11.7 MB/s eta 0:00:00
Downloading multidict-6.7.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (246 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 246.3/246.3 kB 12.8 MB/s eta 0:00:00
Downloading propcache-0.4.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (210 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 210.0/210.0 kB 13.2 MB/s eta 0:00:00
Downloading protobuf-6.33.5-cp39-abi3-manylinux2014_x86_64.whl (323 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 323.5/323.5 kB 12.2 MB/s eta 0:00:00
Downloading yarl-1.22.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (365 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 365.8/365.8 kB 7.5 MB/s eta 0:00:00
Downloading mako-1.3.10-py3-none-any.whl (78 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.5/78.5 kB 19.8 MB/s eta 0:00:00
Building wheels for collected packages: media-core, julius
  Building wheel for media-core (pyproject.toml): started
  Building wheel for media-core (pyproject.toml): finished with status 'done'
  Created wheel for media-core: filename=media_core-0.1.0-py3-none-any.whl size=32578 sha256=28efbac118269638e75137ab3bac66dafafac2366c1512d287c1483c3186d8fd
  Stored in directory: /tmp/pip-ephem-wheel-cache-is5hn63w/wheels/b3/1b/bb/820896c27a04aa0a1c42405a1e408db8e7a4c37ac4ee5b822f
  Building wheel for julius (setup.py): started
  Building wheel for julius (setup.py): finished with status 'done'
  Created wheel for julius: filename=julius-0.2.7-py3-none-any.whl size=21966 sha256=0801dfd53ae4aa75e4c03e8a98667ac8f435760011a14d9d6bc096db4a845b7a
  Stored in directory: /tmp/pip-ephem-wheel-cache-is5hn63w/wheels/16/15/d4/edd724cefe78050a6ba3344b8b0c6672db829a799dbb9f81ff
Successfully built media-core julius
Installing collected packages: sortedcontainers, primePy, zipp, torchcodec, threadpoolctl, scipy, safetensors, pyparsing, protobuf, propcache, pillow, multidict, Mako, lightning-utilities, kiwisolver, grpcio, frozenlist, fonttools, einops, cycler, contourpy, colorlog, attrs, aiohappyeyeballs, yarl, scikit-learn, pyannoteai-sdk, pandas, opentelemetry-proto, matplotlib, importlib-metadata, googleapis-common-protos, alembic, aiosignal, pyannote-core, optuna, opentelemetry-exporter-otlp-proto-common, opentelemetry-api, media-core, aiohttp, torchmetrics, torchaudio, pytorch-metric-learning, pyannote-database, opentelemetry-semantic-conventions, julius, asteroid-filterbanks, torch-pitch-shift, pytorch-lightning, pyannote-pipeline, pyannote-metrics, opentelemetry-sdk, torch-audiomentations, opentelemetry-exporter-otlp-proto-http, opentelemetry-exporter-otlp-proto-grpc, lightning, opentelemetry-exporter-otlp, pyannote.audio
  Attempting uninstall: protobuf
    Found existing installation: protobuf 7.34.0
    Uninstalling protobuf-7.34.0:
      Successfully uninstalled protobuf-7.34.0
  Attempting uninstall: media-core
    Found existing installation: media-core 0.1.0
    Uninstalling media-core-0.1.0:
      Successfully uninstalled media-core-0.1.0
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv
Successfully installed Mako-1.3.10 aiohappyeyeballs-2.6.1 aiohttp-3.13.3 aiosignal-1.4.0 alembic-1.18.4 asteroid-filterbanks-0.4.0 attrs-25.4.0 colorlog-6.10.1 contourpy-1.3.3 cycler-0.12.1 einops-0.8.2 fonttools-4.61.1 frozenlist-1.8.0 googleapis-common-protos-1.72.0 grpcio-1.78.0 importlib-metadata-8.7.1 julius-0.2.7 kiwisolver-1.4.9 lightning-2.6.1 lightning-utilities-0.15.3 matplotlib-3.10.8 media-core-0.1.0 multidict-6.7.1 opentelemetry-api-1.39.1 opentelemetry-exporter-otlp-1.39.1 opentelemetry-exporter-otlp-proto-common-1.39.1 opentelemetry-exporter-otlp-proto-grpc-1.39.1 opentelemetry-exporter-otlp-proto-http-1.39.1 opentelemetry-proto-1.39.1 opentelemetry-sdk-1.39.1 opentelemetry-semantic-conventions-0.60b1 optuna-4.7.0 pandas-3.0.1 pillow-12.1.1 primePy-1.3 propcache-0.4.1 protobuf-6.33.5 pyannote-core-6.0.1 pyannote-database-6.1.1 pyannote-metrics-4.0.0 pyannote-pipeline-4.0.0 pyannote.audio-4.0.4 pyannoteai-sdk-0.4.0 pyparsing-3.3.2 pytorch-lightning-2.6.1 pytorch-metric-learning-2.9.0 safetensors-0.7.0 scikit-learn-1.8.0 scipy-1.17.1 sortedcontainers-2.4.0 threadpoolctl-3.6.0 torch-audiomentations-0.12.0 torch-pitch-shift-1.2.5 torchaudio-2.10.0 torchcodec-0.10.0 torchmetrics-1.8.2 yarl-1.22.0 zipp-3.23.0

[notice] A new release of pip is available: 24.0 -> 26.0.1
[notice] To update, run: pip install --upgrade pip
Warmup run (not timed)...

### Diarization benchmark

- backend: `pyannote`
- model: `pyannote/speaker-diarization-3.1`
- runs: `1` (warmup: `True`)
- duration_s_avg: `1.391` (min `1.391`, max `1.391`)
- segments_last_run: `0`
- peak_rss_mb: `1049.7`

```text
run=1 duration_s=1.391 segments=0
```
