import { DomainException } from '../../../../common/exceptions/domain.exception';

export class RiskScore {
  constructor(readonly value: number) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      throw new DomainException('Scores must be finite numbers between zero and one.');
    }
  }
}
