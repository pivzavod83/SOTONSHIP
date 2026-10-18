import { ReferenceFxRate } from '../../domain/entities/reference-fx-rate';
import { ReferenceFxRateEntity } from '../../entities/reference-fx-rate.entity';

export class ReferenceFxRateMapper {
  static toDomain(row: ReferenceFxRateEntity): ReferenceFxRate {
    return new ReferenceFxRate({
      id: row.id, currencyPair: row.currencyPair, rate: String(row.rate), source: row.source, collectedDate: row.collectedDate,
      observationDate: row.observationDate, provenanceJson: row.provenanceJson,
    });
  }
  static toPersistence(rate: ReferenceFxRate): ReferenceFxRateEntity {
    return Object.assign(new ReferenceFxRateEntity(), rate.toPrimitives());
  }
}
