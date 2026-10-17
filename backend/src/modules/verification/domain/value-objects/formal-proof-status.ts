import { DomainException } from '../../../../common/exceptions/domain.exception';
import { FormalProofStatusValue } from '../enums/formal-proof-status.enum';

export class FormalProofStatus {
  constructor(readonly value: FormalProofStatusValue) {
    if (!Object.values(FormalProofStatusValue).includes(value)) throw new DomainException('Unsupported proof status.');
  }
  get isProvenSafe(): boolean { return this.value === FormalProofStatusValue.UNSAT_PROVEN_SAFE; }
}
