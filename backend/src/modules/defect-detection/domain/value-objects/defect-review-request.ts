import { DomainException } from '../../../../common/exceptions/domain.exception';

export type DefectCobolSourceFormat = 'FREE' | 'FIXED';
export interface DefectReviewRequestInput {
  cobolSource: string;
  javaSource: string;
  cobolSourceFormat: DefectCobolSourceFormat;
  moduleName?: string;
}
export interface DefectReviewRequestState extends DefectReviewRequestInput {}

function validUnicode(value: string): boolean {
  for (const character of value) {
    const code = character.charCodeAt(0);
    if (character.length === 1 && code >= 0xd800 && code <= 0xdfff) return false;
  }
  return true;
}

/** Retains submitted text exactly; model anchors refer to these raw LF-delimited lines. */
export class DefectReviewRequest {
  private readonly state: DefectReviewRequestState;

  constructor(input: DefectReviewRequestInput) {
    const invalid = (message: string): never => { throw new DomainException(message, 'defect_review.invalid_request'); };
    const validSource = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
      && value.length <= 100_000 && value.split('\n').length <= 1500 && !value.includes('\0') && validUnicode(value)
      && new TextEncoder().encode(value).byteLength <= 200_000;
    if (!input || !validSource(input.cobolSource) || !validSource(input.javaSource)) {
      invalid('Each source must contain valid Unicode, 1–100000 characters, at most 200000 UTF-8 bytes and 1500 lines, without null bytes.');
    }
    if (!['FREE', 'FIXED'].includes(input.cobolSourceFormat)) invalid('Explicit FREE or FIXED COBOL source format is required.');
    if (input.moduleName !== undefined && (typeof input.moduleName !== 'string' || !input.moduleName.trim()
      || input.moduleName.length > 160 || /[\x00-\x1f]/.test(input.moduleName) || !validUnicode(input.moduleName))) {
      invalid('Module name must contain valid Unicode, 1–160 characters and no control characters.');
    }
    this.state = { cobolSource: input.cobolSource, javaSource: input.javaSource, cobolSourceFormat: input.cobolSourceFormat,
      ...(input.moduleName === undefined ? {} : { moduleName: input.moduleName }) };
    if (new TextEncoder().encode(JSON.stringify(this.state)).byteLength > 1_000_000) invalid('The encoded defect review request exceeds 1 MB.');
  }

  toPrimitives(): DefectReviewRequestState { return { ...this.state }; }
}
