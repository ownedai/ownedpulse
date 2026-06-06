# Frontend Component Structure

```
src/
  components/
    layout/
      TopNav.jsx              ← page title (left) + theme toggle (right). NO logo. 44px.
      Sidebar.jsx             ← logo + nav items + contextual Recent Queries (/ only) + system info
      FilterBar.jsx           ← below query input on Query page only. Popovers for Date/Retrieval.
      RetrievalSettings.jsx   ← gear icon popover (NOT expanding row)
      SourceDrawer.jsx        ← fixed overlay drawer, tabs: Chunk | Provenance | Trace
    query/
      QueryInput.jsx
      AnswerPanel.jsx
      CitationCard.jsx
      QueryExpansion.jsx      ← collapsible sub-query display
      AuditFooter.jsx
      ThinkingIndicator.jsx
      EmptyState.jsx
      CorpusStatsBar.jsx      ← landing page stats (no clickable nav on agency counts)
    pages/
      HistoryPage.jsx         ← /history
      CorpusRegistryPage.jsx  ← /corpus
      DocumentDetailPage.jsx  ← /corpus/:docId
      RunLogPage.jsx          ← /corpus/runs
      AdminPage.jsx           ← /admin
    corpus/
      SupersedeChain.jsx      ← horizontal pill chain with arrows
      ChunkList.jsx           ← paginated chunk table with expandable rows
      HashComparison.jsx      ← PG vs Qdrant hash with match indicator
    admin/
      SystemHealth.jsx
      FeedManagement.jsx      ← toggle switch, PATCH /admin/feeds/{id}
      PipelineTrigger.jsx
      ModelSelection.jsx
    common/
      Logo.jsx
      Badge.jsx               ← MATCHED / NOT CITED / SUPERSEDED / status variants
      ProvMetadata.jsx        ← all 9 provenance fields
      Tooltip.jsx             ← reusable, 300ms delay
      ThemeToggle.jsx
      StatusBadge.jsx         ← running/complete/error/indexed variants
  hooks/
    useQuery.js
    useHistory.js
    useCorpusStats.js
    useCorpusDocuments.js
    useTheme.js               ← localStorage persistence
    useLangfuseTrace.js
    useRunLog.js
    useAdminHealth.js
  api/
    client.js                 ← API_BASE from VITE_API_URL || ''
  App.jsx                     ← routing: /, /history, /corpus, /corpus/:docId, /corpus/runs, /admin
  main.jsx
  index.css
```

Routing via `react-router-dom`.
