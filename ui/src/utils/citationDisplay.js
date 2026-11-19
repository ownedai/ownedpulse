// Screen numbering of citations. The screen shows the original citation index,
// the same number the JSON export and the PDF use. Nothing is renumbered.
// Cited sources are listed first, each group in original index order.

export function displayCitations(result) {
  const raw = result?.citations || [];
  const rawAnswer = result?.answer || '';
  if (!raw.length) return { citations: raw, answerText: rawAnswer };

  const cited = raw.filter((c) => c.cited_by_llm).sort((a, b) => a.index - b.index);
  const uncited = raw.filter((c) => !c.cited_by_llm).sort((a, b) => a.index - b.index);

  // Strip decimal sub-citations [N.M] to [N] (LLM safety net). Other markers are unchanged;
  // the display rule in citationMarkers.js shows ranges and lists with the same indices.
  const answerText = rawAnswer.replace(/\[(\d+)\.\d+\]/g, (_, n) => '[' + n + ']');

  return { citations: [...cited, ...uncited], answerText };
}
