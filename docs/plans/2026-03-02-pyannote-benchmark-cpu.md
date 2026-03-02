Running in Docker worker:
  input:   /tmp/reframe-worktrees/next-big-phase-2026-03-01/samples/sample.wav
  backend: pyannote
  extra:   diarize-pyannote

time="2026-03-01T03:58:53+02:00" level=warning msg="/tmp/reframe-worktrees/next-big-phase-2026-03-01/infra/docker-compose.yml: the attribute `version` is obsolete, it will be ignored, please remove it to avoid potential confusion"
time="2026-03-01T03:58:53+02:00" level=warning msg="Found orphan containers ([infra-db-1]) for this project. If you removed or renamed this service in your compose file, you can run this command with the --remove-orphans flag to clean it up."
 Container infra-redis-1 Running 
 Image infra-worker Building 
#1 [internal] load local bake definitions
#1 reading from stdin 551B done
#1 DONE 0.0s

#2 [internal] load build definition from Dockerfile.worker
#2 transferring dockerfile: 686B done
#2 DONE 0.0s

#3 [internal] load metadata for docker.io/library/python:3.11-slim
#3 ...

#4 [auth] library/python:pull token for registry-1.docker.io
#4 DONE 0.0s

#3 [internal] load metadata for docker.io/library/python:3.11-slim
#3 DONE 0.9s

#5 [internal] load .dockerignore
#5 transferring context: 2B done
#5 DONE 0.0s

#6 [ 1/10] FROM docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39
#6 resolve docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39 0.0s done
#6 DONE 0.0s

#7 [internal] load build context
#7 transferring context: 50.55kB 0.0s done
#7 DONE 0.0s

#8 [ 5/10] RUN pip install --no-cache-dir -r requirements.txt
#8 CACHED

#9 [ 3/10] RUN apt-get update     && apt-get install -y --no-install-recommends ffmpeg     && rm -rf /var/lib/apt/lists/*
#9 CACHED

#10 [ 4/10] COPY services/worker/requirements.txt ./requirements.txt
#10 CACHED

#11 [ 2/10] WORKDIR /worker
#11 CACHED

#12 [ 6/10] COPY packages/media-core /worker/packages/media-core
#12 CACHED

