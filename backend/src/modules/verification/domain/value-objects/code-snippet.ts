import { DomainException } from '../../../../common/exceptions/domain.exception';

export class CodeSnippet {
  constructor(readonly value: string) {
    if (typeof value !== 'string' || !value.trim() || value.length > 200_000) {
      throw new DomainException('Code must contain between 1 and 200,000 characters.');
    }
  }
}
