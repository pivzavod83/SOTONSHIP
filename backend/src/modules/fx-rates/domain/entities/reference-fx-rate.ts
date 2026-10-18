import { DomainException } from '../../../../common/exceptions/domain.exception';
import { JsonObject } from '../../../../common/value-objects/json-value';

export interface ReferenceFxRateProps {
  id: string; currencyPair: string; rate: string; source: string; collectedDate: string;
  observationDate?: string;
  provenanceJson?: JsonObject;
}

export class ReferenceFxRate {
  constructor(private readonly state: ReferenceFxRateProps) {
    if (!/^[A-Z]{3}\/[A-Z]{3}$/.test(state.currencyPair) || !/^\d+(\.\d+)?$/.test(state.rate)
      || /^0+(\.0+)?$/.test(state.rate) || !/^\d{4}-\d{2}-\d{2}$/.test(state.collectedDate) || !state.source.trim()) {
      throw new DomainException('Reference FX rate must have a positive exact rate, currency pair, source and collection date.');
    }
  }
  toPrimitives(): ReferenceFxRateProps { return structuredClone({ ...this.state, provenanceJson: this.state.provenanceJson ?? {} }); }
}
