# docling-spring

A Spring Boot service that converts documents (PDF, DOCX, PPTX, HTML, images, etc.)
into Markdown files using [Docling](https://github.com/docling-project/docling).

Docling is a Python library/CLI, not a Java library, so this app shells out to the
`docling` command-line tool via `ProcessBuilder` and reads back the generated `.md` file.

## Prerequisites

- Java 17+
- Maven 3.9+
- Python 3.9+ with Docling installed:

  ```bash
  pip install docling
  ```

  Verify it's on your PATH:

  ```bash
  docling --version
  ```

## Running locally

```bash
mvn spring-boot:run
```

The app starts on `http://localhost:8080`.

## Configuration

`src/main/resources/application.yml`:

```yaml
docling:
  executable: docling          # path to the docling CLI, or just "docling" if on PATH
  upload-dir: ./data/uploads   # where uploaded source files are staged
  output-dir: ./data/output    # where converted markdown is written
  timeout-seconds: 300         # kill the conversion if it runs longer than this
```

Any of these can be overridden with environment variables, e.g.:

```bash
DOCLING_EXECUTABLE=/usr/local/bin/docling java -jar target/docling-spring-1.0.0.jar
```

## API

### Convert and get markdown text back as JSON

```bash
curl -F "file=@report.pdf" http://localhost:8080/api/convert/markdown
```

Response:

```json
{
  "originalFilename": "report.pdf",
  "markdown": "# Report Title\n\n..."
}
```

### Convert and download the .md file directly

```bash
curl -F "file=@report.pdf" http://localhost:8080/api/convert/markdown/file -o report.md
```

## Docker

Build and run (bundles Java + Python + Docling in one image):

```bash
docker build -t docling-spring .
docker run -p 8080:8080 docling-spring
```

## Notes

- Supported input formats depend on your installed Docling version — typically PDF,
  DOCX, PPTX, XLSX, HTML, images (PNG/JPEG), and Markdown/AsciiDoc.
- Each request gets its own UUID-named upload/output subfolder so concurrent
  conversions don't collide.
- For heavy production use, consider running Docling conversions as an async job
  (e.g. queue + polling endpoint) since PDF/OCR conversion can take a while for
  large files — the current implementation is synchronous per request.
