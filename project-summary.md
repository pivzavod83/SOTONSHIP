# Project Summary

Banks are replacing decades-old COBOL systems with modern Java applications, but even a tiny translation error can alter a payment, interest, fee, or currency calculation. A one-penny discrepancy may appear insignificant, yet across millions of transactions it can create financial, regulatory, and customer consequences.

Our project provides a safety and verification layer for this migration process. It uses a Graph Neural Network to compare the structure and financial logic of the original COBOL program with the new Java version, even when code has been renamed or reorganised. A mathematical verification engine then checks whether both programs always produce the same result. If a difference exists, the system identifies the exact transaction that exposes it and can recommend a correction. If verification is not possible, it requests human review instead of making an unsupported claim.

This gives teams evidence-based confidence that modernised banking software preserves the behaviour of the original system.
