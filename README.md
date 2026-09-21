# Document Intelligence

**Intelligent Document Processing Platform** - Enterprise-grade document extraction using AI-powered OCR and LLM providers with advanced document segmentation.

## Features

- **Multiple OCR Providers**: Mistral, Azure Document Intelligence, PaddleOCR, Marker, Surya, Tesseract, EasyOCR, Google Vision, AWS Textract
- **Multiple LLM Extractors**: Azure OpenAI (GPT-5.5), Gemini, OpenAI, Mistral, NuExtract (local)
- **Document Segmentation**: Intelligent multi-document detection and splitting with ML-enhanced boundaries
- **Multi-Agent Extraction**: Specialized agents for complex document structures
- **Visual Workflow Builder**: Drag-and-drop workflow creation with ReactFlow
- **Custom Schema Management**: Create and manage extraction schemas via UI
- **Real-time Progress**: WebSocket support for live extraction updates
- **Document Caching**: Smart caching for OCR and segmentation results
- **Role-Based Access Control**: Admin, user roles with workflow permissions
- **API Key Management**: Per-workflow API key generation
- **Cloud Storage**: Azure Blob Storage for document persistence
- **PostgreSQL Database**: Enterprise-grade data persistence

## Supported Documents

- Bill of Entry (Import)
- Shipping Bill (Export)
- Invoice, Receipt, Purchase Order
- Bank Statement, Contract
- ID Card, Medical Prescription
- Multi-document PDFs (auto-segmentation)
- Generic documents with custom schemas

## Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 13+
- Azure Blob Storage account

---

## Environment Configuration

### Required Environment Variables

```env
# PostgreSQL Database (REQUIRED)
DB_HOST=your-postgres-host
DB_PORT=5432
DB_NAME=idp-platform
DB_USER=postgres
DB_PASSWORD=your_password

# Azure Blob Storage (REQUIRED)
AZURE_STORAGE_CONNECTION_STRING=your_connection_string
AZURE_STORAGE_DOCUMENTS_CONTAINER=idp-docstore

# Azure OpenAI (REQUIRED for extraction)
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-5.5
AZURE_OPENAI_MINI_DEPLOYMENT=gpt-5.5
# AZURE_OPENAI_API_VERSION=2025-04-01-preview
# AZURE_OPENAI_REASONING_EFFORT=low

# Mistral OCR (REQUIRED)
MISTRAL_API_KEY=your_key

# Optional Providers
GEMINI_API_KEY=your_key
HF_TOKEN=your_huggingface_token
AZURE_DOC_INTELLIGENCE_ENDPOINT=your_endpoint
AZURE_DOC_INTELLIGENCE_KEY=your_key
```

---

## Running the Application

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your configuration

# Start Backend
python run_api.py
```

Backend runs at **http://localhost:8001**

- API Docs: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

---

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend runs at **http://localhost:3000**

#### Production Build

```bash
npm run build
npm start
```

---

### Docker Setup

```bash
# Backend
cd backend
docker build -t document-intelligence-backend .

# Frontend
cd frontend
docker build -t document-intelligence-frontend .
```

---

## Running Both Together

**Terminal 1 - Backend:**

```bash
cd backend
source venv/bin/activate
python run_api.py
```

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

Open http://localhost:3000 in your browser.

---

## Key Features

### Document Segmentation Lab

Access at `/lab/segmentation` - Upload multi-document PDFs and automatically detect document boundaries using ML-enhanced heuristics.

### Segmentation Profiles

Configure document detection profiles at `/settings/segmentation` - Define expected document types, detection methods, and confidence thresholds.

### Multi-Agent Extraction

Enable `use_agents=true` for complex documents - Specialized agents handle tables, nested structures, and field extraction.

---

## API Endpoints

| Endpoint                             | Description                      |
| ------------------------------------ | -------------------------------- |
| `POST /api/extract`                  | Extract data from document       |
| `POST /api/extract/segment-analysis` | Analyze document segments        |
| `POST /api/extract/multi-document`   | Process multi-document PDFs      |
| `GET /api/providers`                 | List available OCR/LLM providers |
| `GET /api/schemas`                   | List extraction schemas          |
| `GET /api/jobs`                      | Get job history                  |
| `GET /api/segmentation-profiles`     | List segmentation profiles       |
| `WS /ws/{job_id}`                    | WebSocket for real-time updates  |
| `GET /api/workflows`                 | List workflows                   |
| `POST /api/workflows`                | Create workflow                  |
| `POST /api/v1/{workflow_id}/extract` | Workflow API extraction          |

---

## Project Structure

```
Document_Intelligence/
├── backend/
│   ├── api/                    # FastAPI routes
│   │   ├── routers/            # Route handlers
│   │   ├── database/           # SQLAlchemy models (PostgreSQL)
│   │   └── auth/               # Authentication
│   ├── core/
│   │   ├── agents/             # Multi-agent extraction
│   │   ├── intelligence/       # Document segmentation
│   │   ├── providers/          # OCR & LLM providers
│   │   ├── storage/            # Azure Blob Storage
│   │   └── converters/         # Document conversion
│   ├── requirements.txt        # Dependencies
│   └── run_api.py              # Entry point
├── frontend/
│   ├── app/                    # Next.js pages
│   │   ├── lab/segmentation/   # Segmentation lab
│   │   ├── settings/           # Settings pages
│   │   └── jobs/               # Job management
│   ├── components/
│   │   ├── agui/               # Agent UI components
│   │   ├── extraction/         # Extraction components
│   │   └── workflows/          # Workflow builder
│   ├── hooks/                  # Custom React hooks
│   └── lib/                    # Utilities & API client
└── README.md
```

---

## Technology Stack

- **Backend**: FastAPI, SQLAlchemy, PostgreSQL, Azure Blob Storage
- **Frontend**: Next.js 14, React, TailwindCSS, shadcn/ui
- **AI/ML**: Azure OpenAI, Mistral, PydanticAI, scikit-learn, sentence-transformers
- **Real-time**: WebSockets for live updates

---

## License

Apache License 2.0 — Copyright 2026
