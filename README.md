# QNA Generator

A tool for converting paired exam PDFs (question papers + mark schemes) into structured Markdown files with an interactive GUI.

## Quick Start

```powershell
# Launch the GUI (recommended)
python run.py
```

## Project Structure

```
QNA-Generator/
├── run.py                 # Main GUI application
├── scripts/               # CLI scripts
│   ├── convert_pdfs_to_markdown.py
│   ├── build_html_from_markdowns.py
│   └── check_availability.py
├── src/                   # Core source code
│   ├── pdf_availability_scanner.py
│   ├── renamer_engine.py
│   ├── rename_pdfs.py
│   └── ...
├── config/                # Configuration files
│   ├── subject_rules.json
│   ├── filename_aliases.json
│   └── profiles/
└── docs/                  # Documentation
```

## GUI Usage

The **Desktop GUI** (`run.py`) is the recommended interface:

```powershell
python run.py
```

### Tabs:
- **Convert PDFs** - Generate markdown from PDF question papers and mark schemes
- **Rename PDFs** - Batch rename messy PDFs to standardized names
- **Availability** - Scan and view paper availability matrix
- **Settings** - Configure environment

### GUI Features:
- PDF folder selection with auto-derived output folder
- Profile and taxonomy mode selection
- LLM, OCR, and embedding mode options
- Full pipeline (convert + build HTML) in one click
- Live log output panel
- Progress tracking with cancel support

## CLI Scripts

For advanced usage, CLI scripts are available in `scripts/`:

### Convert PDFs to Markdown

```powershell
python scripts/convert_pdfs_to_markdown.py --input-dir "C:\path\to\past-papers"
```

Options:
```powershell
--input-dir <path>           # PDF input folder
--output-dir <path>          # Markdown output folder (default: sibling markdowns/)
--profile-file <path>         # Profile file (default: config/profiles/edexcel_generic.json)
--llm-mode <mode>            # off, cleanup, cleanup-and-tag (default: cleanup-and-tag)
--ocr-mode <mode>            # off, rapidocr (default: rapidocr)
--embedding-mode <mode>       # off, clip (default: off)
--paper-filter <filter>       # Filter specific papers
--limit <n>                  # Limit number of papers to process
```

### Build HTML Site

```powershell
python scripts/build_html_from_markdowns.py --input-dir ".\markdowns"
```

Options:
```powershell
--input-dir <path>           # Markdown folder
--output-dir <path>          # HTML output folder (default: <input>_site)
--image-mode <mode>           # linked, embed (default: linked)
--theme <theme>              # modern, pdf (default: modern)
```

### Check Availability

```powershell
python scripts/check_availability.py --base "C:\path\to\exams"
```

## PDF Renamer

Batch rename PDFs using LLM-generated rules:

```powershell
# Generate rules first
python -m src.rename_pdfs --base "C:\path\to\exams" --mode generate-rules

# Auto-rename PDFs
python -m src.rename_pdfs --base "C:\path\to\exams" --mode rename
```

### Naming Convention

```
{year}-{session}-{level}-{subject}-{board}-{code}-{paper}-{variant}-{type}.pdf
```

Example: `2024-s-igcse-biology-edexcel-4bi1-1-n-qp.pdf`

## Supported Subjects

**A-Level:** Accounting, Biology, Business, Chemistry, Chinese, Computer Science, Design Technology, Economics, English Language, English Literature, French, Further Mathematics, Geography, Global Perspectives, History, Information Technology, Mathematics, Physical Education, Physics, Psychology, Sociology

**IGCSE:** Additional Mathematics, Biology, Business Studies, Chemistry, Chinese, Combined Science, Commerce, Computer Science, Design Technology, Economics, English Literature, English Second Language, Geography, History, ICT, International Mathematics, Mathematics, Physics, Psychology

**IB:** Biology, Business Management, Chemistry, Computer Science, Design Technology, Digital Societies, Economics, English A Language Literature, Environmental Systems Societies, Geography, Global Politics, History, Mathematics AA, Music, Philosophy, Physics, Psychology, Social and Cultural Anthropology, Sports Exercise Health Science, Visual Arts

## Configuration

### Environment Variables

```powershell
$env:MINIMAX_API_KEY='...'
$env:MINIMAX_BASE_URL='https://api.sfkey.cn/'
$env:MINIMAX_MODEL='MiniMax-M2.7-highspeed'
```

Or use a `.env` file (auto-loaded by the GUI).

### Profiles

Profiles in `config/profiles/`:
- `edexcel_generic.json`
- `cambridge_igcse.json`
- `igcse_generic.json`
- `ib_generic.json`
- `alevel_generic.json`

## Output Layout

```
markdowns/
├── 2019/
│   └── 2019-s-igcse-biology-edexcel-4bi1-1-n/
│       ├── q1a.md
│       ├── q1a.blocks.json
│       └── q2a.md
├── 2023/
│   └── 2023-s-igcse-biology-edexcel-4bi1-01-n/
│       └── ...
├── manifest.json
├── topic_index.json
├── topic_index.md
└── _assets/
```

## PDF Availability Scanner

The scanner provides a visual matrix to track exam paper availability.

### Matrix View
- Rows: Subjects
- Columns: Year-Session (e.g., 2023-S, 2023-W)
- Color-coded cells:
  - Green = Complete (has QP and MS)
  - Yellow = Partial (missing QP or MS)
  - Red = Missing both

### Features
- Filter by year, subject, syllabus, or status
- Upload missing files
- Replace existing files
- Export to CSV

## Notes

- The GUI is the recommended interface for most workflows
- CLI scripts are useful for automation and scripting
- The renamer requires MiniMax API access for rule generation
- HTML output requires an existing markdown folder from the converter
