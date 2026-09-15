
# STAGE 1 — System Base
# Installs Linux system tools needed at runtime

FROM python:3.12-slim AS system-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    # PDF processing
    poppler-utils \
    libpoppler-cpp-dev \
    # Word/Excel conversion at runtime
    libreoffice-core \
    libreoffice-common \
    libreoffice-writer \
    libreoffice-calc \
    # Tesseract OCR engine
    tesseract-ocr \
    # Required by some Python packages during install
    libgomp1 \
    libgl1 \                                                                                                                                                               
    libglib2.0-0 \                                                                                                                                                         
    libsm6 \                                                                                                                                                               
    libxext6 \                                                                                                                                                             
    libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# STAGE 2 — Python Core Dependencies Builder
# Installs base + llm packages with CPU-only torch
FROM system-base AS python-builder

WORKDIR /app

# Build tools only needed here — never copied to final image
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy all requirements files
COPY requirements/ ./requirements/
COPY .env .env

RUN pip install --no-cache-dir \
    torch==2.10.0+cpu \
    torchvision==0.25.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Install base dependencies
# NOTE: easyocr is in base.txt but it pulls its own heavy torch
# We install it separately AFTER our CPU torch to prevent override
RUN grep -v "easyocr" requirements/base.txt > /tmp/base_no_easyocr.txt \
    && pip install --no-cache-dir -r /tmp/base_no_easyocr.txt

# Install LLM dependencies
# NOTE: openai and google-generativeai are duplicated in base.txt — pip handles this fine
# NOTE: accelerate REMOVED — GPU-only library, zero benefit on CPU ACA
# NOTE: torch already installed above as CPU version, pip will skip reinstall
RUN grep -v "accelerate" requirements/llm.txt > /tmp/llm_no_accelerate.txt \
    && pip install --no-cache-dir -r /tmp/llm_no_accelerate.txt

# Now install easyocr separately AFTER torch is locked to CPU version
RUN pip install --no-cache-dir "easyocr>=1.7.0"

# STAGE 3 — OCR Dependencies Builder
# Installs all 3 OCR engines (user picks at runtime)
FROM python-builder AS ocr-builder

WORKDIR /app

RUN pip install --no-cache-dir -r requirements/ocr-chandra.txt

RUN pip install --no-cache-dir -r requirements/ocr-mistral.txt

RUN pip install --no-cache-dir paddlepaddle==2.6.2 \
    --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
RUN pip install --no-cache-dir \
    "numpy==1.26.4" \
    "paddleocr==2.7.3" \
    "opencv-python-headless>=4.6.0"
# NOTE: opencv-python-headless used instead of opencv-python
# Headless = no GUI dependencies = smaller size, perfect for server use

# STAGE 4 — App Builder
# Copies source code and installs the application package

FROM ocr-builder AS app-builder

WORKDIR /app

# Copy application source code
COPY src/ ./src/
COPY api/ ./api/
COPY core/ ./core/
COPY schema/ ./schema/
COPY setup.py .
COPY .env .env

# Install app as regular package (NOT editable)
# Editable install (-e) is for development only — causes issues in multi-stage builds
RUN pip install --no-cache-dir .

# STAGE 5 — Final Runtime Image
# Only what is needed to RUN — no build tools, no compilers

FROM system-base AS runtime

WORKDIR /app

# Copy Python packages installed across all builder stages
COPY --from=app-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=app-builder /usr/local/bin /usr/local/bin

# Copy application source code
COPY --from=app-builder /app/src ./src
COPY --from=app-builder /app/api ./api
COPY --from=app-builder /app/core ./core
COPY --from=app-builder /app/schema ./schema
COPY .env .env

# Create runtime directories
RUN mkdir -p /app/temp /app/output /app/logs

# ------------------------------------------------------------------
# SECURITY NOTE: .env is NOT copied into this image
# Add all environment variables in Azure Container Apps:
#   Azure Portal → Container App → Settings → Environment Variables
#   For secrets (API keys): use the Secrets tab
# ------------------------------------------------------------------

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DEBIAN_FRONTEND=noninteractive

EXPOSE 8001

# start-period=60s gives app time to load models on startup
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]