import { DomainException } from '../../../../common/exceptions/domain.exception';

export class VerificationId {
  constructor(readonly value: string) {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) {
      throw new DomainException('Verification ID must be a UUID.');
    }
  }
  toString(): string { return this.value; }
}
