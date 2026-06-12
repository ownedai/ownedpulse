# Simplify Initial Load / Corpus Reload Modal
Design spec per user instruction 2026-06-12.

## State
```javascript
const [includeBaseCorpus, setIncludeBaseCorpus] = useState(true)
const [selectedSources, setSelectedSources] = useState({
  fda_press_releases: true, ema_reg_guidance: true,
  ema_sci_guidelines: true, ich_guidelines: true
})
const [depth, setDepth] = useState('1year')
const [fileStrategy, setFileStrategy] = useState('use_local')
const [confirmed, setConfirmed] = useState(false)
const [nuclearConfirmed, setNuclearConfirmed] = useState(false)
```

## Request body mapping
- `mode`: nuclear → `full_reset`; else → `wipe_and_reload`
- `redownload`: use_local → `none`; redownload → `force`
- `base_corpus`: includeBaseCorpus ? [all 9 doc_ids] : []
- `rss_feeds`: selectedSources with true values, filtered through depth → date_from

## Sections
1. BASE CORPUS: checkbox + description
2. SOURCES: 4 checkboxes with doc counts
3. HISTORICAL DEPTH: pill buttons (1y, 3y, 5y, all)
4. FILE STRATEGY: radio buttons (use_local, redownload, nuclear)
5. CONFIRMATION: checkbox(es)
