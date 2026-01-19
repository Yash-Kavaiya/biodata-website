# Biodata Management System

A full-stack application for biodata OCR processing and match finding, built with FastAPI and vanilla JavaScript.

## Features

- **Upload**: Single or bulk PDF/image upload with async processing
- **LLM-powered OCR**: Uses Claude to extract structured data from biodata documents
- **Validation Workflow**: Approve, edit, re-OCR, or reject extracted data
- **Match Finding**: Search by preferences or upload a biodata to find compatible profiles
- **Local Storage**: JSON database and local file storage (cloud-ready architecture)

## Architecture

```
biodata-website/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration settings
│   ├── models/              # Pydantic models
│   │   └── biodata.py       # Biodata schemas
│   ├── services/            # Business logic (SOLID principles)
│   │   ├── storage_service.py    # File storage (local/cloud)
│   │   ├── database_service.py   # JSON database
│   │   ├── ocr_service.py        # LLM-based OCR
│   │   └── similarity_service.py # Match finding
│   ├── routers/             # API endpoints
│   │   ├── upload.py        # Upload endpoints
│   │   ├── biodata.py       # CRUD endpoints
│   │   ├── validation.py    # Validation workflow
│   │   └── search.py        # Search/match endpoints
│   └── db/                  # Database files
│       ├── biodata.json     # Biodata storage
│       └── embeddings.pkl   # Similarity index
├── frontend/
│   ├── templates/
│   │   └── index.html       # Main HTML page
│   └── static/
│       ├── css/styles.css   # Styling
│       └── js/app.js        # Frontend logic
├── uploads/                 # Uploaded files
├── requirements.txt
└── .env.example
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### 3. Run the Application

```bash
# From project root
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open in Browser

Navigate to http://localhost:8000

## API Documentation

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

## API Endpoints

### Upload
- `POST /api/upload/single` - Upload single file
- `POST /api/upload/bulk` - Upload multiple files
- `POST /api/upload/async/single` - Async single upload
- `POST /api/upload/async/bulk` - Async bulk upload

### Biodata
- `GET /api/biodata` - List all biodatas
- `GET /api/biodata/{id}` - Get biodata by ID
- `POST /api/biodata` - Create biodata manually
- `PUT /api/biodata/{id}` - Update biodata
- `DELETE /api/biodata/{id}` - Delete biodata

### Validation
- `POST /api/validation/approve/{id}` - Approve OCR result
- `POST /api/validation/reject/{id}` - Reject OCR result
- `POST /api/validation/edit/{id}` - Edit and approve
- `POST /api/validation/re-ocr/{id}` - Re-run OCR
- `POST /api/validation/auto-approve-all` - Auto-approve high confidence

### Search
- `POST /api/search/preferences` - Search by preferences
- `GET /api/search/simple` - Simple search with query params
- `POST /api/search/by-biodata/{id}` - Find matches for a biodata
- `POST /api/search/by-upload` - Upload and find matches
- `GET /api/search/stats` - Get search statistics

## Design Principles

This project follows **SOLID principles**:

- **Single Responsibility**: Each service handles one concern
- **Open/Closed**: Easy to extend (e.g., add new storage providers)
- **Liskov Substitution**: Storage interfaces are interchangeable
- **Interface Segregation**: Clean, focused interfaces
- **Dependency Inversion**: Services depend on abstractions

## Future Enhancements

- [ ] Cloud storage integration (Google Cloud Storage)
- [ ] Advanced similarity search with embeddings
- [ ] User authentication
- [ ] PDF generation for biodatas
- [ ] Email notifications
- [ ] Mobile-responsive improvements

## License

MIT
