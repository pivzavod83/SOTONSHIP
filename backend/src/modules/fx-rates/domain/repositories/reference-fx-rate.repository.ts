import { ReferenceFxRate } from '../entities/reference-fx-rate';

export const FX_RATE_REPOSITORY = 'IReferenceFxRateRepository';
export interface IReferenceFxRateRepository { findAll(): Promise<ReferenceFxRate[]>; }