#13 [ 7/10] RUN pip install --no-cache-dir '/worker/packages/media-core[transcribe-faster-whisper,translate-local]'
#13 1.049 Processing ./packages/media-core
#13 1.051   Installing build dependencies: started
#13 3.943   Installing build dependencies: finished with status 'done'
#13 3.944   Getting requirements to build wheel: started
#13 4.326   Getting requirements to build wheel: finished with status 'done'
#13 4.327   Preparing metadata (pyproject.toml): started
#13 4.706   Preparing metadata (pyproject.toml): finished with status 'done'
#13 4.715 Requirement already satisfied: pydantic>=2.7 in /usr/local/lib/python3.11/site-packages (from media-core==0.1.0) (2.12.5)
#13 4.832 Collecting faster-whisper>=1.0.0 (from media-core==0.1.0)
#13 4.939   Downloading faster_whisper-1.2.1-py3-none-any.whl.metadata (16 kB)
#13 4.987 Collecting argostranslate>=1.9.0 (from media-core==0.1.0)
#13 5.018   Downloading argostranslate-1.11.0-py3-none-any.whl.metadata (9.7 kB)
#13 5.172 Collecting ctranslate2<5,>=4.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.207   Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 5.340 Collecting minisbd (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.372   Downloading minisbd-0.9.3-py3-none-any.whl.metadata (47 kB)
#13 5.403      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 47.2/47.2 kB 1.4 MB/s eta 0:00:00
#13 5.414 Requirement already satisfied: packaging in /usr/local/lib/python3.11/site-packages (from argostranslate>=1.9.0->media-core==0.1.0) (26.0)
#13 5.457 Collecting sacremoses<0.2,>=0.0.53 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.492   Downloading sacremoses-0.1.1-py3-none-any.whl.metadata (8.3 kB)
#13 5.593 Collecting sentencepiece<0.3,>=0.2.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.644   Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 6.013 Collecting spacy (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.055   Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (27 kB)
#13 6.225 Collecting stanza==1.10.1 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 6.266   Downloading stanza-1.10.1-py3-none-any.whl.metadata (13 kB)
#13 6.351 Collecting emoji (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 6.393   Downloading emoji-2.15.0-py3-none-any.whl.metadata (5.7 kB)
#13 6.788 Collecting numpy (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 6.939   Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (6.6 kB)
#13 8.509 Collecting protobuf>=3.15.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.787   Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl.metadata (595 bytes)
#13 9.134 Collecting requests (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.230   Downloading requests-2.32.5-py3-none-any.whl.metadata (4.9 kB)
#13 9.424 Collecting networkx (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.565   Downloading networkx-3.6.1-py3-none-any.whl.metadata (6.8 kB)
#13 9.694 Collecting torch>=1.3.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.726   Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (31 kB)
#13 9.805 Collecting tqdm (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.837   Downloading tqdm-4.67.3-py3-none-any.whl.metadata (57 kB)
#13 9.848      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 57.7/57.7 kB 5.5 MB/s eta 0:00:00
#13 9.938 Collecting huggingface-hub>=0.21 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.968   Downloading huggingface_hub-1.5.0-py3-none-any.whl.metadata (13 kB)
#13 10.14 Collecting tokenizers<1,>=0.13 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.17   Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (7.3 kB)
#13 10.24 Collecting onnxruntime<2,>=1.14 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.28   Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (5.0 kB)
#13 10.34 Collecting av>=11 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.37   Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (4.6 kB)
#13 10.38 Requirement already satisfied: annotated-types>=0.6.0 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.7.0)
#13 10.38 Requirement already satisfied: pydantic-core==2.41.5 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (2.41.5)
#13 10.38 Requirement already satisfied: typing-extensions>=4.14.1 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (4.15.0)
#13 10.38 Requirement already satisfied: typing-inspection>=0.4.2 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.4.2)
#13 10.39 Requirement already satisfied: setuptools in /usr/local/lib/python3.11/site-packages (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0) (79.0.1)
#13 10.44 Collecting pyyaml<7,>=5.3 (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.48   Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.4 kB)
#13 10.60 Collecting filelock>=3.10.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.63   Downloading filelock-3.24.3-py3-none-any.whl.metadata (2.0 kB)
#13 10.68 Collecting fsspec>=2023.5.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.71   Downloading fsspec-2026.2.0-py3-none-any.whl.metadata (10 kB)
#13 10.78 Collecting hf-xet<2.0.0,>=1.2.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.82   Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (4.9 kB)
#13 10.86 Collecting httpx<1,>=0.23.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.89   Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
#13 10.94 Collecting typer (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.97   Downloading typer-0.24.1-py3-none-any.whl.metadata (16 kB)
#13 11.01 Collecting flatbuffers (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 11.04   Downloading flatbuffers-25.12.19-py2.py3-none-any.whl.metadata (1.0 kB)
#13 11.09 Collecting sympy (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 11.12   Downloading sympy-1.14.0-py3-none-any.whl.metadata (12 kB)
#13 11.58 Collecting regex (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.61   Downloading regex-2026.2.28-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (40 kB)
#13 11.61      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.4/40.4 kB 10.8 MB/s eta 0:00:00
#13 11.62 Requirement already satisfied: click in /usr/local/lib/python3.11/site-packages (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0) (8.3.1)
#13 11.66 Collecting joblib (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.69   Downloading joblib-1.5.3-py3-none-any.whl.metadata (5.5 kB)
#13 11.80 Collecting spacy-legacy<3.1.0,>=3.0.11 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.83   Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl.metadata (2.8 kB)
#13 11.87 Collecting spacy-loggers<2.0.0,>=1.0.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.90   Downloading spacy_loggers-1.0.5-py3-none-any.whl.metadata (23 kB)
#13 11.95 Collecting murmurhash<1.1.0,>=0.28.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 11.99   Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.3 kB)
#13 12.04 Collecting cymem<2.1.0,>=2.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.07   Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (9.7 kB)
#13 12.22 Collecting preshed<3.1.0,>=3.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.25   Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.5 kB)
#13 12.40 Collecting thinc<8.4.0,>=8.3.4 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.43   Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (15 kB)
#13 12.48 Collecting wasabi<1.2.0,>=0.9.1 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.51   Downloading wasabi-1.1.3-py3-none-any.whl.metadata (28 kB)
#13 12.57 Collecting srsly<3.0.0,>=2.4.3 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.61   Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (19 kB)
#13 12.65 Collecting catalogue<2.1.0,>=2.0.6 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.68   Downloading catalogue-2.0.10-py3-none-any.whl.metadata (14 kB)
#13 12.72 Collecting weasel<0.5.0,>=0.4.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.75   Downloading weasel-0.4.3-py3-none-any.whl.metadata (4.6 kB)
#13 12.84 Collecting typer-slim<1.0.0,>=0.3.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.87   Downloading typer_slim-0.24.0-py3-none-any.whl.metadata (4.2 kB)
#13 12.93 Collecting jinja2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 12.96   Downloading jinja2-3.1.6-py3-none-any.whl.metadata (2.9 kB)
#13 13.05 Collecting anyio (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 13.09   Downloading anyio-4.12.1-py3-none-any.whl.metadata (4.3 kB)
#13 13.13 Collecting certifi (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 13.16   Downloading certifi-2026.2.25-py3-none-any.whl.metadata (2.5 kB)
#13 13.20 Collecting httpcore==1.* (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 13.23   Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
#13 13.27 Collecting idna (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 13.30   Downloading idna-3.11-py3-none-any.whl.metadata (8.4 kB)
#13 13.34 Collecting h11>=0.16 (from httpcore==1.*->httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 13.37   Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
#13 13.49 Collecting charset_normalizer<4,>=2 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.52   Downloading charset_normalizer-3.4.4-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (37 kB)
#13 13.59 Collecting urllib3<3,>=1.21.1 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.62   Downloading urllib3-2.6.3-py3-none-any.whl.metadata (6.9 kB)
#13 13.73 Collecting blis<1.4.0,>=1.3.0 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.76   Downloading blis-1.3.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (7.5 kB)
#13 13.80 Collecting confection<1.0.0,>=0.0.1 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 13.84   Downloading confection-0.1.5-py3-none-any.whl.metadata (19 kB)
#13 13.92 Collecting cuda-bindings==12.9.4 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.15   Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (2.6 kB)
#13 14.59 Collecting nvidia-cuda-nvrtc-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.63   Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 14.66 Collecting nvidia-cuda-runtime-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.69   Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 14.73 Collecting nvidia-cuda-cupti-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.76   Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 14.80 Collecting nvidia-cudnn-cu12==9.10.2.21 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.83   Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 14.87 Collecting nvidia-cublas-cu12==12.8.4.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.90   Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 14.94 Collecting nvidia-cufft-cu12==11.3.3.83 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 14.97   Downloading nvidia_cufft_cu12-11.3.3.83-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 15.00 Collecting nvidia-curand-cu12==10.3.9.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.03   Downloading nvidia_curand_cu12-10.3.9.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 15.07 Collecting nvidia-cusolver-cu12==11.7.3.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.10   Downloading nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 15.14 Collecting nvidia-cusparse-cu12==12.5.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.18   Downloading nvidia_cusparse_cu12-12.5.8.93-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 15.23 Collecting nvidia-cusparselt-cu12==0.7.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.26   Downloading nvidia_cusparselt_cu12-0.7.1-py3-none-manylinux2014_x86_64.whl.metadata (7.0 kB)
#13 15.30 Collecting nvidia-nccl-cu12==2.27.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.33   Downloading nvidia_nccl_cu12-2.27.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.0 kB)
#13 15.36 Collecting nvidia-nvshmem-cu12==3.4.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.40   Downloading nvidia_nvshmem_cu12-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.1 kB)
#13 15.54 Collecting nvidia-nvtx-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.58   Downloading nvidia_nvtx_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 15.72 Collecting nvidia-nvjitlink-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.76   Downloading nvidia_nvjitlink_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 15.80 Collecting nvidia-cufile-cu12==1.13.1.3 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.83   Downloading nvidia_cufile_cu12-1.13.1.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 15.88 Collecting triton==3.6.0 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 15.92   Downloading triton-3.6.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (1.7 kB)
#13 15.97 Collecting cuda-pathfinder~=1.1 (from cuda-bindings==12.9.4->torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 16.00   Downloading cuda_pathfinder-1.4.0-py3-none-any.whl.metadata (1.9 kB)
#13 16.15 Collecting mpmath<1.4,>=1.1.0 (from sympy->onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 16.18   Downloading mpmath-1.3.0-py3-none-any.whl.metadata (8.6 kB)
#13 16.25 Collecting shellingham>=1.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 16.30   Downloading shellingham-1.5.4-py2.py3-none-any.whl.metadata (3.5 kB)
#13 16.40 Collecting rich>=12.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 16.44   Downloading rich-14.3.3-py3-none-any.whl.metadata (18 kB)
#13 16.50 Collecting annotated-doc>=0.0.2 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 16.54   Downloading annotated_doc-0.0.4-py3-none-any.whl.metadata (6.6 kB)
#13 16.61 Collecting cloudpathlib<1.0.0,>=0.7.0 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 16.65   Downloading cloudpathlib-0.23.0-py3-none-any.whl.metadata (16 kB)
#13 16.70 Collecting smart-open<8.0.0,>=5.2.1 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 16.73   Downloading smart_open-7.5.1-py3-none-any.whl.metadata (24 kB)
#13 16.82 Collecting MarkupSafe>=2.0 (from jinja2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 16.86   Downloading markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.7 kB)
#13 17.00 Collecting markdown-it-py>=2.2.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 17.04   Downloading markdown_it_py-4.0.0-py3-none-any.whl.metadata (7.3 kB)
#13 17.08 Collecting pygments<3.0.0,>=2.13.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 17.11   Downloading pygments-2.19.2-py3-none-any.whl.metadata (2.5 kB)
#13 17.38 Collecting wrapt (from smart-open<8.0.0,>=5.2.1->weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 17.41   Downloading wrapt-2.1.1-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (7.4 kB)
#13 17.50 Collecting mdurl~=0.1 (from markdown-it-py>=2.2.0->rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 17.53   Downloading mdurl-0.1.2-py3-none-any.whl.metadata (1.6 kB)
#13 17.61 Downloading argostranslate-1.11.0-py3-none-any.whl (41 kB)
#13 17.61    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 41.6/41.6 kB 23.5 MB/s eta 0:00:00
#13 17.64 Downloading stanza-1.10.1-py3-none-any.whl (1.1 MB)
#13 17.82    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 6.1 MB/s eta 0:00:00
#13 17.86 Downloading faster_whisper-1.2.1-py3-none-any.whl (1.1 MB)
#13 17.99    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 8.7 MB/s eta 0:00:00
#13 18.02 Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl (40.8 MB)
#13 23.49    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.8/40.8 MB 5.3 MB/s eta 0:00:00
#13 23.52 Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (38.8 MB)
#13 32.85    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 38.8/38.8 MB 6.4 MB/s eta 0:00:00
#13 32.88 Downloading huggingface_hub-1.5.0-py3-none-any.whl (596 kB)
#13 32.96    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 596.3/596.3 kB 7.8 MB/s eta 0:00:00
#13 32.99 Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (17.1 MB)
#13 36.19    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 17.1/17.1 MB 4.6 MB/s eta 0:00:00
#13 36.22 Downloading sacremoses-0.1.1-py3-none-any.whl (897 kB)
#13 36.37    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 897.5/897.5 kB 6.2 MB/s eta 0:00:00
#13 36.40 Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (1.4 MB)
#13 36.62    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.4/1.4 MB 6.3 MB/s eta 0:00:00
#13 36.65 Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (3.3 MB)
#13 37.16    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.3/3.3 MB 6.5 MB/s eta 0:00:00
#13 37.19 Downloading tqdm-4.67.3-py3-none-any.whl (78 kB)
#13 37.20    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.4/78.4 kB 12.3 MB/s eta 0:00:00
#13 37.23 Downloading minisbd-0.9.3-py3-none-any.whl (40 kB)
#13 37.24    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.9/40.9 kB 21.3 MB/s eta 0:00:00
#13 37.27 Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (32.3 MB)
#13 42.17    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 32.3/32.3 MB 5.8 MB/s eta 0:00:00
#13 42.20 Downloading catalogue-2.0.10-py3-none-any.whl (17 kB)
#13 42.24 Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (244 kB)
#13 42.28    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 244.5/244.5 kB 6.2 MB/s eta 0:00:00
#13 42.31 Downloading filelock-3.24.3-py3-none-any.whl (24 kB)
#13 42.35 Downloading fsspec-2026.2.0-py3-none-any.whl (202 kB)
#13 42.36    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 202.5/202.5 kB 12.3 MB/s eta 0:00:00
#13 42.40 Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.2 MB)
#13 42.98    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.2/4.2 MB 7.2 MB/s eta 0:00:00
#13 43.01 Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
#13 43.01    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 73.5/73.5 kB 14.9 MB/s eta 0:00:00
#13 43.05 Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
#13 43.05    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.8/78.8 kB 11.3 MB/s eta 0:00:00
#13 43.09 Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (128 kB)
#13 43.10    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 128.4/128.4 kB 11.9 MB/s eta 0:00:00
#13 43.13 Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (16.9 MB)
#13 46.36    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 16.9/16.9 MB 6.2 MB/s eta 0:00:00
#13 46.40 Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (824 kB)
#13 46.58    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 824.7/824.7 kB 4.7 MB/s eta 0:00:00
#13 46.62 Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl (324 kB)
#13 46.73    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 324.3/324.3 kB 2.7 MB/s eta 0:00:00
#13 46.78 Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (806 kB)
#13 46.90    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 806.6/806.6 kB 7.6 MB/s eta 0:00:00
#13 46.93 Downloading requests-2.32.5-py3-none-any.whl (64 kB)
#13 46.94    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64.7/64.7 kB 25.2 MB/s eta 0:00:00
#13 46.97 Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl (29 kB)
#13 47.01 Downloading spacy_loggers-1.0.5-py3-none-any.whl (22 kB)
#13 47.04 Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.1 MB)
#13 47.17    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 8.7 MB/s eta 0:00:00
#13 47.21 Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.1 MB)
#13 47.73    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.1/4.1 MB 7.9 MB/s eta 0:00:00
#13 47.76 Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (915.6 MB)
#13 181.5    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 915.6/915.6 MB 9.8 MB/s eta 0:00:00
#13 181.5 Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (12.2 MB)
#13 183.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 12.2/12.2 MB 9.6 MB/s eta 0:00:00
#13 183.1 Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl (594.3 MB)
#13 270.6    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 594.3/594.3 MB 7.1 MB/s eta 0:00:00
#13 270.7 Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (10.2 MB)
#13 272.0    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.2/10.2 MB 7.8 MB/s eta 0:00:00
#13 272.0 Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl (88.0 MB)
#13 284.3    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 88.0/88.0 MB 7.6 MB/s eta 0:00:00
#13 284.3 Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (954 kB)
#13 284.4    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 954.8/954.8 kB 8.4 MB/s eta 0:00:00
#13 284.5 Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl (706.8 MB)

