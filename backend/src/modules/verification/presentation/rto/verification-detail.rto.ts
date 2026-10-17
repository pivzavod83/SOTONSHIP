import { ApiProperty } from '@nestjs/swagger';
import { VerificationSummaryRto } from './verification-summary.rto';
import { VerificationRun } from '../../domain/entities/verification-run';
import { JsonObject, JsonValue } from '../../../../common/value-objects/json-value';

export class VerificationDetailRto extends VerificationSummaryRto {
  @ApiProperty() cobolSource!: string;
  @ApiProperty() javaSource!: string;
  @ApiProperty() patchedJavaSource!: string;
  @ApiProperty({ type: 'object', additionalProperties: true }) cpgGraphJson!: JsonObject;
  @ApiProperty({ type: 'array', items: { type: 'object', additionalProperties: true } }) counterexamplesJson!: JsonValue[];
  @ApiProperty({ type: 'object', additionalProperties: true }) provenanceJson!: JsonObject;

  static override fromDomain(run: VerificationRun): VerificationDetailRto {
    const state = run.toPrimitives();
    return Object.assign(new VerificationDetailRto(), VerificationSummaryRto.fromDomain(run), {
      cobolSource: state.cobolSource, javaSource: state.javaSource, patchedJavaSource: state.patchedJavaSource,
      cpgGraphJson: state.cpgGraphJson, counterexamplesJson: state.counterexamplesJson, provenanceJson: state.provenanceJson,
    });
  }
}
