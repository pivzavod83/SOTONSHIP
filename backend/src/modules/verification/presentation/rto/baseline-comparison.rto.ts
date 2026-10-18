import { ApiProperty } from '@nestjs/swagger';

export class DeterministicBaselineMetricsRto {
  @ApiProperty() meanAlignmentScore!: number;
  @ApiProperty() caughtBugs!: number;
}
export class NeuroSymbolicMetricsRto {
  @ApiProperty() meanAlignmentScore!: number;
  @ApiProperty() flaggedHighRiskModules!: number;
  @ApiProperty() provenCounterexamples!: number;
  @ApiProperty() provenSafeModules!: number;
}
export class BaselineComparisonRto {
  @ApiProperty() totalModules!: number;
  @ApiProperty() completedProofs!: number;
  @ApiProperty() unknownModules!: number;
  @ApiProperty({ type: DeterministicBaselineMetricsRto }) deterministicBaseline!: DeterministicBaselineMetricsRto;
  @ApiProperty({ type: NeuroSymbolicMetricsRto }) neuroSymbolic!: NeuroSymbolicMetricsRto;
  @ApiProperty({ description: 'Explains scope; seeded demo results are not a benchmark accuracy claim.' }) interpretation!: string;
}
