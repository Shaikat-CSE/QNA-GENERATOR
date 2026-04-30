# QNA Generator → ContentGenerator Integration Guide

## Overview
This guide shows how to link the QNA Generator exam questions into the ContentGenerator's "Exam" tab.

## Architecture
- **QNA Generator**: Standalone HTML pages (separate project)
- **ContentGenerator**: Slide-based content with tabs
- **Integration**: Iframe embedding with topic-based routing

## Step 1: Generate QNA HTML with PDF Theme

```bash
cd C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\QNA-Generator

python build_html_from_markdowns.py \
  --input-dir "C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse\Biology\Edexcel Biology (4BI1)\markdowns" \
  --html-theme pdf
```

This creates:
- `markdowns_site/` - Full QNA HTML site
- `markdowns_site/topics/{topic-slug}.html` - Topic pages
- `markdowns_site/topic_mapping.json` - Topic ID → URL mapping

## Step 2: Copy QNA Output to ContentGenerator

```bash
# Copy the entire QNA site
cp -r "C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse\Biology\Edexcel Biology (4BI1)\markdowns_site" \
      "C:\Users\gmhome\SynologyDrive\Ragmaterials\ContentGenerator\output\exam-qna\biology"
```

## Step 3: Modify ContentGenerator Slide Template

### A. Update the Exam Tab HTML

In your slide generation code, replace the exam placeholder:

**Before:**
```html
<div class="tab-panel exam-panel" data-panel="exam">
  <div class="exam-questions" data-exam-slide="8.1"></div>
</div>
```

**After:**
```html
<div class="tab-panel exam-panel" data-panel="exam">
  <iframe class="exam-iframe" 
          data-topic-id="c02_t04"
          src="../../../exam-qna/biology/topics/structures-and-functions-in-living-organisms-nutrition-in-plants.html"
          frameborder="0">
  </iframe>
</div>
```

### B. Add CSS for Iframe

Add to your slide CSS:

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

.tab-panel.exam-panel.active {
  display: block;
}
```

## Step 4: Topic ID Mapping

Use `topic_mapping.json` to map your ContentGenerator topics to QNA pages:

```json
{
  "c02_t04": {
    "chapter": "Structures and functions in living organisms",
    "topic": "Nutrition in plants",
    "slug": "structures-and-functions-in-living-organisms-nutrition-in-plants",
    "url": "topics/structures-and-functions-in-living-organisms-nutrition-in-plants.html",
    "question_count": 8
  }
}
```

### Python Integration Example:

```python
import json
from pathlib import Path

# Load mapping
mapping_path = Path("output/exam-qna/biology/topic_mapping.json")
topic_mapping = json.loads(mapping_path.read_text())

# Get QNA URL for a topic
topic_id = "c02_t04"  # From your slide metadata
if topic_id in topic_mapping:
    qna_url = f"../../../exam-qna/biology/{topic_mapping[topic_id]['url']}"
    question_count = topic_mapping[topic_id]['question_count']
else:
    qna_url = None  # Show placeholder
```

## Step 5: Dynamic Loading (Optional)

Add JavaScript to load QNA dynamically:

```javascript
// In your slide's JavaScript
document.querySelectorAll('.tab-btn[data-tab="exam"]').forEach(btn => {
  btn.addEventListener('click', function() {
    const slide = this.closest('.slide');
    const topicId = slide.dataset.topicId; // e.g., "c02_t04"
    const iframe = slide.querySelector('.exam-iframe');
    
    if (iframe && !iframe.src) {
      // Load mapping and set iframe src
      fetch('../../../exam-qna/biology/topic_mapping.json')
        .then(r => r.json())
        .then(mapping => {
          if (mapping[topicId]) {
            iframe.src = `../../../exam-qna/biology/${mapping[topicId].url}`;
          }
        });
    }
  });
});
```

## Directory Structure

```
ContentGenerator/
├── output/
│   ├── slides/
│   │   └── biology/
│   │       └── chapter-2-cell-biology.html  ← Your slides
│   └── exam-qna/
│       └── biology/
│           ├── topics/
│           │   ├── cell-structure.html      ← QNA pages
│           │   └── photosynthesis.html
│           ├── 2019/
│           ├── 2023/
│           ├── _assets/
│           ├── _site_assets/
│           ├── index.html
│           └── topic_mapping.json           ← Mapping file
```

## Benefits

✅ **Separation**: QNA Generator and ContentGenerator remain independent
✅ **Reusability**: Same QNA pages work standalone or embedded
✅ **Maintenance**: Update QNA separately, just rebuild and copy
✅ **Performance**: Iframe isolation prevents CSS/JS conflicts
✅ **Flexibility**: Can link to specific questions or topic pages

## Updating QNA Content

When you regenerate QNA:

```bash
# 1. Regenerate QNA
cd QNA-Generator
python build_html_from_markdowns.py --input-dir <path> --html-theme pdf

# 2. Copy to ContentGenerator
cp -r markdowns_site/* ../ContentGenerator/output/exam-qna/biology/

# 3. Done! Slides automatically show updated content
```

## Troubleshooting

**Iframe not showing:**
- Check relative path from slide to QNA folder
- Verify topic_mapping.json exists
- Check browser console for CORS errors

**Layout issues:**
- QNA uses full viewport height - ensure iframe has proper height
- Remove padding from `.exam-panel` to avoid double scrollbars

**Topic not found:**
- Verify topic_id matches between ContentGenerator and QNA taxonomy
- Check topic_mapping.json for available topics
