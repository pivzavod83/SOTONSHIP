/** Future translation providers return candidates; they cannot return a proof verdict. */
export const CODE_GENERATION_PROVIDER = 'ICodeGenerationProvider';
export interface GenerationInput { cobolSource: string; moduleName: string; inputOutputContract: Record<string, unknown>; }
export interface GeneratedJavaCandidate { javaSource: string; assumptions: string[]; unsupportedConstructs: string[]; provider: string; model: string; promptVersion: string; }
export interface GenerationConfiguration { adapterEnabled: boolean; apiKeyPresent: boolean; providerSelected: boolean; modelSelected: boolean; baseUrlPresent: boolean; }
export interface ICodeGenerationProvider {
  configuration(): GenerationConfiguration;
  generate(input: GenerationInput): Promise<GeneratedJavaCandidate>;
}
