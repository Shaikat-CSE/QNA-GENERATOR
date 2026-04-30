# Auto-Linking QNA to ContentGenerator Slides

## How It Works

When ContentGenerator generates slides, it creates an exam tab for each topic. You need to modify the slide generation code to automatically inject an iframe pointing to the QNA topic page.

## Step 1: Copy QNA Output to ContentGenerator

After generating QNA HTML:

```bash
# Generate QNA with PDF theme
cd C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\QNA-Generator
python build_html_from_markdowns.py \
  --input-dir "C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse\Biology\Edexcel Biology (4BI1)\markdowns" \
  --html-theme pdf

# Copy to ContentGenerator
cp -r "C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse\Biology\Edexcel Biology (4BI1)\markdowns_site" \
      "C:\Users\gmhome\SynologyDrive\Ragmaterials\ContentGenerator\output\exam-qna\biology"
```

## Step 2: Modify slide_generator.py

Edit `C:\Users\gmhome\SynologyDrive\Ragmaterials\ContentGenerator\shared\slide_generator.py`

### A. Add helper function to load topic mapping (add after line 23):

```python
def load_qna_topic_mapping(subject: str, output_dir: Path) -> dict[str, Any]:
    """Load QNA topic mapping for iframe URLs"""
    mapping_path = output_dir / "exam-qna" / subject.lower() / "topic_mapping.json"
    if mapping_path.exists():
        return json.loads(mapping_path.read_text(encoding="utf-8"))
    return {}
```

### B. Modify build_topic_slide_html function (line 1325):

Replace lines 1380-1382:

**Before:**
```python
<div class="tab-panel exam-panel" data-panel="exam">
  <div class="exam-questions" data-exam-slide="{topic['id']}"></div>
</div>
```

**After:**
```python
<div class="tab-panel exam-panel" data-panel="exam">
  {build_exam_iframe_html(topic['id'], topic.get('qna_url', ''))}
</div>
```

### C. Add iframe builder function (add after line 1323):

```python
def build_exam_iframe_html(topic_id: str, qna_url: str) -> str:
    """Build iframe HTML for QNA integration or placeholder"""
    if qna_url:
        return f'''<iframe class="exam-iframe" 
          data-topic-id="{topic_id}"
          src="{qna_url}"
          frameborder="0"
          style="width: 100%; height: calc(100vh - 180px); border: none; background: #ffffff;">
        </iframe>'''
    else:
        return f'<div class="exam-questions" data-exam-slide="{topic_id}"></div>'
```

### D. Modify generate_comprehensive_chapter_slide function (line 991):

Add QNA mapping lookup after line 1045:

```python
# Load QNA topic mapping
qna_mapping = load_qna_topic_mapping(subject, output_dir)

for idx, topic in enumerate(topics, 1):
    print(f"\n  [{idx}/{len(topics)}] Processing topic {topic['topic_code']}: {topic['title']}")
    
    # Match QNA URL by topic slug
    topic_slug = slugify(f"{topic.get('chapter_name', '')}-{topic['title']}")
    qna_match = qna_mapping.get(topic_slug)
    qna_url = ""
    if qna_match:
        # Build relative path from slide to QNA
        qna_url = f"../../exam-qna/{subject.lower()}/{qna_match['url']}"
        print(f"    Found QNA match: {qna_match['question_count']} questions")
    
    # Generate comprehensive spec with retry
    # ... (rest of the code)
```

### E. Pass QNA URL to topic spec (after line 1126):

```python
# Override AI's id with the correct topic code
topic_spec['id'] = actual_topic_code
topic_spec['qna_url'] = qna_url  # Add this line
print(f"    [DEBUG] Set topic_spec['id'] to: '{topic_spec['id']}'")
```

## Step 3: Add CSS for iframe (optional)

The template already has `.exam-panel` styles, but you can add iframe-specific styles to `comprehensive_chapter_template.html` around line 424:

```css
.exam-iframe {
  width: 100%;
  height: calc(100vh - 180px);
  border: none;
  background: #ffffff;
}

.tab-panel.exam-panel {
  padding: 0;
  overflow: hidden;
}
```

## Step 4: Topic Slug Matching

The key is matching ContentGenerator topic IDs to QNA topic slugs. QNA uses:

```
{chapter-name}-{topic-name}
```

For example:
- QNA slug: `structures-and-functions-in-living-organisms-nutrition-in-plants`
- ContentGenerator needs to generate the same slug from its topic data

If your topics have `chapter_name` and `title` fields, the slugify function will create matching slugs.

## Step 5: Test the Integration

1. Generate QNA HTML with PDF theme
2. Copy to ContentGenerator's `output/exam-qna/{subject}/`
3. Generate new slides with ContentGenerator
4. Open the generated slide HTML
5. Click the "Exam" tab - should show QNA iframe

## Fallback Behavior

If no QNA match is found, the code falls back to the original placeholder:
```html
<div class="exam-questions" data-exam-slide="{topic_id}"></div>
```

This ensures slides still work even without QNA integration.

## Directory Structure

```
ContentGenerator/
├── output/
│   ├── slides/
│   │   └── biology/
│   │       └── chapter-2-cell-biology.html  ← Generated slides
│   └── exam-qna/
│       └── biology/
│           ├── topics/
│           │   └── nutrition-in-plants.html  ← QNA pages
│           ├── topic_mapping.json            ← Mapping file
│           └── _site_assets/
└── shared/
    └── slide_generator.py                    ← Modified file
```

## Troubleshooting

**Iframe not showing:**
- Check relative path from slide to QNA folder
- Verify topic_mapping.json exists
- Check browser console for errors

**Topic not matched:**
- Print the slugs being compared
- Ensure chapter_name is available in topic data
- Check slugify function produces consistent output

**Layout issues:**
- QNA PDF theme is designed for full viewport
- Ensure iframe has proper height
- Remove padding from `.exam-panel` to avoid scrollbars
