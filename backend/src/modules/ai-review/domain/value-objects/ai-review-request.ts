import { DomainException } from '../../../../common/exceptions/domain.exception';

export type ReviewCobolSourceFormat = 'AUTO' | 'FREE' | 'FIXED';
export interface AiReviewRequestInput {
  moduleName: string;
  cobolSource: string;
  javaSource: string;
  cobolSourceFormat?: ReviewCobolSourceFormat;
  analysisContext?: string;
}
export interface AiReviewRequestState extends AiReviewRequestInput { cobolSourceFormat: ReviewCobolSourceFormat; }

function validUnicode(value: string): boolean {
  for (const character of value) {
    const code = character.charCodeAt(0);
    if (character.length === 1 && code >= 0xd800 && code <= 0xdfff) return false;
  }
  return true;
}

/** Exact source text is retained so every hypothesis refers to the supplied pair. */
export class AiReviewRequest {
  private readonly state: AiReviewRequestState;

  constructor(input: AiReviewRequestInput) {
    const invalid = (message: string): never => { throw new DomainException(message, 'ai_review.invalid_request'); };
    if (!input || typeof input.moduleName !== 'string' || !input.moduleName.trim() || input.moduleName.length > 160
      || /[\x00-\x1f]/.test(input.moduleName) || !validUnicode(input.moduleName)) invalid('A valid Unicode module name of 1–160 characters is required.');
    const validSource = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
      && value.length <= 100_000 && value.split('\n').length <= 1500 && !value.includes('\0') && validUnicode(value);
    if (!validSource(input.cobolSource) || !validSource(input.javaSource)) invalid('Each source must contain valid Unicode, 1–100000 characters and at most 1500 lines, without null bytes.');
    const cobolSourceFormat = input.cobolSourceFormat ?? 'AUTO';
    if (!['AUTO', 'FREE', 'FIXED'].includes(cobolSourceFormat)) invalid('COBOL source format is invalid.');
    if (input.analysisContext !== undefined && (typeof input.analysisContext !== 'string' || input.analysisContext.length > 8000 || input.analysisContext.includes('\0') || !validUnicode(input.analysisContext))) {
      invalid('Analysis context must contain valid Unicode and at most 8000 characters without null bytes.');
    }
    this.state = { moduleName: input.moduleName, cobolSource: input.cobolSource, javaSource: input.javaSource, cobolSourceFormat,
      ...(input.analysisContext === undefined ? {} : { analysisContext: input.analysisContext }) };
    if (Buffer.byteLength(JSON.stringify(this.state), 'utf8') > 1_000_000) invalid('The encoded AI review request exceeds 1 MB.');
  }

  toPrimitives(): AiReviewRequestState { return { ...this.state }; }
}
