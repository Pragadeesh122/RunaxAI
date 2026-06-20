// Document upload constraints. Keep in sync with the backend
// (`api/projects.py`: PROJECT_DOC_SUPPORTED_EXTS, PROJECT_DOC_MAX_BYTES).
export const PROJECT_DOC_SUPPORTED_EXTS = ['pdf', 'txt', 'md', 'csv', 'docx'] as const;
export const PROJECT_DOC_MAX_BYTES = 100 * 1024 * 1024; // 100 MB
export const PROJECT_DOC_MAX_MB = PROJECT_DOC_MAX_BYTES / (1024 * 1024);

// Human-readable list for `accept` attributes and helper copy.
export const PROJECT_DOC_ACCEPT = PROJECT_DOC_SUPPORTED_EXTS.map((e) => `.${e}`).join(',');
export const PROJECT_DOC_SUPPORTED_LABEL = 'PDF, TXT, MD, CSV, or DOCX';

function fileExtension(name: string): string {
  return name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
}

/**
 * Pre-flight validation that mirrors the backend rules, so a new user gets an
 * immediate, friendly message instead of a silent failure after the round-trip.
 * Returns an error string to show, or `null` when the file is acceptable.
 */
export function validateUploadFile(file: File): string | null {
  const ext = fileExtension(file.name);
  if (!ext || !(PROJECT_DOC_SUPPORTED_EXTS as readonly string[]).includes(ext)) {
    return `That file type isn't supported. Upload a ${PROJECT_DOC_SUPPORTED_LABEL} file.`;
  }
  if (file.size <= 0) {
    return 'That file looks empty. Try a different file.';
  }
  if (file.size > PROJECT_DOC_MAX_BYTES) {
    return `That file is too large. The limit is ${PROJECT_DOC_MAX_MB} MB per file.`;
  }
  return null;
}
