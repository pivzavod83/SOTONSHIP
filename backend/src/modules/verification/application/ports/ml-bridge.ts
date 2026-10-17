import { VerificationAnalysis } from '../../domain/entities/verification-run';
import { VerificationCategory } from '../../domain/enums/verification-category.enum';
import { JsonObject } from '../../../../common/value-objects/json-value';

export interface MlVerificationInput {
  id?: string;
  moduleName: string;
  category: VerificationCategory;
  cobolSource: string;
  javaSource: string;
  patchedJavaSource: string;
  proofInputs?: {
    cobolDialectProfile: 'IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1';
    cobolSourceFormat: 'FREE' | 'FIXED';
    amountField: string; rateField: string; resultField: string;
    javaAmountParameter: string; javaRateParameter: string;
    amountMinCents: number; amountMaxCents: number;
    referenceCurrencyPair: string; referenceSource: string; referenceCollectedDate: string;
  };
  referenceFxRates: {
    currencyPair: string; rate: string; source: string; collectedDate: string;
    observationDate?: string; provenanceJson?: JsonObject;
  }[];
}
export const ML_BRIDGE = 'IMlBridge';
export interface IMlBridge { verify(input: MlVerificationInput): Promise<VerificationAnalysis>; }
