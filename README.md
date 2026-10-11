# Bulk Certificate Generator

A backend API that takes a list of recipients in one request, generates a PDF
certificate for each of them from a predefined template, and lets the client
track progress and download the results.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, SQLite (any relational database
supported by SQLAlchemy works), ReportLab for PDFs, pytest.

## How it works

1. The client sends `POST /jobs` with the course details and a list of recipients.
2. The API validates the request, stores a **job** and one **certificate row per
   recipient**, and answers straight away with `202 Accepted` and a job id.
3. A background task generates the PDFs one by one and updates each row.
4. The client polls `GET /jobs/{id}` for progress, then downloads certificates
   individually or all together as a ZIP.

```
app/
  main.py                  app creation, startup (create tables, resume unfinished jobs)
  routes.py                HTTP endpoints
  services.py              create a job, process a job, count statuses
  certificate_template.py  the certificate design (draws one PDF)
  models.py                database tables: Job, Certificate
  schemas.py               request/response models and validation rules
  database.py              engine and session
  config.py                settings from environment variables
tests/                     pytest suite
sample_request.json        example request body
```

## Setup

Requires Python 3.11 or newer.

```bash
git clone <your-repo-url>
cd bulk-certificate-generator

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration (optional)

All settings have defaults, so nothing is required to get started.

| Environment variable     | Default                       | Meaning                                  |
| ------------------------ | ----------------------------- | ---------------------------------------- |
| `DATABASE_URL`           | `sqlite:///./certificates.db` | SQLAlchemy database URL                  |
| `STORAGE_DIR`            | `./generated_certificates`    | Folder where PDFs are written            |
| `MAX_RECIPIENTS_PER_JOB` | `5000`                        | Largest recipient list a request may have |

To use PostgreSQL instead of SQLite, install a driver (`pip install "psycopg[binary]"`)
and set `DATABASE_URL=postgresql+psycopg://user:password@localhost/certificates`.

## Run the application

```bash
uvicorn app.main:app --reload
```

The API is at <http://127.0.0.1:8000>. Interactive documentation (Swagger UI),
where every endpoint can be tried from the browser, is at
<http://127.0.0.1:8000/docs>. Tables are created automatically on startup.

## Run the tests

```bash
pytest
```

The tests use their own temporary database and output folder, so they never
touch real data.

## API

| Method | Path                               | Purpose                                         |
| ------ | ---------------------------------- | ----------------------------------------------- |
| POST   | `/jobs`                            | Submit a bulk generation request                |
| GET    | `/jobs`                            | List jobs, newest first                         |
| GET    | `/jobs/{job_id}`                   | Job status and progress                         |
| GET    | `/jobs/{job_id}/certificates`      | Per-recipient results (filter with `?status=`)  |
| GET    | `/jobs/{job_id}/download`          | All generated certificates of the job as a ZIP  |
| GET    | `/certificates/{certificate_id}`   | Details of one certificate                      |
| GET    | `/certificates/{certificate_id}/download` | One certificate as a PDF                 |
| GET    | `/health`                          | Health check                                    |

