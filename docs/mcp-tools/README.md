# MCP Tools

Documentation for the BoondManager MCP tools exposed by
`apps/mcp-boondmanager`.

## Boundary

The MCP server is deterministic. It wraps BoondManager HTTP calls, handles
provider-specific paths, downloads documents, and returns structured data. It
does not call an LLM and does not decide how candidate cards should be rendered.

The Agent API owns planning, ranking, dictionary-label resolution, CV
interpretation, and final UI response normalization.

## Candidate Search And Enrichment

### `searchCandidates`

Searches BoondManager candidates from natural-language-planned filters.

- Input: search criteria accepted by the BoondManager MCP tool schema.
- Output: candidate records with ids and visible BoondManager fields.
- Notes: result shape is normalized by the Agent API before reaching the web UI.

### `getCandidateDetail`

Returns additional structured candidate information for a candidate id.

- Input: `{ "candidateId": number }`
- Output: BoondManager candidate detail payload.
- Notes: the Agent API merges this into the matching `SearchResult`.

### `getCandidateTechnicalDocument`

Returns the candidate technical document / dossier technique when available.

- Input: `{ "candidateId": number }`
- Output: structured technical-document data such as tools, diplomas, languages,
  activity areas, summaries, and related profile metadata when present.
- Notes: the Agent API treats this as an authoritative source for many profile
  metadata fields.

### `getCandidateCV`

Downloads and parses the candidate CV PDF when a readable resume document is
available in BoondManager.

Input:

```json
{
  "candidateId": 41961
}
```

Output:

```json
{
  "candidateId": 41961,
  "documentId": "13821_resume",
  "fileName": null,
  "contentType": "document",
  "downloadedByteCount": 279643,
  "hasContent": true,
  "extractedText": "Aymane EL IDRISSI | Dossier de compétences ..."
}
```

Behavior:

- Reads `/candidates/{candidateId}/information` to locate resume documents.
- Selects document identifiers such as `{id}_resume`.
- Downloads `/documents/{documentId}` from BoondManager.
- Extracts PDF text with PDFBox.
- Returns `hasContent=false` and an empty `extractedText` when no usable CV is
  found.

Responsibility split:

- MCP: locate the resume, download the PDF, extract text, return metadata.
- Agent API: call `getCandidateCV`, merge the extracted text, generate a short
  LLM-backed `summary` when the LLM backend is configured, and keep a
  deterministic fallback when not.
- Frontend: display the normalized candidate card fields returned by the Agent
  API.

## Error Behavior

Tool failures should be surfaced to the Agent API as typed MCP errors. The Agent
API decides whether to retry, keep partial results, emit safe warnings, or fail
the search. Raw provider stack traces and credentials must never be exposed to
the frontend.
