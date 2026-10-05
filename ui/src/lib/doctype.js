// One label map for every surface that shows a document classification.
//
// Two vocabularies reach the UI. Chunk payloads and the corpus API carry
// `document_type` — the filterable, hyphenated classification ("regulation",
// "annex", "press-release") — and `doc_type`, the canonical underscored form
// the registry constraint allows ("press_release", "reflection_paper").
// Both are mapped so a display never falls through to a raw slug.
export const DOCTYPE_LABEL = {
  // document_type
  guidance: 'Guidance',
  'press-release': 'Press Release',
  'reflection-paper': 'Reflection Paper',
  regulation: 'Regulation',
  annex: 'Annex',
  'qa-guidance': 'Q&A Guidance',
  'safety-communication': 'Safety Communication',
  news: 'News',
  'regulatory-decision': 'Regulatory Decision',
  // doc_type
  drug_approval: 'Drug Approval',
  press_release: 'Press Release',
  safety_alert: 'Safety Alert',
  reflection_paper: 'Reflection Paper',
  news_item: 'News Item',
  other: 'Unclassified',
  other_document: 'Other',
  training_material: 'Training Material',
  concept_paper: 'Concept Paper',
};

// document_type wins: it is the more specific classification (a "regulation"
// stays a regulation; only its canonical doc_type collapses to "guidance").
export function docTypeLabel(obj) {
  if (!obj) return '—';
  const dt = obj.document_type || obj.documentType;
  const ct = obj.doc_type;
  return DOCTYPE_LABEL[dt] || DOCTYPE_LABEL[ct] || dt || ct || '—';
}
