# Omul — Project Summary

Banks modernising COBOL, a long-established banking language, into Java, used for newer applications, must preserve calculations. Different rounding and number-storage rules can silently change payments.

Omul helps engineers review supplied translations. Local AI highlights suspected differences; an independent mathematical checker examines supported calculations. Engineers inspect evidence, compare a reviewed correction and recheck. Unsupported cases remain inconclusive.

Using a [Bank of England rate](https://www.bankofengland.co.uk/boeapps/database/Rates.asp?into=GBP) observed on 15 October 2026, our independently executed, AI-generated example converts £45 into €53.24 in COBOL but €53.23 in Java. This demonstrates a real discrepancy in an educational fixture.

Customers are bank modernisation teams and migration consultancies. Omul provides evidence for their decisions; its experimental detector correctly classified only 1 of 8 held-out examples.

It supports employees rather than replacing jobs or expertise. People retain review and approval. Omul does not automatically translate code or certify production safety.
