import { Injectable } from '@nestjs/common';
import { ApplicationException } from '../../../../common/exceptions/application.exception';
import { GeneratedJavaCandidate, GenerationConfiguration, GenerationInput, ICodeGenerationProvider } from '../../application/ports/code-generation-provider';

/** Intentionally inactive: selecting a provider requires an explicit adapter implementation. */
@Injectable()
export class UnconfiguredCodeGenerationProvider implements ICodeGenerationProvider {
  configuration(): GenerationConfiguration {
    return { adapterEnabled: false, apiKeyPresent: Boolean(process.env.LLM_API_KEY?.trim()),
      providerSelected: Boolean(process.env.LLM_PROVIDER?.trim()), modelSelected: Boolean(process.env.LLM_MODEL?.trim()),
      baseUrlPresent: Boolean(process.env.LLM_BASE_URL?.trim()) };
  }
  async generate(_input: GenerationInput): Promise<GeneratedJavaCandidate> {
    throw new ApplicationException('Code generation is not connected. A provider adapter must be implemented before API credentials are used.', 'generation.not_configured', 503);
  }
}
