# Ports & Logistics Multi-Agent RAG System — Database Schema & Tech Stack

## 1. الـ Tools والـ Tech Stack

| الطبقة | الأداة | السبب |
|---|---|---|
| Database (structured + vectors) | **PostgreSQL 16 + pgvector extension** | مكان واحد للـ relational data والـ embeddings، يسهّل RBAC عن طريق JOINs عادية |
| Object storage (raw files) | **MinIO** (S3-compatible, self-hosted) | تخزين الـ PDFs/emails/reports الأصلية قبل المعالجة |
| Backend / ORM | **Python + SQLAlchemy + psycopg2** | التعامل مع الداتابيز من كود الـ pipeline والـ agents |
| Embedding model | **sentence-transformers (local, e.g. `all-MiniLM-L6-v2` أو `bge-base`)** أو **OpenAI/Cohere embeddings API** | يتحدد حسب لو عايز تشتغل offline (MVP تعليمي) أو تستخدم API |
| Chunking / RAG orchestration | **LlamaIndex** أو **LangChain** | إدارة الـ chunking, retrieval, prompt assembly |
| Synthetic data generation | **Faker + custom Python scripts** | توليد structured/semi-structured data واقعية الشكل |
| Document parsing | **unstructured.io** أو **PyMuPDF (fitz)** للـ PDFs, **BeautifulSoup** للـ scraping | استخراج نص نظيف من مصادر مختلفة |
| API layer | **FastAPI** | يعرض endpoints للـ agents والـ retrieval مع auth middleware |
| Auth | **JWT (PyJWT) + Role-based middleware** | تحديد هوية المستخدم ودوره قبل أي retrieval |
| Scheduling (لاحقاً مع الـ agents) | **APScheduler** أو **Airflow** (لو حبيت تتعلم orchestration أقوى) | تشغيل التقارير الدورية |
| BI Layer | **Power BI** (يتصل مباشرة بـ PostgreSQL عبر الـ native connector) | الداشبوردات |
| Containerization | **Docker + docker-compose** | تشغيل Postgres + MinIO + FastAPI مع بعض بسهولة |

> ملاحظة: البدء بـ local embedding model (sentence-transformers) مفيد تعليمياً لأنك هتفهم الأبعاد والـ vector math من غير تكلفة API، وبعدين تقدر تقارن مع OpenAI embeddings لاحقاً.

---

## 2. الـ Database Schema الكامل

