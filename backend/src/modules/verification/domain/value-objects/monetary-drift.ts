import { DomainException } from '../../../../common/exceptions/domain.exception';

/** Keep exact financial values as decimal strings across all boundaries. */
export class MonetaryDrift {
  constructor(readonly value: string) {
    if (!/^-?\d+(\.\d+)?$/.test(value)) throw new DomainException('Monetary drift must be an exact decimal string.');
  }
  get isZero(): boolean { return /^-?0+(\.0+)?$/.test(this.value); }
}
