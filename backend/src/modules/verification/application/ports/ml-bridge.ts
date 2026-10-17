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
  referenceFxRates: {
    currencyPair: string; rate: string; source: string; collectedDate: string;
    observationDate?: string; provenanceJson?: JsonObject;
  }[];
}
export const ML_BRIDGE = 'IMlBridge';
export interface IMlBridge { verify(input: MlVerificationInput): Promise<VerificationAnalysis>; }