```sql
-- ============================================
-- EXTENSIONS
-- ============================================
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- AUTH & RBAC
-- ============================================
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    role_name TEXT UNIQUE NOT NULL,       -- 'employee', 'manager', 'ceo'
    allowed_sensitivity_levels TEXT[] NOT NULL  -- e.g. ARRAY['public','internal']
);

CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL             -- 'Operations','Customs','Finance','HR'
);

CREATE TABLE employees (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    department_id INT REFERENCES departments(id),
    role_id INT REFERENCES roles(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    employee_id UUID REFERENCES employees(id),
    action TEXT NOT NULL,                 -- 'query_rag','view_report','login'
    resource_ref TEXT,                    -- document_id or report_id touched
    created_at TIMESTAMP DEFAULT now()
);

-- ============================================
-- STRUCTURED: PORTS & VESSELS OPERATIONS
-- ============================================
CREATE TABLE ports (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    unlocode TEXT UNIQUE                  -- UN/LOCODE standard port code
);

CREATE TABLE vessels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    imo_number TEXT UNIQUE NOT NULL,
    vessel_type TEXT,                     -- 'container','bulk','tanker'
    flag_country TEXT,
    port_id INT REFERENCES ports(id),
    eta TIMESTAMP,
    etd TIMESTAMP,
    status TEXT,                          -- 'scheduled','docked','departed','delayed'
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE containers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    container_number TEXT UNIQUE NOT NULL,
    vessel_id UUID REFERENCES vessels(id),
    cargo_type TEXT,
    weight_kg NUMERIC,
    customs_status TEXT,                  -- 'pending','cleared','held'
    destination_port_id INT REFERENCES ports(id)
);

CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vessel_id UUID REFERENCES vessels(id),
    amount NUMERIC NOT NULL,
    currency TEXT DEFAULT 'USD',
    invoice_type TEXT,                    -- 'demurrage','handling','storage'
    status TEXT,                          -- 'paid','overdue','issued'
    issued_at TIMESTAMP DEFAULT now()
);

-- ============================================
-- SEMI-STRUCTURED: AIS TRACKING / EDI MESSAGES
-- ============================================
CREATE TABLE ais_tracking (
    id BIGSERIAL PRIMARY KEY,
    vessel_id UUID REFERENCES vessels(id),
    recorded_at TIMESTAMP NOT NULL,
    payload JSONB NOT NULL                -- raw AIS-style JSON: {lat, lon, speed, heading,...}
);

CREATE TABLE edi_messages (
    id BIGSERIAL PRIMARY KEY,
    vessel_id UUID REFERENCES vessels(id),
    message_type TEXT,                    -- 'IFTMIN','COPRAR', etc.
    payload JSONB NOT NULL,
    received_at TIMESTAMP DEFAULT now()
);

-- ============================================
-- UNSTRUCTURED + RAG LAYER
-- ============================================
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT,
    source_type TEXT NOT NULL,            -- 'incident_report','email','news','contract','regulation'
    department_id INT REFERENCES departments(id),
    sensitivity_level TEXT NOT NULL DEFAULT 'internal',  -- 'public','internal','confidential','executive'
    raw_storage_path TEXT,                -- pointer to MinIO/S3 object
    source_url TEXT,                      -- if scraped from real open source
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384),                -- 384 = all-MiniLM-L6-v2 dim; change if using another model
    sensitivity_level TEXT NOT NULL,      -- inherited from document, can be overridden per chunk
    department_id INT REFERENCES departments(id),
    metadata JSONB,                       -- {tags, related_vessel_id, source_date, ...}
    created_at TIMESTAMP DEFAULT now()
);

-- Vector similarity index (IVFFlat, needs ANALYZE after bulk insert)
CREATE INDEX ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_sensitivity ON document_chunks (sensitivity_level);
CREATE INDEX idx_chunks_department ON document_chunks (department_id);

-- ============================================
-- REPORTS (output of the agents, for scheduling later)
-- ============================================
CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    generated_for_role TEXT,              -- which role this report targets
    sensitivity_level TEXT NOT NULL,
    content TEXT,                         -- generated summary/analysis
    generated_at TIMESTAMP DEFAULT now()
);
```

---

## 3. أهم قرارات التصميم (ليه كده)

- **`sensitivity_level` على مستوى الـ chunk مش الـ document بس**: عشان تقدر تتحكم بدقة أعلى لو document واحد فيه أجزاء عامة وأجزاء حساسة.
- **`roles.allowed_sensitivity_levels` كـ array**: بيخليك تعمل الـ retrieval query بسطر واحد (`sensitivity_level = ANY(role.allowed_sensitivity_levels)`) من غير if/else معقدة في الكود.
- **`ais_tracking` و `edi_messages` كـ JSONB منفصلين عن الـ RAG tables**: لأنهم semi-structured بيتقروا كـ structured queries (فلترة بالتاريخ، بالسفينة) مش بالـ semantic search زي النصوص.
- **`audit_log`**: مش إلزامي للـ MVP بس بيفيدك تتعلم كمان إزاي تتبع مين شاف إيه، وده جزء مهم في أي نظام فيه RBAC حقيقي.
- **الـ vector dimension = 384**: مبني على `all-MiniLM-L6-v2`. لو قررت تستخدم OpenAI embeddings (`text-embedding-3-small` مثلاً) لازم تغيّرها لـ 1536.

الخطوة الجاية المنطقية: نكتب الـ synthetic data generator اللي يملأ الجداول الـ structured دي، وبعدين ingestion pipeline يملأ `documents` و `document_chunks` من المصادر الحقيقية.
