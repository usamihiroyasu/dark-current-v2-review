# Experimental environment and reproduction scope

The research environment includes NVIDIA DGX Spark systems, an NVIDIA RTX 4090 system, and an Apple M4 Max system with 128 GB unified memory. This overview does not imply that every study used every device. Hardware and inference settings must be read per study; fleet size is not an experimental denominator.

The manuscript documents the historical self-hosted RTX 4090 and M4 Max evaluations. Studies using private inference services retain their study-specific served identities and request/configuration provenance. A served model label does not establish the upstream checkpoint bytes or the complete vendor build. Consult [the configuration map](STUDY_CONFIGURATION_MAP.json) and the [reproduction map](REPRODUCTION_MAP.md) for each supported replay or inspection layer. Private endpoints, credentials and administrative routes are not distributed.

A reproduction record should identify the relevant model/profile, artifact and runtime versions where verified, prompt renderer, decoder, sampling settings, token limits, sandbox limits, frozen inputs and output/analysis hashes. Unknown fields remain unknown. Recorded local/self-hosted experimental execution does not characterize the entire manuscript-preparation workflow.

Hardware topology is reported only when a retained execution binding establishes its use for that experiment. Network connectivity alone does not establish distributed inference, effective capacity, throughput or speedup. No machine not used by the reported experiment is added to its environment declaration.

Prepared release candidate, not public. Third-party rights and outgoing licensing are distinct from byte integrity.