### Submit a certificate generation request

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```

Request body:

```json
{
  "course_name": "Python Backend Bootcamp",
  "issued_by": "Acme Academy",
  "issue_date": "2026-10-01",
  "recipients": [
    { "name": "Asha Verma", "email": "asha.verma@example.com" },
    { "name": "Rahul Mehta", "email": "rahul.mehta@example.com" }
  ]
}
```

- `course_name`, `issued_by`: required, 1–150 characters.
- `issue_date`: optional, `YYYY-MM-DD`, defaults to today.
- `recipients`: required, 1 to `MAX_RECIPIENTS_PER_JOB` items, each with a
  `name` (1–100 characters) and a valid `email`.

Response, `202 Accepted`:

```json
{
  "id": "dc3a3fff-0eab-44bf-94b0-c8fdede0c6d6",
  "status": "pending",
  "counts": { "total": 2, "pending": 2, "generated": 0, "failed": 0, "invalid": 0 },
  "progress_percent": 0.0,
  "status_url": "/jobs/dc3a3fff-0eab-44bf-94b0-c8fdede0c6d6",
  "certificates_url": "/jobs/dc3a3fff-0eab-44bf-94b0-c8fdede0c6d6/certificates",
  "download_url": "/jobs/dc3a3fff-0eab-44bf-94b0-c8fdede0c6d6/download",
  "...": "..."
}
```

### Check progress

```bash
curl http://127.0.0.1:8000/jobs/<job_id>
```

```json
{
  "id": "dc3a3fff-0eab-44bf-94b0-c8fdede0c6d6",
  "status": "completed_with_errors",
  "counts": { "total": 5, "pending": 0, "generated": 3, "failed": 0, "invalid": 2 },
  "progress_percent": 100.0,
  "started_at": "2026-10-11T12:10:43.961508",
  "completed_at": "2026-10-11T12:10:44.011112",
  "...": "..."
}
```

Job statuses:

| Status                  | Meaning                                         |
| ----------------------- | ----------------------------------------------- |
| `pending`               | Accepted, generation has not started            |
| `processing`            | Certificates are being generated                |
| `completed`             | Every recipient got a certificate               |
| `completed_with_errors` | Some certificates were generated, some were not |
| `failed`                | No certificate could be generated               |

Certificate statuses: `pending`, `generated`, `failed` (valid data, but
generation raised an error) and `invalid` (the recipient data failed validation,
so generation was never attempted). All timestamps are UTC.

To see what went wrong and for whom:

```bash
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates?status=invalid"
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates?status=failed"
```

```json
{
  "total": 1,
  "limit": 100,
  "offset": 0,
  "items": [
    {
      "id": "c2ae4347-074c-485b-9f05-2b22cd719c0b",
      "row_number": 5,
      "recipient_name": "Broken Email",
      "recipient_email": "not-an-email",
      "status": "invalid",
      "error_message": "email: value is not a valid email address: An email address must have an @-sign.",
      "download_url": null
    }
  ]
}
```

`row_number` is the position of the recipient in the submitted list (starting
at 1), so a result can be matched back to the input. The list is paginated with
`limit` (max 500) and `offset`.

### Retrieve generated certificates

One certificate — take `download_url` from the certificate list:

```bash
curl -o certificate.pdf http://127.0.0.1:8000/certificates/<certificate_id>/download
```

Every generated certificate of a job in one ZIP:

```bash
curl -o certificates.zip http://127.0.0.1:8000/jobs/<job_id>/download
```

Asking for the PDF of a certificate that is not `generated` returns `409`.
The ZIP can be requested while a job is still running; it contains whatever has
been generated so far, and returns `404` if nothing has been generated yet.

## Design decisions

**Background processing instead of synchronous.** A request may contain
thousands of recipients. Generating them inside the request would keep the
client waiting, risk HTTP timeouts, and lose everything if the connection
dropped. So `POST /jobs` only validates and stores the job, returns `202` with a
job id, and the generation runs afterwards using FastAPI's `BackgroundTasks`.
The client polls the status endpoint.

**Why `BackgroundTasks` and not Celery/RQ.** It needs no extra infrastructure
(no Redis, no separate worker process), which keeps the project easy to set up
and review. The trade-off is that the work runs inside the web server process:
it does not survive a crash on its own and it does not scale across machines.
Two things soften that:

- All progress is in the database, and on startup the app **resumes any job
  left in `pending` or `processing`**, picking up only the certificates that are
  still pending.
- All generation goes through one function, `services.process_job(job_id)`.
  Moving to a real task queue means turning that function into a Celery task and
  changing the one line in `routes.py` that schedules it.

**One database row per recipient.** The `certificates` table holds a row for
every submitted recipient, valid or not, with its own status and error message.
That is what makes it possible to say exactly which certificates succeeded and
which failed, and why. Job counts are computed from these rows with a
`GROUP BY` rather than stored as counters, so they cannot drift out of sync.

**Two levels of validation.**

- Problems with the request as a whole (missing course name, empty list, too
  many recipients, bad date) reject the request with `422`, since there is
  nothing sensible to generate.
- Problems with an individual recipient (missing name, bad email, duplicate
  email within the request) do **not** reject the request. The row is stored
  as `invalid` with the reason, and the valid recipients are still processed.
  With a list of 2,000 people, rejecting everything because of one typo would
  be a poor experience.

**Failure isolation.** Each certificate is generated inside its own
`try/except` and committed on its own. An error is recorded on that row
(`failed` + `error_message`) and the loop moves on. Committing per certificate
is also what makes progress visible while the job is running.

**Storage.** PDFs are written to the local filesystem under
`STORAGE_DIR/<job_id>/<certificate_id>.pdf`, and the database stores the
relative path. File names are built from generated ids only, never from user
input, so there is no path-injection risk. In production this would be object
storage such as S3.

**Template.** A single landscape A4 design drawn with ReportLab in
`certificate_template.py`. It is a plain function that takes the recipient
details and an output path and knows nothing about jobs or the database, so it
can be tested alone and replaced without touching anything else. Long names are
shrunk to fit on one line.

**SQLite by default.** It is a relational database that needs no installation,
so the project runs with one command. It is opened in WAL mode so status
requests can read while the worker writes. Nothing in the code is
SQLite-specific apart from that connection setup; switching database is a
change of `DATABASE_URL`.

**Ids are UUIDs** rather than sequential numbers, so download links cannot be
guessed by counting.

### Performance

On a laptop, a job of 2,000 recipients is accepted in about half a second and
finishes generating in roughly 18 seconds (about 9 ms per certificate).

### Known limitations and possible next steps

- The template uses PDF built-in fonts, which cover Western European characters
  only. A name in another script (for example Devanagari) is marked `failed`
  with a clear message rather than printed as boxes. Fix: embed a Unicode TTF
  font.
- No authentication. Anyone who can reach the API can submit jobs and download
  certificates.
- One job is processed by one thread. For much larger volumes, use a task queue
  with several workers.
- There is no endpoint to retry failed certificates or to delete old jobs and
  their files.
- The ZIP is built in memory, which is fine for thousands of small PDFs but
  should be streamed for very large jobs.
- Tables are created with `create_all`. A real deployment would use Alembic
  migrations.
- Accepting a CSV upload in addition to JSON would be a natural addition.
